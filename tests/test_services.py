"""Testy reguł biznesowych wydzielonych ze stron Streamlita (faza A planu).

Chronią zachowanie, które wcześniej istniało wyłącznie w ciele `pages/1_Nowa_wizyta.py`
i `pages/2_Historia_wizyt.py`, i które łatwo zgubić przy przepisywaniu na FastAPI.
"""

import pytest
from pydantic import ValidationError

from src.services import (
    build_corrected_note,
    clean_icd_rows,
    derive_audio_suffix,
    resolve_note_version,
    split_lines,
)


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
    def test_drops_rows_with_blank_code(self):
        """Wiersz-zaślepka z formularza nie może trafić do notatki."""
        rows = [
            {"code": "F32.1", "description": "Epizod", "confidence": 0.8},
            {"code": "   ", "description": "", "confidence": 0.0},
            {"code": "", "description": "śmieć", "confidence": 0.5},
        ]
        result = clean_icd_rows(rows)
        assert [c.code for c in result] == ["F32.1"]

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
            kody_icd10=[{"code": "F41.1", "description": "Lęk", "confidence": 0.7}],
            zalecenia=["sertralina"],
            podsumowanie="wizyta kontrolna",
        )
        base.update(overrides)
        return base

    def test_builds_valid_note(self):
        note = build_corrected_note(**self._valid_kwargs())
        assert note.ryzyko_samobojcze.value == "NIEOBECNE"
        assert note.kody_icd10[0].code == "F41.1"

    def test_drops_blank_symptoms(self):
        note = build_corrected_note(**self._valid_kwargs())
        assert note.objawy == ["lęk", "bezsenność"]

    def test_strips_risk_description(self):
        note = build_corrected_note(**self._valid_kwargs())
        assert note.ryzyko_samobojcze_opis == "pacjent neguje"

    def test_drops_blank_icd_codes(self):
        note = build_corrected_note(
            **self._valid_kwargs(
                kody_icd10=[
                    {"code": "F32.1", "confidence": 0.9},
                    {"code": "", "confidence": 0.0},
                ]
            )
        )
        assert len(note.kody_icd10) == 1

    def test_invalid_risk_value_raises(self):
        """Nieprawidłowa wartość ryzyka musi wysadzić budowanie — nie wolno zapisać takiej notatki."""
        with pytest.raises(ValueError):
            build_corrected_note(**self._valid_kwargs(ryzyko_samobojcze="MOŻE"))

    def test_missing_required_field_raises(self):
        with pytest.raises(ValidationError):
            build_corrected_note(**self._valid_kwargs(status_psychiczny=None))


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
