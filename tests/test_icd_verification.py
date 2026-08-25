"""Testy weryfikacji rozpoznań w rejestrze WHO.

Punkt wyjścia to realny błąd zgłoszony przez użytkownika: model podał kody ICD-11,
które ISTNIEJĄ, ale znaczą co innego, niż twierdził (QE80 „ofiara przestępstwa"
opisane jako zaburzenia snu). Walidacja formatu tego nie łapie — dlatego opis musi
pochodzić z WHO, a nie od modelu.
"""

import pytest

from src import icd, services
from src.schemas import ICDCode


@pytest.fixture
def fake_who(monkeypatch):
    """Podmienia funkcje sieciowe w module `src.icd`.

    `verify_icd_codes` robi `from . import icd` wewnątrz funkcji, więc podmiana musi
    dotyczyć samego modułu, a nie atrybutu w `services`.
    """

    def _install(codes=None, terms=None, fail=False):
        codes, terms = codes or {}, terms or {}
        counters = {"lookup": 0, "search": 0}

        def lookup_code(code, *, icd11=True, language="pl"):
            counters["lookup"] += 1
            if fail:
                raise icd.IcdUnavailable("brak sieci")
            title = codes.get((code or "").upper())
            return icd.IcdMatch(code=code.upper(), title=title) if title else None

        def search(term, *, icd11=True, language="pl"):
            counters["search"] += 1
            if fail:
                raise icd.IcdUnavailable("brak sieci")
            hit = terms.get((term or "").strip().lower())
            return [icd.IcdMatch(code=hit[0], title=hit[1])] if hit else []

        monkeypatch.setattr(icd, "lookup_code", lookup_code)
        monkeypatch.setattr(icd, "search", search)
        return counters

    return _install


def _verify(proposals, **kwargs):
    return services.verify_icd_codes(proposals, **kwargs)


class TestOfficialTitleWins:
    def test_replaces_model_description_with_who_title(self, fake_who):
        """Dokładnie zgłoszony błąd: QE80 to ofiara przestępstwa, nie zaburzenia snu."""
        fake_who(codes={"QE80": "Victim of crime or terrorism"})

        result = _verify(
            [ICDCode(klasyfikacja="ICD-11", code="QE80", description="Problemy związane ze snem", confidence=0.7)],
            klasyfikacja="ICD-11",
        )

        assert result[0].code == "QE80"
        assert result[0].description == "Victim of crime or terrorism"
        assert result[0].zweryfikowany is True
        # Rozbieżność musi być widoczna, a nie po cichu poprawiona.
        assert "Problemy związane ze snem" in result[0].uwaga
        assert result[0].propozycja_ai == "Problemy związane ze snem"

    def test_no_note_when_model_description_matches(self, fake_who):
        fake_who(codes={"6B00": "Generalised anxiety disorder"})

        result = _verify(
            [ICDCode(klasyfikacja="ICD-11", code="6B00", description="Generalised anxiety disorder", confidence=0.9)],
            klasyfikacja="ICD-11",
        )
        assert result[0].zweryfikowany is True
        assert result[0].uwaga == ""


class TestCodeFromDiagnosisName:
    def test_finds_code_when_model_left_it_empty(self, fake_who):
        fake_who(terms={"zaburzenie lękowe uogólnione": ("6B00", "Generalised anxiety disorder")})

        result = _verify(
            [ICDCode(klasyfikacja="ICD-11", code="", description="Zaburzenie lękowe uogólnione", confidence=0.8)],
            klasyfikacja="ICD-11",
        )
        assert result[0].code == "6B00"
        assert result[0].zweryfikowany is True

    def test_replaces_wrong_code_found_by_name(self, fake_who):
        """6A70 to epizod depresyjny — dla lęku uogólnionego kod ma być zmieniony."""
        fake_who(
            codes={},  # 6A70 nie potwierdza się jako kod dla tego rozpoznania
            terms={"zaburzenie lękowe uogólnione": ("6B00", "Generalised anxiety disorder")},
        )

        result = _verify(
            [ICDCode(klasyfikacja="ICD-11", code="6A70", description="Zaburzenie lękowe uogólnione", confidence=0.8)],
            klasyfikacja="ICD-11",
        )
        assert result[0].code == "6B00"
        assert result[0].zweryfikowany is True
        assert "6A70" in result[0].uwaga


class TestUnverifiable:
    def test_marks_unverified_when_nothing_matches(self, fake_who):
        fake_who()

        result = _verify(
            [ICDCode(klasyfikacja="ICD-11", code="ZZ99", description="Coś wymyślonego", confidence=0.9)],
            klasyfikacja="ICD-11",
        )
        assert result[0].zweryfikowany is False
        assert "Zweryfikuj ręcznie" in result[0].uwaga

    def test_keeps_model_proposal_visible_when_unverified(self, fake_who):
        fake_who()
        result = _verify([ICDCode(klasyfikacja="ICD-10", code="ZZ99", description="Coś", confidence=0.5)])
        assert result[0].code == "ZZ99"
        assert result[0].description == "Coś"

    def test_api_failure_never_breaks_generation(self, fake_who):
        """Awaria WHO nie może wysadzić wizyty — notatka powstaje, kody są oflagowane."""
        fake_who(fail=True)

        result = _verify(
            [
                ICDCode(klasyfikacja="ICD-11", code="6B00", description="Lęk uogólniony", confidence=0.9),
                ICDCode(klasyfikacja="ICD-11", code="6A70", description="Epizod depresyjny", confidence=0.8),
            ],
            klasyfikacja="ICD-11",
        )
        assert len(result) == 2
        assert all(r.zweryfikowany is False for r in result)
        assert all("rejestrem WHO" in r.uwaga for r in result)

    def test_api_failure_is_not_retried_for_every_code(self, fake_who):
        """Po pierwszej awarii nie dobijamy się do martwego API przy każdym kodzie."""
        counters = fake_who(fail=True)
        _verify([ICDCode(klasyfikacja="ICD-11", code=f"X{i}", description="x", confidence=0.5) for i in range(5)])
        assert counters["lookup"] == 1


class TestIcd10Path:
    def test_uses_code_lookup_for_icd10(self, fake_who):
        fake_who(codes={"F41.1": "Generalized anxiety disorder"})

        result = _verify(
            [ICDCode(klasyfikacja="ICD-10", code="F41.1", description="Lęk uogólniony", confidence=0.9)],
            klasyfikacja="ICD-10",
        )
        assert result[0].zweryfikowany is True
        assert result[0].description == "Generalized anxiety disorder"


class TestMultipleClassifications:
    """Notatka może zawierać kilka systemów naraz — każdy wpis idzie własną ścieżką."""

    def test_each_entry_verified_against_its_own_system(self, fake_who):
        fake_who(codes={"6B00": "Generalised anxiety disorder", "F41.1": "Generalized anxiety disorder"})

        result = _verify(
            [
                ICDCode(klasyfikacja="ICD-11", code="6B00", description="Lęk", confidence=0.9),
                ICDCode(klasyfikacja="ICD-10", code="F41.1", description="Lęk", confidence=0.9),
            ]
        )
        assert [r.klasyfikacja for r in result] == ["ICD-11", "ICD-10"]
        assert all(r.zweryfikowany for r in result)

    def test_dict_without_system_falls_back_to_requested(self, fake_who):
        """Wpisy ze starszych notatek nie mają klasyfikacji — bierzemy zamówioną."""
        fake_who(codes={"6B00": "Generalised anxiety disorder"})
        result = _verify(
            [{"code": "6B00", "description": "Lęk", "confidence": 0.9}], klasyfikacja="ICD-11"
        )
        assert result[0].klasyfikacja == "ICD-11"
        assert result[0].zweryfikowany is True


class TestDsm5:
    """DSM-5 wydaje APA — nie ma publicznego rejestru, więc nie da się go potwierdzić."""

    def test_never_marked_verified(self, fake_who):
        fake_who(codes={"300.02": "cokolwiek"})
        result = _verify(
            [ICDCode(klasyfikacja="DSM-5", code="300.02", description="GAD", confidence=0.9)]
        )
        assert result[0].zweryfikowany is False
        assert result[0].klasyfikacja == "DSM-5"
        assert "DSM-5 nie ma publicznego rejestru" in result[0].uwaga

    def test_keeps_diagnosis_name_and_code(self, fake_who):
        fake_who()
        result = _verify(
            [ICDCode(klasyfikacja="DSM-5", code="300.02", description="GAD", confidence=0.9)]
        )
        assert result[0].code == "300.02"
        assert result[0].description == "GAD"

    def test_adds_icd10_crosscheck_when_code_exists_there(self, fake_who):
        """DSM-5 używa kodów ICD-10-CM, więc kontrola w ICD-10 bywa pomocna."""
        fake_who(codes={"F41.1": "Generalized anxiety disorder"})
        result = _verify(
            [ICDCode(klasyfikacja="DSM-5", code="F41.1", description="GAD", confidence=0.9)]
        )
        assert result[0].zweryfikowany is False  # kontrola to nie potwierdzenie
        assert "Kontrolnie" in result[0].uwaga
        assert "Generalized anxiety disorder" in result[0].uwaga

    def test_no_crosscheck_when_no_code_given(self, fake_who):
        counters = fake_who()
        result = _verify([ICDCode(klasyfikacja="DSM-5", code="", description="GAD", confidence=0.9)])
        assert counters["lookup"] == 0
        assert result[0].uwaga == services.DSM5_NOTE


class TestTitleCleaning:
    def test_strips_search_highlight_markup(self):
        assert icd._clean("<em class='found'>Anxiety</em> disorder") == "Anxiety disorder"

    def test_handles_missing_title(self):
        assert icd._clean(None) == ""

    def test_reads_language_tagged_title(self):
        assert icd._title_of({"title": {"@value": "Zaburzenie lękowe"}}) == "Zaburzenie lękowe"


class TestLanguageFallback:
    def test_polish_falls_back_to_english(self):
        assert icd._language_order("pl") == ["pl", "en"]

    def test_english_has_no_duplicate_fallback(self):
        assert icd._language_order("en") == ["en"]
