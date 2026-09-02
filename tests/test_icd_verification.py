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

        def search(term, *, icd11=True, language="pl", trace=None):
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


class TestMeaningMismatchStaysVisible:
    """Ochrona przed pomyleniem kodu ze znaczeniem — powód, dla którego to powstało.

    Opis pokazujemy po polsku, więc porównywanie go z angielskim tytułem rejestru
    nie miałoby sensu: różniłby się zawsze. Porównujemy dwa teksty angielskie —
    termin, jakim model się posłużył, i oficjalny tytuł WHO.
    """

    def test_flags_code_whose_meaning_differs(self, fake_who):
        """Zgłoszony błąd: QE80 to ofiara przestępstwa, nie zaburzenia snu."""
        fake_who(codes={"QE80": "Victim of crime or terrorism"})

        result = _verify(
            [
                ICDCode(
                    klasyfikacja="ICD-11",
                    code="QE80",
                    description="Problemy związane ze snem",
                    termin_wyszukiwania="Sleep problems",
                    confidence=0.7,
                )
            ],
            klasyfikacja="ICD-11",
        )

        assert result[0].code == "QE80"
        # Lekarz czyta po polsku…
        assert result[0].description == "Problemy związane ze snem"
        # …ale oficjalne znaczenie jest widoczne obok i rozjazd jest zgłoszony.
        assert result[0].oficjalna_nazwa == "Victim of crime or terrorism"
        assert "Sleep problems" in result[0].uwaga
        assert "Victim of crime or terrorism" in result[0].uwaga

    def test_no_note_when_meaning_agrees(self, fake_who):
        fake_who(codes={"6B00": "Generalised anxiety disorder"})

        result = _verify(
            [
                ICDCode(
                    klasyfikacja="ICD-11",
                    code="6B00",
                    description="Zaburzenie lękowe uogólnione",
                    termin_wyszukiwania="Generalised anxiety disorder",
                    confidence=0.9,
                )
            ],
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
    """ICD-10 domyślnie przyjmujemy od modelu, bez odpytywania rejestru.

    Powód jest empiryczny: ICD-10 jest w danych treningowych od dekad i model radzi
    sobie z nią dobrze, a odpytywanie rejestru dawało tu fałszywe „nie znaleziono".
    ICD-11 to inna historia — tam model realnie się myli i sprawdzanie zostaje.
    """

    def test_accepts_model_code_without_asking_registry(self, fake_who):
        counters = fake_who(codes={"F41.1": "Generalized anxiety disorder"})

        result = _verify(
            [ICDCode(klasyfikacja="ICD-10", code="F41.1", description="Lęk uogólniony", confidence=0.9)],
            klasyfikacja="ICD-10",
        )
        assert counters["lookup"] == 0, "ICD-10 nie powinno odpytywać rejestru"
        assert result[0].code == "F41.1"
        assert result[0].description == "Lęk uogólniony"

    def test_marked_as_not_checked_not_as_missing(self, fake_who):
        """Kluczowe rozróżnienie: „nie sprawdzano" to nie to samo co „nie ma"."""
        fake_who()
        result = _verify([ICDCode(klasyfikacja="ICD-10", code="F41.1", description="Lęk", confidence=0.9)])
        assert result[0].weryfikacja.value == "NIESPRAWDZANY"
        assert result[0].uwaga == "", "brak sprawdzania nie jest problemem do zgłoszenia"

    def test_missing_code_is_flagged_not_silently_empty(self, fake_who):
        """Bez odpytywania rejestru pusty kod nikt nie uzupełni — musi być widoczny."""
        fake_who()
        result = _verify([ICDCode(klasyfikacja="ICD-10", code="", description="Lęk", confidence=0.9)])
        assert result[0].weryfikacja.value == "NIEPOTWIERDZONY"
        assert "nie podał kodu" in result[0].uwaga

    def test_lookup_returns_when_flag_enabled(self, fake_who, monkeypatch):
        """Flaga VERIFY_ICD10 przywraca sprawdzanie, gdyby okazało się potrzebne."""
        from src import config

        monkeypatch.setattr(config, "VERIFY_ICD10", True)
        fake_who(codes={"F41.1": "Generalized anxiety disorder"})

        result = _verify(
            [ICDCode(klasyfikacja="ICD-10", code="F41.1", description="Lęk uogólniony", confidence=0.9)],
            klasyfikacja="ICD-10",
        )
        assert result[0].weryfikacja.value == "POTWIERDZONY"
        assert result[0].description == "Lęk uogólniony"
        assert result[0].oficjalna_nazwa == "Generalized anxiety disorder"


class TestPolishNameSurvivesLookup:
    """Rejestr odpytujemy po angielsku, ale lekarz ma widzieć polską nazwę."""

    def test_searches_with_english_term(self, fake_who):
        fake_who(terms={"generalised anxiety disorder": ("6B00", "Generalised anxiety disorder")})
        result = _verify(
            [
                ICDCode(
                    klasyfikacja="ICD-11",
                    code="",
                    description="Zaburzenie lękowe uogólnione",
                    termin_wyszukiwania="Generalised anxiety disorder",
                    confidence=0.9,
                )
            ]
        )
        assert result[0].code == "6B00"
        assert result[0].weryfikacja.value == "POTWIERDZONY"

    def test_keeps_polish_description_after_confirmation(self, fake_who):
        fake_who(codes={"6B00": "Generalised anxiety disorder"})
        result = _verify(
            [
                ICDCode(
                    klasyfikacja="ICD-11",
                    code="6B00",
                    description="Zaburzenie lękowe uogólnione",
                    termin_wyszukiwania="Generalised anxiety disorder",
                    confidence=0.9,
                )
            ]
        )
        assert result[0].description == "Zaburzenie lękowe uogólnione"
        # Oficjalne brzmienie zostaje obok — to ono ujawnia rozjazd znaczenia.
        assert result[0].oficjalna_nazwa == "Generalised anxiety disorder"

    def test_falls_back_to_polish_when_english_term_missing(self, fake_who):
        fake_who(terms={"zaburzenie lękowe uogólnione": ("6B00", "Generalised anxiety disorder")})
        result = _verify(
            [ICDCode(klasyfikacja="ICD-11", code="", description="Zaburzenie lękowe uogólnione", confidence=0.9)]
        )
        assert result[0].code == "6B00"


class TestMultipleClassifications:
    """Notatka może zawierać kilka systemów naraz — każdy wpis idzie własną ścieżką."""

    def test_each_entry_follows_rules_of_its_own_system(self, fake_who):
        """ICD-11 idzie do rejestru, ICD-10 nie — każdy wpis własną ścieżką."""
        fake_who(codes={"6B00": "Generalised anxiety disorder"})

        result = _verify(
            [
                ICDCode(klasyfikacja="ICD-11", code="6B00", description="Lęk", confidence=0.9),
                ICDCode(klasyfikacja="ICD-10", code="F41.1", description="Lęk", confidence=0.9),
            ]
        )
        # Wynik jest posortowany klasyfikacjami, więc szukamy po systemie, nie po pozycji.
        by_system = {r.klasyfikacja: r for r in result}
        assert by_system["ICD-11"].weryfikacja.value == "POTWIERDZONY"
        assert by_system["ICD-10"].weryfikacja.value == "NIESPRAWDZANY"

    def test_codes_are_grouped_by_classification(self, fake_who):
        """Model podaje rozpoznaniami; czyta się to klasyfikacjami."""
        fake_who(codes={"6B00": "Generalised anxiety disorder", "7A00": "Chronic insomnia"})
        result = _verify(
            [
                ICDCode(klasyfikacja="ICD-10", code="F41.1", description="Lęk", confidence=0.9),
                ICDCode(klasyfikacja="ICD-11", code="6B00", description="Lęk", confidence=0.9),
                ICDCode(klasyfikacja="DSM-5", code="300.02", description="Lęk", confidence=0.9),
                ICDCode(klasyfikacja="ICD-10", code="F51.0", description="Bezsenność", confidence=0.6),
                ICDCode(klasyfikacja="ICD-11", code="7A00", description="Bezsenność", confidence=0.6),
                ICDCode(klasyfikacja="DSM-5", code="307.42", description="Bezsenność", confidence=0.6),
            ]
        )
        assert [r.klasyfikacja for r in result] == [
            "ICD-10",
            "ICD-10",
            "ICD-11",
            "ICD-11",
            "DSM-5",
            "DSM-5",
        ]

    def test_order_within_a_classification_is_preserved(self, fake_who):
        """Model porządkuje rozpoznania od głównego do pobocznych — tego nie mieszamy."""
        fake_who()
        result = _verify(
            [
                ICDCode(klasyfikacja="DSM-5", code="307.42", description="Bezsenność", confidence=0.6),
                ICDCode(klasyfikacja="ICD-10", code="F32.1", description="Depresja", confidence=0.8),
                ICDCode(klasyfikacja="ICD-10", code="F43.2", description="Adaptacyjne", confidence=0.6),
                ICDCode(klasyfikacja="ICD-10", code="F51.0", description="Bezsenność", confidence=0.5),
            ]
        )
        assert [r.code for r in result] == ["F32.1", "F43.2", "F51.0", "307.42"]

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


class TestEditorRoundTrip:
    """Wiersze wracające z edytora muszą dać się zweryfikować tak samo jak propozycje modelu."""

    def test_english_term_survives_the_editor(self, fake_who):
        fake_who(terms={"generalised anxiety disorder": ("6B00", "Generalised anxiety disorder")})
        rows = [
            {
                "klasyfikacja": "ICD-11",
                "code": "",
                "description": "Zaburzenie lękowe uogólnione",
                "termin_wyszukiwania": "Generalised anxiety disorder",
                "confidence": 0.8,
                # Kolumny tylko do odczytu też wracają z edytora — mają być zignorowane.
                "weryfikacja": "NIEPOTWIERDZONY",
                "uwaga": "cokolwiek",
            }
        ]
        result = services.verify_icd_codes(
            services.clean_icd_rows(rows, default_klasyfikacja="ICD-11"),
            klasyfikacja="ICD-11",
        )
        assert result[0].code == "6B00"
        assert result[0].weryfikacja is services.StanWeryfikacji.POTWIERDZONY
        # Lekarz czyta po polsku; angielskie brzmienie idzie obok.
        assert result[0].description == "Zaburzenie lękowe uogólnione"
        assert result[0].oficjalna_nazwa == "Generalised anxiety disorder"

    def test_search_term_survives_verification(self, fake_who):
        """Weryfikacja nie może zjeść terminu — na nim opiera się każde następne sprawdzenie."""
        fake_who(terms={"chronic insomnia": ("7A00", "Chronic insomnia")})
        confirmed = services.verify_icd_codes(
            [
                ICDCode(
                    klasyfikacja="ICD-11",
                    code="",
                    description="Bezsenność przewlekła",
                    termin_wyszukiwania="Chronic insomnia",
                    confidence=0.7,
                )
            ],
            klasyfikacja="ICD-11",
        )
        assert confirmed[0].termin_wyszukiwania == "Chronic insomnia"

        missing = services.verify_icd_codes(
            [
                ICDCode(
                    klasyfikacja="ICD-11",
                    code="",
                    description="Coś nieznanego",
                    termin_wyszukiwania="Something unknown",
                    confidence=0.7,
                )
            ],
            klasyfikacja="ICD-11",
        )
        assert missing[0].termin_wyszukiwania == "Something unknown"

    def test_not_found_note_names_the_query(self, fake_who):
        """Bez tego nie da się odróżnić „szukaliśmy po angielsku" od „poszła polska nazwa"."""
        fake_who()
        result = services.verify_icd_codes(
            [
                ICDCode(
                    klasyfikacja="ICD-11",
                    code="",
                    description="Bezsenność przewlekła",
                    termin_wyszukiwania="Chronic insomnia",
                    confidence=0.7,
                )
            ],
            klasyfikacja="ICD-11",
        )
        assert "Chronic insomnia" in result[0].uwaga

    def test_not_found_note_reveals_polish_fallback(self, fake_who):
        fake_who()
        result = services.verify_icd_codes(
            [
                ICDCode(
                    klasyfikacja="ICD-11",
                    code="",
                    description="Bezsenność przewlekła",
                    confidence=0.7,
                )
            ],
            klasyfikacja="ICD-11",
        )
        assert "Bezsenność przewlekła" in result[0].uwaga

    def test_polish_name_alone_finds_nothing(self, fake_who):
        """Dowód, po co ta kolumna: rejestr WHO nie zna polskich nazw."""
        fake_who(terms={"generalised anxiety disorder": ("6B00", "Generalised anxiety disorder")})
        rows = [
            {
                "klasyfikacja": "ICD-11",
                "code": "",
                "description": "Zaburzenie lękowe uogólnione",
                "confidence": 0.8,
            }
        ]
        result = services.verify_icd_codes(
            services.clean_icd_rows(rows, default_klasyfikacja="ICD-11"),
            klasyfikacja="ICD-11",
        )
        assert result[0].code == ""
        assert result[0].weryfikacja is services.StanWeryfikacji.NIEPOTWIERDZONY


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


@pytest.fixture
def who_endpoint(monkeypatch):
    """Podstaw warstwę HTTP modułu `icd` i zapamiętaj, o co dokładnie pytał.

    Testujemy tu samo odpytywanie rejestru, więc podmieniamy `_get` (jedyne miejsce,
    w którym moduł dotyka sieci) i token, żeby nie było potrzeby poświadczeń.
    """

    def _install(routes):
        calls: list[tuple[str, dict]] = []

        def fake_request(path, *, language, params=None):
            calls.append((path, dict(params or {})))
            handler = routes.get(path)
            if handler is None:
                return 404, None
            result = handler(params or {}, language) if callable(handler) else handler
            # Trasa może zwrócić sam status, żeby udać błąd HTTP.
            return (result, None) if isinstance(result, int) else (200, result)

        monkeypatch.setattr(icd, "_access_token", lambda: "token-testowy")
        monkeypatch.setattr(icd, "_request", fake_request)
        monkeypatch.setitem(icd._release_cache, "id", "")
        return calls

    return _install


class TestReleaseResolution:
    def test_uses_release_id_from_payload(self, who_endpoint):
        who_endpoint({icd.ICD11_LINEARIZATION: {"releaseId": "2025-01"}})
        assert icd._release_id() == "2025-01"
        assert icd._mms_prefix() == "release/11/2025-01/mms"

    def test_reads_the_releases_list(self, who_endpoint):
        """`@id` listy wydań to sam „release/11" — numer jest wyłącznie w `releases`."""
        who_endpoint(
            {
                icd.ICD11_RELEASES: {
                    "@id": "http://id.who.int/icd/release/11",
                    "releases": [
                        "http://id.who.int/icd/release/11/2025-01",
                        "http://id.who.int/icd/release/11/2024-01",
                    ],
                }
            }
        )
        assert icd._release_id() == "2025-01"

    def test_picks_the_newest_release(self, who_endpoint):
        who_endpoint(
            {
                icd.ICD11_RELEASES: {
                    "@id": "http://id.who.int/icd/release/11",
                    "release": [
                        "http://id.who.int/icd/release/11/2022-02",
                        "http://id.who.int/icd/release/11/2025-01",
                        "http://id.who.int/icd/release/11/2023-01",
                    ],
                }
            }
        )
        assert icd._release_id() == "2025-01"

    def test_falls_back_to_uri(self, who_endpoint):
        who_endpoint(
            {icd.ICD11_LINEARIZATION: {"@id": "http://id.who.int/icd/release/11/2024-01/mms"}}
        )
        assert icd._release_id() == "2024-01"

    def test_unknown_release_keeps_unpinned_address(self, who_endpoint):
        who_endpoint({})
        assert icd._release_id() == ""
        assert icd._mms_prefix() == icd.ICD11_LINEARIZATION


class TestIcd11Search:
    def test_prefers_pinned_release_address(self, who_endpoint):
        calls = who_endpoint(
            {
                icd.ICD11_LINEARIZATION: {"releaseId": "2025-01"},
                "release/11/2025-01/mms/search": {
                    "destinationEntities": [
                        {"theCode": "6B00", "title": "<em>Generalised</em> anxiety disorder"}
                    ]
                },
            }
        )
        assert icd.search("anxiety", language="en") == [
            icd.IcdMatch(code="6B00", title="Generalised anxiety disorder")
        ]
        assert calls[-1][0] == "release/11/2025-01/mms/search"

    def test_falls_back_to_flexisearch(self, who_endpoint):
        def handler(params, _language):
            if params.get("useFlexisearch") != "true":
                return {"destinationEntities": []}
            return {"destinationEntities": [{"theCode": "6A70", "title": "Depressive disorder"}]}

        calls = who_endpoint({icd.ICD11_LINEARIZATION + "/search": handler})
        assert icd.search("depresja", language="en")[0].code == "6A70"
        searches = [params["useFlexisearch"] for path, params in calls if path.endswith("/search")]
        assert searches == ["false", "true"]

    def test_resolves_code_for_entities_without_the_code(self, who_endpoint):
        """Encje z wyszukiwarki bez `theCode` były wcześniej po cichu wyrzucane."""
        who_endpoint(
            {
                icd.ICD11_LINEARIZATION: {"releaseId": "2025-01"},
                "release/11/2025-01/mms/search": {
                    "destinationEntities": [
                        {"id": "http://id.who.int/icd/entity/1635750499", "title": "Anxiety"}
                    ]
                },
                "release/11/2025-01/mms/1635750499": {
                    "code": "6B00",
                    "title": {"@value": "Generalised anxiety disorder"},
                },
            }
        )
        assert icd.search("anxiety", language="en") == [
            icd.IcdMatch(code="6B00", title="Generalised anxiety disorder")
        ]

    def test_empty_result_is_not_an_error(self, who_endpoint):
        who_endpoint({icd.ICD11_LINEARIZATION + "/search": {"destinationEntities": []}})
        assert icd.search("nieistniejące rozpoznanie", language="en") == []

    def test_total_failure_raises_instead_of_reporting_no_hits(self, who_endpoint, monkeypatch):
        """Rejestr niedostępny to co innego niż „nie ma takiego rozpoznania"."""

        def boom(path, *, language, params=None):
            raise icd.IcdUnavailable("WHO odpowiedziało 500.")

        monkeypatch.setattr(icd, "_access_token", lambda: "token-testowy")
        monkeypatch.setattr(icd, "_get", boom)
        monkeypatch.setitem(icd._release_cache, "id", "")
        with pytest.raises(icd.IcdUnavailable):
            icd.search("anxiety", language="en")

    def test_foundation_search_rescues_a_404_linearization(self, who_endpoint):
        """Dokładnie sytuacja z produkcji: warianty linearyzacji zwracają 404."""
        calls = who_endpoint(
            {
                icd.FOUNDATION_SEARCH: {
                    "destinationEntities": [
                        {"id": "http://id.who.int/icd/entity/1635750499", "title": "Anxiety"}
                    ]
                },
                # Encja z fundacji nie ma kodu — kod nadaje linearyzacja.
                f"{icd.ICD11_LINEARIZATION}/1635750499": {
                    "code": "6B00",
                    "title": {"@value": "Generalised anxiety disorder"},
                },
            }
        )
        assert icd.search("generalized anxiety disorder", language="en") == [
            icd.IcdMatch(code="6B00", title="Generalised anxiety disorder")
        ]
        assert any(path == icd.FOUNDATION_SEARCH for path, _ in calls)

    def test_wrong_address_is_not_reported_as_a_missing_diagnosis(self, who_endpoint):
        """404 z wyszukiwarki znaczy „zły adres". Wcześniej `_get` mieliło to na pustą listę."""
        who_endpoint({})  # każda ścieżka odpowiada 404
        with pytest.raises(icd.IcdUnavailable) as exc:
            icd.search("generalised anxiety disorder", language="en")
        assert "404" in str(exc.value)

    def test_server_error_on_every_address_raises(self, who_endpoint):
        who_endpoint({icd.ICD11_LINEARIZATION + "/search": 503})
        with pytest.raises(icd.IcdUnavailable):
            icd.search("anxiety", language="en")

    def test_describe_attempts_separates_the_three_failures(self, who_endpoint):
        who_endpoint({icd.ICD11_LINEARIZATION + "/search": {"destinationEntities": []}})
        trace: list[dict] = []
        icd.search("anxiety", language="en", trace=trace)
        assert icd.describe_attempts(trace) == (
            "wydanie ICD-11: nieustalone; release/11/mms/search: 0 wyników; "
            "entity/search: HTTP 404"
        )

    def test_trace_records_every_attempt(self, who_endpoint):
        who_endpoint({icd.ICD11_LINEARIZATION + "/search": {"destinationEntities": []}})
        trace: list[dict] = []
        icd.search("anxiety", language="en", trace=trace)
        queries = [entry for entry in trace if "path" in entry]
        assert queries and all(entry["path"].endswith("search") for entry in queries)
        assert {entry["flexisearch"] for entry in queries} == {"false", "true"}
        # Pierwszy wpis mówi, czy w ogóle udało się ustalić wydanie.
        assert trace[0]["note"].startswith("wydanie ICD-11:")


class TestIcd11CodeLookup:
    def test_uses_codeinfo(self, who_endpoint):
        calls = who_endpoint(
            {
                icd.ICD11_LINEARIZATION: {"releaseId": "2025-01"},
                "release/11/2025-01/mms/codeinfo/6B00": {
                    "stemId": "http://id.who.int/icd/release/11/2025-01/mms/1635750499"
                },
                "release/11/2025-01/mms/1635750499": {
                    "code": "6B00",
                    "title": "Generalised anxiety disorder",
                },
            }
        )
        hit = icd.lookup_code("6B00", icd11=True, language="en")
        assert hit == icd.IcdMatch(code="6B00", title="Generalised anxiety disorder")
        assert any("codeinfo" in path for path, _ in calls)

    def test_unknown_code_returns_none(self, who_endpoint):
        who_endpoint({icd.ICD11_LINEARIZATION + "/search": {"destinationEntities": []}})
        assert icd.lookup_code("XX99", icd11=True, language="en") is None


class TestRegistryAnswerReachesTheNote:
    """Sprawdzenie okablowania: to, co odpowiedział rejestr, ma dojść do uwagi na ekranie."""

    def test_empty_answer_is_quoted_in_the_note(self, who_endpoint):
        who_endpoint({icd.ICD11_LINEARIZATION + "/search": {"destinationEntities": []}})
        result = services.verify_icd_codes(
            [
                ICDCode(
                    klasyfikacja="ICD-11",
                    code="",
                    description="Bezsenność przewlekła",
                    termin_wyszukiwania="Chronic insomnia",
                    confidence=0.7,
                )
            ],
            klasyfikacja="ICD-11",
        )
        assert "Chronic insomnia" in result[0].uwaga
        assert "0 wyników" in result[0].uwaga

    def test_wrong_address_reads_as_an_outage_not_a_missing_diagnosis(self, who_endpoint):
        who_endpoint({})  # 404 pod każdym adresem
        result = services.verify_icd_codes(
            [
                ICDCode(
                    klasyfikacja="ICD-11",
                    code="",
                    description="Bezsenność przewlekła",
                    termin_wyszukiwania="Chronic insomnia",
                    confidence=0.7,
                )
            ],
            klasyfikacja="ICD-11",
        )
        assert "404" in result[0].uwaga
        assert "Nie znaleziono tego rozpoznania" not in result[0].uwaga


class TestApiErrorPayload:
    def test_http_200_with_error_flag_is_reported(self):
        assert icd._api_error({"error": True, "errorMessage": "zła fraza"}) == "zła fraza"

    def test_normal_payload_has_no_error(self):
        assert icd._api_error({"destinationEntities": []}) == ""
