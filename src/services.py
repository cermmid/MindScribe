"""Warstwa serwisowa — logika przypadków użycia, bez żadnej zależności od UI.

Ten moduł celowo **nie importuje streamlita ani pandas**. Cała logika, która wcześniej
mieszkała w ciele stron `pages/`, jest tutaj, żeby dało się ją wywołać tak samo z
Streamlita, jak i z backendu FastAPI (patrz plan iteracji 4, faza A).

Reguły biznesowe zakodowane w tym pliku:
- notatka zostaje `approved` WYŁĄCZNIE po walidacji `PsychiatricNote` (inaczej wyjątek),
- wiersze ICD-10 z pustym kodem są odrzucane,
- `confidence` jest zabezpieczone przed `None`/`NaN` z edytora tabeli,
- przy odczycie wygrywa wersja poprawiona przez lekarza, a oryginał AI jest fallbackiem.
"""

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable, Mapping

from .audio import save_uploaded_audio
from .db import get_approved_examples, get_visit, insert_visit, update_visit
from .schemas import (
    ICDCode,
    JakoscNagrania,
    Klasyfikacja,
    PsychiatricNote,
    RyzykoSamobojcze,
    VerifiedICDCode,
)

# `gemini_client` ciągnie za sobą cały SDK Google, więc importujemy go leniwie —
# czyste reguły walidacji z tego modułu dają się wtedy testować bez SDK.

DEFAULT_AUDIO_SUFFIX = ".wav"


# --- Pomocnicze konwersje wejścia ---------------------------------------------


def derive_audio_suffix(filename: str | None, *, default: str = DEFAULT_AUDIO_SUFFIX) -> str:
    """Rozszerzenie pliku audio na podstawie nazwy uploadu.

    Nagranie z mikrofonu nie ma nazwy — wtedy zwracamy domyślne `.wav`.
    """
    if not filename or "." not in filename:
        return default
    ext = filename.rsplit(".", 1)[-1].strip().lower()
    return f".{ext}" if ext else default


def split_lines(text: str | None) -> list[str]:
    """Zamień pole tekstowe (jedna pozycja w linii) na listę, odrzucając puste.

    Używane przez UI Streamlita. Klient mobilny będzie operował na prawdziwych
    listach i nie będzie tego potrzebował.
    """
    if not text:
        return []
    return [line.strip() for line in text.splitlines() if line.strip()]


def clean_icd_rows(
    rows: Iterable[Mapping[str, Any]], *, default_klasyfikacja: str = "ICD-10"
) -> list[ICDCode]:
    """Zamień surowe wiersze z edytora na propozycje rozpoznań.

    Odrzucamy wyłącznie wiersze **całkiem puste** — tak znika zaślepka z formularza.
    Sam pusty kod jest poprawny: rozpoznanie opisane nazwą dostanie kod z rejestru WHO,
    a to bezpieczniejsze niż kod zgadnięty przez model.

    `confidence` bywa `None` albo `NaN`, stąd podwójne zabezpieczenie.
    """
    cleaned: list[ICDCode] = []
    for row in rows:
        code = str(row.get("code") or "").strip()
        description = str(row.get("description") or "").strip()
        if not code and not description:
            continue
        raw_conf = row.get("confidence")
        try:
            confidence = float(raw_conf) if raw_conf is not None else 0.0
        except (TypeError, ValueError):
            confidence = 0.0
        if confidence != confidence:  # NaN
            confidence = 0.0
        confidence = min(max(confidence, 0.0), 1.0)
        cleaned.append(
            ICDCode(
                klasyfikacja=Klasyfikacja(
                    _normalize_klasyfikacja(row.get("klasyfikacja") or default_klasyfikacja)
                ),
                code=code,
                description=description,
                confidence=confidence,
            )
        )
    return cleaned


# --- Weryfikacja rozpoznań w rejestrze WHO -------------------------------------


DSM5_NOTE = (
    "DSM-5 nie ma publicznego rejestru, więc tego wpisu nie da się potwierdzić "
    "automatycznie — zweryfikuj w podręczniku DSM-5."
)


def _normalize_klasyfikacja(value: Any) -> str:
    text = str(getattr(value, "value", value) or "").strip().upper().replace(" ", "")
    if text in {"ICD-11", "ICD11"}:
        return "ICD-11"
    if text in {"DSM-5", "DSM5", "DSMV"}:
        return "DSM-5"
    return "ICD-10"


def verify_icd_codes(
    proposals: Iterable[ICDCode | Mapping[str, Any]],
    *,
    klasyfikacja: str = "ICD-10",
) -> list[VerifiedICDCode]:
    """Sprawdź propozycje modelu w API WHO i zastąp opisy oficjalnymi tytułami.

    Każdy wpis weryfikowany jest wg **własnej** klasyfikacji, bo notatka może zawierać
    kilka systemów naraz. `klasyfikacja` to wartość zapasowa dla wpisów bez tej informacji.

    Kolejność działań:
    1. jeśli model podał kod — potwierdź go i weź oficjalny tytuł,
    2. jeśli kodu brak albo nie istnieje — wyszukaj po nazwie rozpoznania,
    3. jeśli i to zawiedzie — zostaw propozycję oznaczoną jako niezweryfikowana.

    DSM-5 jest wydawany przez APA i nie ma publicznego rejestru, więc jego wpisów nie
    potwierdzamy. Ponieważ DSM-5 posługuje się kodami ICD-10-CM, robimy jedynie kontrolę
    pomocniczą w ICD-10 i zapisujemy jej wynik w uwadze — to wskazówka, nie potwierdzenie.

    Awaria API nigdy nie przerywa pracy: wszystko wraca jako niezweryfikowane
    z czytelną uwagą, a lekarz decyduje.
    """
    from . import icd

    fallback = _normalize_klasyfikacja(klasyfikacja)
    results: list[VerifiedICDCode] = []
    api_down_note = ""

    for proposal in proposals:
        if isinstance(proposal, ICDCode):
            item = proposal
        else:
            # Wpisy ze starszych notatek i z edytora nie muszą mieć klasyfikacji —
            # w schemacie modelu jest wymagana, tutaj uzupełniamy zamówioną.
            data = dict(proposal)
            data.setdefault("klasyfikacja", fallback)
            item = ICDCode(**data)
        proposed_name = (item.description or "").strip()
        proposed_code = (item.code or "").strip()
        system = _normalize_klasyfikacja(item.klasyfikacja)
        icd11 = system == "ICD-11"

        if system == "DSM-5":
            results.append(_verify_dsm5(item, system, api_down_note))
            continue

        if api_down_note:
            results.append(_unverified(item, api_down_note, system))
            continue

        try:
            match = icd.lookup_code(proposed_code, icd11=icd11) if proposed_code else None
            searched = None
            if match is None and proposed_name:
                candidates = icd.search(proposed_name, icd11=icd11)
                searched = candidates[0] if candidates else None
        except icd.IcdUnavailable as exc:
            api_down_note = (
                "Nie udało się połączyć z rejestrem WHO — kod NIE został zweryfikowany. "
                f"({exc})"
            )
            results.append(_unverified(item, api_down_note, system))
            continue

        if match is not None:
            note = ""
            if proposed_name and _differs(proposed_name, match.title):
                note = f"Model opisał ten kod jako „{proposed_name}” — oficjalnie to „{match.title}”."
            results.append(
                VerifiedICDCode(
                    klasyfikacja=system,
                    code=match.code,
                    description=match.title,
                    confidence=item.confidence,
                    zweryfikowany=True,
                    propozycja_ai=proposed_name if note else "",
                    uwaga=note,
                )
            )
        elif searched is not None:
            note = ""
            if proposed_code:
                note = (
                    f"Kod zaproponowany przez model ({proposed_code}) nie istnieje w {system} "
                    f"albo nie pasuje — dobrano {searched.code} na podstawie nazwy rozpoznania."
                )
            results.append(
                VerifiedICDCode(
                    klasyfikacja=system,
                    code=searched.code,
                    description=searched.title,
                    confidence=item.confidence,
                    zweryfikowany=True,
                    propozycja_ai=proposed_name,
                    uwaga=note,
                )
            )
        else:
            results.append(
                _unverified(
                    item,
                    f"Nie znaleziono tego rozpoznania w rejestrze WHO dla {system}. "
                    "Zweryfikuj ręcznie przed wpisaniem do dokumentacji.",
                    system,
                )
            )

    return results


def _verify_dsm5(item: ICDCode, system: str, api_down_note: str) -> VerifiedICDCode:
    """DSM-5 zawsze wraca jako niezweryfikowany — nie ma publicznego rejestru do sprawdzenia.

    DSM-5 posługuje się kodami ICD-10-CM, więc gdy model podał kod, robimy pomocniczą
    kontrolę w ICD-10 i dopisujemy jej wynik. To wskazówka dla lekarza, nie potwierdzenie:
    ICD-10-CM to amerykańska modyfikacja ICD-10 i nie każdy jej kod istnieje w wersji WHO.
    """
    from . import icd

    note = DSM5_NOTE
    code = (item.code or "").strip()
    if code and not api_down_note:
        try:
            crosscheck = icd.lookup_code(code, icd11=False)
        except icd.IcdUnavailable:
            crosscheck = None
        if crosscheck is not None:
            note = f"{DSM5_NOTE} Kontrolnie: {code} w ICD-10 to „{crosscheck.title}”."
    return _unverified(item, note, system)


def _unverified(item: ICDCode, note: str, system: str = "") -> VerifiedICDCode:
    return VerifiedICDCode(
        klasyfikacja=system or _normalize_klasyfikacja(getattr(item, "klasyfikacja", None)),
        code=(item.code or "").strip(),
        description=(item.description or "").strip(),
        confidence=item.confidence,
        zweryfikowany=False,
        uwaga=note,
    )


def _differs(a: str, b: str) -> bool:
    """Czy dwie nazwy rozpoznania są istotnie różne (pomijając wielkość liter i interpunkcję)."""
    normalize = lambda s: "".join(ch for ch in s.lower() if ch.isalnum())  # noqa: E731
    return normalize(a) != normalize(b)


# --- Przypadek użycia: utworzenie wizyty ---------------------------------------


@dataclass
class CreatedVisit:
    visit_id: int
    note: PsychiatricNote
    debug_prompt: str
    usage: dict[str, Any] = field(default_factory=dict)
    few_shot_count: int = 0


def load_few_shot_examples(doctor_id: str | None = None) -> list[dict[str, str]]:
    """Zatwierdzone notatki zasilające few-shot.

    `doctor_id` jest na razie przekazywane dalej bez filtrowania — separacja per
    użytkownik wchodzi w fazie B razem z migracją na Postgresa.
    """
    return get_approved_examples(doctor_id=doctor_id)


def create_visit_from_audio(
    audio_bytes: bytes,
    *,
    audio_suffix: str = DEFAULT_AUDIO_SUFFIX,
    audio_mime: str | None = None,
    visit_label: str | None = None,
    visit_type: str | None = None,
    doctor_id: str | None = None,
    few_shot: list[dict[str, str]] | None = None,
    pipeline: str = "multimodal",
    klasyfikacje: list[str] | str = "ICD-10",
) -> CreatedVisit:
    """Pełna ścieżka: zapis audio → few-shot → Gemini → zapis wizyty jako draft.

    `audio_mime` to typ zgłoszony przez przeglądarkę. Przekazuj go zawsze, gdy jest
    dostępny — bez niego zgadujemy z rozszerzenia, a przy nagraniu z mikrofonu
    rozszerzenie bywa nieprawdziwe.

    Wyjątki z wywołania Gemini są propagowane — wołający decyduje, jak je pokazać.
    """
    from .gemini_client import generate_note_from_audio

    if not audio_bytes:
        raise ValueError("Brak danych audio.")

    if few_shot is None:
        few_shot = load_few_shot_examples(doctor_id)

    wanted = [klasyfikacje] if isinstance(klasyfikacje, str) else list(klasyfikacje)
    wanted = wanted or ["ICD-10"]

    audio_path: Path = save_uploaded_audio(audio_bytes, suffix=audio_suffix)
    draft, debug_prompt, usage = generate_note_from_audio(
        audio_path, few_shot, mime_type=audio_mime, klasyfikacje=wanted
    )

    # Kody od modelu są tylko propozycją — do notatki trafiają dopiero po sprawdzeniu w WHO.
    note = PsychiatricNote(
        **draft.model_dump(exclude={"kody_icd", "klasyfikacje"}),
        klasyfikacje=[Klasyfikacja(k) for k in wanted],
        kody_icd=verify_icd_codes(draft.kody_icd, klasyfikacja=wanted[0]),
    )

    visit_id = insert_visit(
        audio_path=str(audio_path),
        pipeline=pipeline,
        raw_transcript=note.raw_transcript,
        ai_note_original_json=note.model_dump_json(indent=2),
        visit_label=(visit_label or "").strip() or None,
        visit_type=visit_type,
        doctor_id=doctor_id,
        usage=usage,
    )
    return CreatedVisit(
        visit_id=visit_id,
        note=note,
        debug_prompt=debug_prompt,
        usage=usage,
        few_shot_count=len(few_shot),
    )


# --- Przypadek użycia: zatwierdzenie notatki -----------------------------------


def build_corrected_note(
    *,
    raw_transcript: str,
    ryzyko_samobojcze: str,
    ryzyko_samobojcze_opis: str = "",
    status_psychiczny: str,
    objawy: Iterable[str],
    kody_icd: Iterable[Mapping[str, Any]] | Iterable[ICDCode],
    zalecenia_terapeuty: Iterable[str],
    zalecenia_proponowane: Iterable[str] = (),
    podsumowanie: str,
    klasyfikacje: list[str] | str = "ICD-10",
    jakosc_nagrania: str = "DOBRA",
    verify: bool = True,
) -> PsychiatricNote:
    """Zbuduj i zwaliduj poprawioną notatkę. Rzuca `ValidationError`, gdy dane są złe.

    Kody poprawione ręcznie przez lekarza też przechodzą weryfikację w WHO — inaczej
    literówka w kodzie trafiłaby do dokumentacji bez żadnej kontroli.
    """
    wanted = [klasyfikacje] if isinstance(klasyfikacje, str) else list(klasyfikacje)
    wanted = wanted or ["ICD-10"]

    icd_list = list(kody_icd)
    proposals = (
        icd_list
        if icd_list and isinstance(icd_list[0], ICDCode)
        else clean_icd_rows(icd_list, default_klasyfikacja=wanted[0])  # type: ignore[arg-type]
    )
    codes = (
        verify_icd_codes(proposals, klasyfikacja=wanted[0])
        if verify
        else [_unverified(p, "Weryfikacja pominięta.") for p in proposals]
    )
    return PsychiatricNote(
        jakosc_nagrania=JakoscNagrania(jakosc_nagrania),
        raw_transcript=raw_transcript,
        klasyfikacje=[Klasyfikacja(k) for k in wanted],
        ryzyko_samobojcze=RyzykoSamobojcze(ryzyko_samobojcze),
        ryzyko_samobojcze_opis=(ryzyko_samobojcze_opis or "").strip(),
        status_psychiczny=status_psychiczny,
        objawy=[s for s in (str(o).strip() for o in objawy) if s],
        kody_icd=list(codes),
        zalecenia_terapeuty=[s for s in (str(z).strip() for z in zalecenia_terapeuty) if s],
        zalecenia_proponowane=[s for s in (str(z).strip() for z in zalecenia_proponowane) if s],
        podsumowanie=podsumowanie,
    )


def approve_note(visit_id: int, note: PsychiatricNote, *, doctor_id: str | None = None) -> None:
    """Zapisz zwalidowaną notatkę i oznacz wizytę jako zatwierdzoną.

    Wywoływać **wyłącznie** z obiektem, który przeszedł walidację `PsychiatricNote` —
    tylko taka notatka trafia potem do few-shot.
    """
    update_visit(
        visit_id,
        doctor_note_corrected_json=note.model_dump_json(indent=2),
        status="approved",
        doctor_id=doctor_id,
    )


# --- Przypadek użycia: odczyt wizyty -------------------------------------------


@dataclass
class ResolvedNote:
    """Która wersja notatki jest pokazywana i czy da się ją sparsować."""

    note: dict[str, Any] | None
    source_json: str | None
    is_corrected: bool

    @property
    def is_parsable(self) -> bool:
        return self.note is not None


def resolve_note_version(visit: Mapping[str, Any]) -> ResolvedNote:
    """Wybierz wersję notatki do pokazania: poprawiona przez lekarza, inaczej oryginał AI."""
    import json

    corrected = visit.get("doctor_note_corrected_json")
    source_json = corrected or visit.get("ai_note_original_json")
    try:
        note = json.loads(source_json) if source_json else None
    except (ValueError, TypeError):
        note = None
    return ResolvedNote(note=note, source_json=source_json, is_corrected=bool(corrected))


def get_visit_with_note(visit_id: int, *, doctor_id: str | None = None) -> tuple[dict[str, Any] | None, ResolvedNote | None]:
    """Pobierz wizytę razem z rozstrzygniętą wersją notatki."""
    visit = get_visit(visit_id, doctor_id=doctor_id)
    if not visit:
        return None, None
    return visit, resolve_note_version(visit)
