"""Testy reguł biznesowych wydzielonych ze stron Streamlita (faza A planu).

Chronią zachowanie, które wcześniej istniało wyłącznie w ciele `pages/1_Nowa_wizyta.py`
i `pages/2_Historia_wizyt.py`, i które łatwo zgubić przy przepisywaniu na FastAPI.
"""

import io
import wave
from array import array

import pytest
from pydantic import ValidationError

from src.audio import looks_silent, resolve_audio_mime
from src.formatting import (
    audio_quality_label,
    audio_unusable,
    classification_label,
    classifications_of,
    get_icd_codes,
    group_codes_by_classification,
    note_to_text,
)
from src.pricing import estimate_audio_seconds, format_duration
from src.services import (
    build_corrected_note,
    clean_icd_rows,
    derive_audio_suffix,
    resolve_note_version,
    split_lines,
)


class TestEstimateAudioSeconds:
    def test_estimates_from_audio_tokens(self):
        """32 tokeny na sekundę: 57 600 tokenów to pół godziny."""
        assert estimate_audio_seconds(57_600) == 1800.0

    def test_none_when_no_data(self):
        assert estimate_audio_seconds(0) is None
        assert estimate_audio_seconds(None) is None

    def test_none_when_modality_unknown(self):
        """Bez rozbicia modalności liczba zawiera też prompt tekstowy — nie wolno zgadywać."""
        assert estimate_audio_seconds(57_600, modality_known=False) is None

    def test_none_below_trust_threshold(self):
        """Krótkie nagranie: narzut tekstu promptu dominuje, więc lepiej nie pokazywać nic."""
        assert estimate_audio_seconds(3_840) is None  # ~2 minuty


class TestFormatDuration:
    def test_minutes(self):
        assert format_duration(840) == "14 min"

    def test_hours_and_minutes(self):
        assert format_duration(4980) == "1 h 23 min"

    def test_missing(self):
        assert format_duration(None) == "—"
        assert format_duration(0) == "—"


class TestDeriveAudioSuffix:
    def test_takes_extension_from_filename(self):
        assert derive_audio_suffix("wizyta.MP3") == ".mp3"

    def test_defaults_when_no_extension(self):
        assert derive_audio_suffix("nagranie") == ".wav"

    def test_defaults_when_no_filename(self):
        # nagranie z mikrofonu nie ma nazwy pliku
        assert derive_audio_suffix(None) == ".wav"


class TestSplitLines:
    def test_strips_and_drops_empties(self):
        assert split_lines("  lęk \n\n  bezsenność  \n") == ["lęk", "bezsenność"]

    def test_empty_input(self):
        assert split_lines("") == []
        assert split_lines(None) == []


class TestCleanIcdRows:
    def test_drops_only_completely_empty_rows(self):
        """Zaślepka formularza znika, ale rozpoznanie bez kodu zostaje.

        Pusty kod jest teraz poprawny — kod dobierze rejestr WHO na podstawie nazwy,
        a to bezpieczniejsze niż kod zgadnięty przez model.
        """
        rows = [
            {"code": "F32.1", "description": "Epizod", "confidence": 0.8},
            {"code": "   ", "description": "  ", "confidence": 0.0},
            {"code": "", "description": "Zaburzenie lękowe", "confidence": 0.5},
        ]
        result = clean_icd_rows(rows)
        assert [(c.code, c.description) for c in result] == [
            ("F32.1", "Epizod"),
            ("", "Zaburzenie lękowe"),
        ]

    def test_confidence_none_becomes_zero(self):
        result = clean_icd_rows([{"code": "F41.1", "confidence": None}])
        assert result[0].confidence == 0.0

    def test_confidence_nan_becomes_zero(self):
        """st.data_editor potrafi zwrócić NaN dla pustej komórki liczbowej."""
        result = clean_icd_rows([{"code": "F41.1", "confidence": float("nan")}])
        assert result[0].confidence == 0.0

    def test_confidence_garbage_becomes_zero(self):
        result = clean_icd_rows([{"code": "F41.1", "confidence": "abc"}])
        assert result[0].confidence == 0.0

    def test_confidence_clamped_to_range(self):
        """PsychiatricNote wymaga 0.0-1.0, więc wartość spoza zakresu nie może wysadzić walidacji."""
        assert clean_icd_rows([{"code": "F1", "confidence": 5.0}])[0].confidence == 1.0
        assert clean_icd_rows([{"code": "F2", "confidence": -3.0}])[0].confidence == 0.0

    def test_missing_description_becomes_empty_string(self):
        assert clean_icd_rows([{"code": "F41.1", "confidence": 0.5}])[0].description == ""


class TestBuildCorrectedNote:
    def _valid_kwargs(self, **overrides):
        base = dict(
            raw_transcript="transkrypcja",
            ryzyko_samobojcze="NIEOBECNE",
            ryzyko_samobojcze_opis="  pacjent neguje  ",
            status_psychiczny="w kontakcie logicznym",
            objawy=["lęk", "  ", "bezsenność"],
            kody_icd=[{"code": "F41.1", "description": "Lęk", "confidence": 0.7}],
            zalecenia_terapeuty=["sertralina"],
            podsumowanie="wizyta kontrolna",
        )
        base.update(overrides)
        return base

    def test_builds_valid_note(self):
        note = build_corrected_note(**self._valid_kwargs())
        assert note.ryzyko_samobojcze.value == "NIEOBECNE"
        assert note.kody_icd[0].code == "F41.1"

    def test_classification_is_recorded(self):
        note = build_corrected_note(**self._valid_kwargs(klasyfikacje=["ICD-11"]))
        assert [k.value for k in note.klasyfikacje] == ["ICD-11"]

    def test_rejects_unknown_classification(self):
        with pytest.raises(ValueError):
            build_corrected_note(**self._valid_kwargs(klasyfikacje=["ICD-9"]))

    def test_drops_blank_symptoms(self):
        note = build_corrected_note(**self._valid_kwargs())
        assert note.objawy == ["lęk", "bezsenność"]

    def test_strips_risk_description(self):
        note = build_corrected_note(**self._valid_kwargs())
        assert note.ryzyko_samobojcze_opis == "pacjent neguje"

    def test_drops_blank_icd_codes(self):
        note = build_corrected_note(
            **self._valid_kwargs(
                kody_icd=[
                    {"code": "F32.1", "confidence": 0.9},
                    {"code": "", "confidence": 0.0},
                ]
            )
        )
        assert len(note.kody_icd) == 1

    def test_invalid_risk_value_raises(self):
        """Nieprawidłowa wartość ryzyka musi wysadzić budowanie — nie wolno zapisać takiej notatki."""
        with pytest.raises(ValueError):
            build_corrected_note(**self._valid_kwargs(ryzyko_samobojcze="MOŻE"))

    def test_missing_required_field_raises(self):
        with pytest.raises(ValidationError):
            build_corrected_note(**self._valid_kwargs(status_psychiczny=None))


def _wav_bytes(samples: list[int], *, framerate: int = 16000) -> bytes:
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(framerate)
        w.writeframes(array("h", samples).tobytes())
    return buf.getvalue()


class TestLooksSilent:
    """Wykrywanie martwego mikrofonu — przeglądarka nagrywa, ale nie dostaje sygnału."""

    def test_empty_payload_is_silent(self):
        assert looks_silent(b"") is True

    def test_tiny_payload_is_silent(self):
        assert looks_silent(b"RIFF" + b"\x00" * 100) is True

    def test_wav_of_pure_zeros_is_silent(self):
        assert looks_silent(_wav_bytes([0] * 16000)) is True

    def test_wav_with_speech_level_audio_is_not_silent(self):
        loud = [12000 if i % 2 else -12000 for i in range(16000)]
        assert looks_silent(_wav_bytes(loud)) is False

    def test_faint_background_noise_still_counts_as_silent(self):
        """Kilka jednostek szumu kwantyzacji to nadal martwy mikrofon."""
        assert looks_silent(_wav_bytes([1, -1] * 8000)) is True

    def test_quiet_but_real_speech_passes(self):
        """Cicha mowa musi przejść — próg nie może blokować normalnego nagrania."""
        quiet = [400 if i % 2 else -400 for i in range(16000)]
        assert looks_silent(_wav_bytes(quiet)) is False

    def test_undecodable_container_judged_only_by_size(self):
        """Webm/mp4 nie dekodujemy — lepiej przepuścić niż zablokować dobre nagranie."""
        assert looks_silent(b"\x1aE\xdf\xa3" + b"\x00" * 50_000, "audio/webm") is False


class TestResolveAudioMime:
    """Najważniejsza poprawka: zły typ MIME sprawiał, że model zmyślał transkrypcję."""

    def test_browser_mime_wins_over_extension(self):
        """st.audio_input zapisuje jako .wav, ale przeglądarka może nagrać webm."""
        assert resolve_audio_mime(".wav", "audio/webm") == "audio/webm"

    def test_strips_codec_parameters(self):
        assert resolve_audio_mime(".wav", "audio/webm;codecs=opus") == "audio/webm"

    def test_accepts_video_container_for_audio_only_recording(self):
        """Przeglądarki potrafią zwrócić video/webm dla nagrania z samym dźwiękiem."""
        assert resolve_audio_mime(".webm", "video/webm") == "video/webm"

    def test_falls_back_to_extension(self):
        assert resolve_audio_mime(".mp3", None) == "audio/mpeg"
        assert resolve_audio_mime(".m4a", None) == "audio/mp4"

    def test_ignores_nonsense_declared_type(self):
        assert resolve_audio_mime(".mp3", "application/octet-stream") == "audio/mpeg"

    def test_unknown_extension_defaults_to_wav(self):
        assert resolve_audio_mime(".xyz", None) == "audio/wav"
        assert resolve_audio_mime(None, None) == "audio/wav"


class TestBackwardCompatibility:
    """Notatki zapisane przed dodaniem wyboru ICD-11 muszą dalej się otwierać."""

    def test_reads_legacy_icd_key(self):
        legacy = {"kody_icd10": [{"code": "F32.1", "description": "Epizod", "confidence": 0.8}]}
        assert get_icd_codes(legacy)[0]["code"] == "F32.1"

    def test_reads_new_icd_key(self):
        current = {"kody_icd": [{"code": "6A70.1", "description": "Epizod", "confidence": 0.8}]}
        assert get_icd_codes(current)[0]["code"] == "6A70.1"

    def test_no_codes_at_all(self):
        assert get_icd_codes({}) == []

    def test_legacy_note_defaults_to_icd10(self):
        """Notatka bez pola klasyfikacji powstała, gdy istniało tylko ICD-10."""
        assert classification_label({}) == "ICD-10"

    def test_reads_legacy_single_classification(self):
        """Notatki sprzed wyboru wielu systemów mają pojedyncze `klasyfikacja`."""
        assert classification_label({"klasyfikacja": "ICD-11"}) == "ICD-11"

    def test_reads_multiple_classifications(self):
        note = {"klasyfikacje": ["ICD-10", "DSM-5"]}
        assert classifications_of(note) == ["ICD-10", "DSM-5"]
        assert classification_label(note) == "ICD-10 + DSM-5"


class TestSplitRecommendations:
    """Zalecenia z wizyty muszą być oddzielone od propozycji asystenta."""

    def test_keeps_both_lists_separate(self):
        note = build_corrected_note(
            raw_transcript="t",
            ryzyko_samobojcze="NIEOBECNE",
            status_psychiczny="ok",
            objawy=[],
            kody_icd=[],
            zalecenia_terapeuty=["sertralina 50 mg"],
            zalecenia_proponowane=["rozważyć psychoterapię CBT"],
            podsumowanie="p",
        )
        assert note.zalecenia_terapeuty == ["sertralina 50 mg"]
        assert note.zalecenia_proponowane == ["rozważyć psychoterapię CBT"]

    def test_copyable_text_marks_proposals_as_not_said(self):
        note = {
            "ryzyko_samobojcze": "NIEOBECNE",
            "zalecenia_terapeuty": ["sertralina 50 mg"],
            "zalecenia_proponowane": ["rozważyć CBT"],
        }
        text = note_to_text(note, title="Wizyta #1")
        assert "ZALECENIA\n- sertralina 50 mg" in text
        assert "PROPOZYCJE DO ROZWAŻENIA" in text
        assert "nie padły na wizycie" in text
        # kolejność: najpierw to, co faktycznie zalecono
        assert text.index("ZALECENIA\n") < text.index("PROPOZYCJE")

    def test_legacy_note_recommendations_still_render(self):
        """Notatki sprzed podziału mają jedno pole `zalecenia`."""
        note = {"ryzyko_samobojcze": "NIEOBECNE", "zalecenia": ["stara pozycja"]}
        text = note_to_text(note, title="Wizyta #1")
        assert "ZALECENIA\n- stara pozycja" in text
        assert "PROPOZYCJE DO ROZWAŻENIA" not in text


class TestGroupCodesByClassification:
    def test_groups_in_requested_order(self):
        note = {
            "klasyfikacje": ["ICD-10", "DSM-5"],
            "kody_icd": [
                {"klasyfikacja": "DSM-5", "code": "300.02", "description": "GAD"},
                {"klasyfikacja": "ICD-10", "code": "F41.1", "description": "Lęk uogólniony"},
            ],
        }
        grouped = group_codes_by_classification(note)
        assert list(grouped) == ["ICD-10", "DSM-5"]
        assert grouped["ICD-10"][0]["code"] == "F41.1"
        assert grouped["DSM-5"][0]["code"] == "300.02"

    def test_codes_without_system_fall_into_first_classification(self):
        note = {"klasyfikacje": ["ICD-11"], "kody_icd": [{"code": "6B00", "description": "GAD"}]}
        assert list(group_codes_by_classification(note)) == ["ICD-11"]

    def test_legacy_note_groups_under_icd10(self):
        note = {"kody_icd10": [{"code": "F41.1", "description": "Lęk"}]}
        assert list(group_codes_by_classification(note)) == ["ICD-10"]

    def test_copyable_text_separates_systems(self):
        """Lekarz wkleja ten tekst do dokumentacji — systemy nie mogą się zlewać."""
        note = {
            "ryzyko_samobojcze": "NIEOBECNE",
            "klasyfikacje": ["ICD-10", "DSM-5"],
            "kody_icd": [
                {"klasyfikacja": "ICD-10", "code": "F41.1", "description": "Lęk", "zweryfikowany": True},
                {"klasyfikacja": "DSM-5", "code": "300.02", "description": "GAD", "zweryfikowany": False},
            ],
        }
        text = note_to_text(note, title="Wizyta #1")
        assert "ROZPOZNANIA (ICD-10)" in text
        assert "ROZPOZNANIA (DSM-5)" in text
        # tylko DSM-5 jest niepotwierdzony
        assert "300.02 — GAD [DO WERYFIKACJI]" in text
        assert "F41.1 — Lęk\n" in text

    def test_legacy_note_has_no_audio_warning(self):
        """Stare notatki nie mają pola jakości — nie wolno straszyć fałszywym alarmem."""
        assert audio_unusable({}) is False
        assert audio_quality_label({}) is None


class TestAudioQualityFlags:
    def test_flags_unusable_recording(self):
        note = {"jakosc_nagrania": "BRAK_MOWY"}
        assert audio_unusable(note) is True
        assert "nie wykryto zrozumiałej mowy" in audio_quality_label(note)

    def test_flags_poor_recording_without_marking_unusable(self):
        note = {"jakosc_nagrania": "SLABA"}
        assert audio_unusable(note) is False
        assert audio_quality_label(note) is not None

    def test_good_recording_has_no_warning(self):
        assert audio_quality_label({"jakosc_nagrania": "DOBRA"}) is None

    def test_warning_appears_in_copyable_text(self):
        """Ostrzeżenie musi trafić też do tekstu, który lekarz wkleja do dokumentacji."""
        note = {
            "jakosc_nagrania": "BRAK_MOWY",
            "ryzyko_samobojcze": "NIEOBECNE",
            "podsumowanie": "brak danych",
        }
        text = note_to_text(note, title="Wizyta #1")
        assert "UWAGA" in text
        # ostrzeżenie przed treścią notatki
        assert text.index("UWAGA") < text.index("MYŚLI SAMOBÓJCZE")


class TestResolveNoteVersion:
    def test_prefers_doctor_corrected_version(self):
        visit = {
            "ai_note_original_json": '{"podsumowanie": "wersja AI"}',
            "doctor_note_corrected_json": '{"podsumowanie": "wersja lekarza"}',
        }
        resolved = resolve_note_version(visit)
        assert resolved.is_corrected is True
        assert resolved.note["podsumowanie"] == "wersja lekarza"

    def test_falls_back_to_ai_original(self):
        visit = {"ai_note_original_json": '{"podsumowanie": "wersja AI"}', "doctor_note_corrected_json": None}
        resolved = resolve_note_version(visit)
        assert resolved.is_corrected is False
        assert resolved.note["podsumowanie"] == "wersja AI"

    def test_broken_json_does_not_raise(self):
        """Uszkodzony JSON ma zwrócić surowy tekst do pokazania, a nie wysadzić stronę."""
        visit = {"ai_note_original_json": "{to nie jest json", "doctor_note_corrected_json": None}
        resolved = resolve_note_version(visit)
        assert resolved.note is None
        assert resolved.is_parsable is False
        assert resolved.source_json == "{to nie jest json"

    def test_no_note_at_all(self):
        resolved = resolve_note_version({})
        assert resolved.note is None
        assert resolved.source_json is None
