"""Weryfikacja rozpoznań w oficjalnym API WHO (icd.who.int/icdapi).

Po co to istnieje: model językowy potrafi podać **prawdziwie wyglądający kod z błędnym
znaczeniem** — np. QE80 („ofiara przestępstwa") opisane jako zaburzenia snu. Walidacja
formatu tego nie wykryje, bo kod naprawdę istnieje. Jedyne rzetelne rozwiązanie to
sprawdzenie kodu w źródle autorytatywnym i **zastąpienie opisu oficjalnym tytułem WHO**,
żeby para kod-opis nigdy się nie rozjechała.

Moduł jest celowo odporny na awarie: brak poświadczeń, brak sieci albo błąd API nigdy
nie wysadza generowania notatki — rozpoznania zostają wtedy oznaczone jako
niezweryfikowane, a lekarz widzi wyraźne ostrzeżenie.
"""

from __future__ import annotations

import re
import time
from dataclasses import dataclass

import requests

from .config import ICD_CLIENT_ID, ICD_CLIENT_SECRET

TOKEN_URL = "https://icdaccessmanagement.who.int/connect/token"
BASE_URL = "https://id.who.int/icd"

# Wydania używane do odpytywania. "release/11/mms" bez numeru wskazuje najnowsze wydanie.
ICD11_LINEARIZATION = "release/11/mms"
ICD10_RELEASE = "release/10/2019"

_TIMEOUT = 8
_TAG_RE = re.compile(r"<[^>]+>")
_RELEASE_RE = re.compile(r"/release/11/(\d{4}-\d{2})\b")
_ENTITY_ID_RE = re.compile(r"/(\d+)/?$")

# Ile encji bez kodu próbujemy jeszcze rozwiązać przez linearyzację. Każda to osobne
# zapytanie, więc trzymamy krótko — pierwsze trafienie i tak jest tym, którego używamy.
_RESOLVE_LIMIT = 5


@dataclass(frozen=True)
class IcdMatch:
    """Rozpoznanie potwierdzone w API WHO."""

    code: str
    title: str


class IcdUnavailable(RuntimeError):
    """API WHO jest nieskonfigurowane albo nieosiągalne."""


def is_configured() -> bool:
    return bool(ICD_CLIENT_ID and ICD_CLIENT_SECRET)


# --- Token --------------------------------------------------------------------

_token_cache: dict[str, float | str] = {"value": "", "expires_at": 0.0}


def _access_token() -> str:
    """Token OAuth2, cache'owany do wygaśnięcia (WHO wydaje na ok. godzinę)."""
    now = time.time()
    if _token_cache["value"] and float(_token_cache["expires_at"]) > now + 60:
        return str(_token_cache["value"])

    if not is_configured():
        raise IcdUnavailable("Brak ICD_CLIENT_ID / ICD_CLIENT_SECRET w konfiguracji.")

    try:
        response = requests.post(
            TOKEN_URL,
            data={
                "client_id": ICD_CLIENT_ID,
                "client_secret": ICD_CLIENT_SECRET,
                "scope": "icdapi_access",
                "grant_type": "client_credentials",
            },
            timeout=_TIMEOUT,
        )
        response.raise_for_status()
        payload = response.json()
    except (requests.RequestException, ValueError) as exc:
        raise IcdUnavailable(f"Nie udało się pobrać tokenu WHO: {exc}") from exc

    token = payload.get("access_token")
    if not token:
        raise IcdUnavailable("Odpowiedź WHO nie zawiera access_token.")

    _token_cache["value"] = token
    _token_cache["expires_at"] = now + float(payload.get("expires_in", 3600))
    return token


def _headers(language: str) -> dict[str, str]:
    return {
        "Authorization": f"Bearer {_access_token()}",
        "Accept": "application/json",
        "Accept-Language": language,
        "API-Version": "v2",
    }


def _get(path: str, *, language: str, params: dict | None = None) -> dict | None:
    try:
        response = requests.get(
            f"{BASE_URL}/{path.lstrip('/')}",
            headers=_headers(language),
            params=params,
            timeout=_TIMEOUT,
        )
    except requests.RequestException as exc:
        raise IcdUnavailable(f"Błąd połączenia z WHO: {exc}") from exc

    if response.status_code == 404:
        return None
    if not response.ok:
        raise IcdUnavailable(f"WHO odpowiedziało {response.status_code}.")
    try:
        return response.json()
    except ValueError as exc:
        raise IcdUnavailable(f"Niepoprawna odpowiedź WHO: {exc}") from exc


# --- Parsowanie ----------------------------------------------------------------


def _clean(text: str | None) -> str:
    """Tytuły z wyszukiwarki WHO zawierają znaczniki podświetlenia (<em class='found'>)."""
    if not text:
        return ""
    return _TAG_RE.sub("", text).replace("&quot;", '"').replace("&amp;", "&").strip()


def _title_of(entity: dict) -> str:
    title = entity.get("title")
    if isinstance(title, dict):
        title = title.get("@value")
    return _clean(title)


def _api_error(payload: dict | None) -> str:
    """WHO potrafi odpowiedzieć HTTP 200 z `error: true` w treści — to nie jest sukces."""
    if not payload or not payload.get("error"):
        return ""
    return str(payload.get("errorMessage") or "nieokreślony błąd wyszukiwarki WHO")


# --- Wydanie ICD-11 ------------------------------------------------------------

_release_cache: dict[str, str] = {"id": ""}


def _release_id() -> str:
    """Numer najnowszego wydania ICD-11 (np. „2025-01"), pusty gdy się nie udało ustalić.

    Adres bez numeru wydania (`release/11/mms`) działa dla części zasobów, ale
    dokumentacja WHO opisuje wyszukiwarkę pod adresem z numerem. Ustalamy go raz
    i próbujemy obu wariantów — koszt to jedno zapytanie na uruchomienie procesu.
    """
    if _release_cache["id"]:
        return _release_cache["id"]
    try:
        payload = _get(ICD11_LINEARIZATION, language="en") or {}
    except IcdUnavailable:
        return ""
    release = str(payload.get("releaseId") or "").strip()
    if not release:
        uri = str(payload.get("@id") or payload.get("latestRelease") or "")
        match = _RELEASE_RE.search(uri)
        release = match.group(1) if match else ""
    _release_cache["id"] = release
    return release


def _mms_prefix() -> str:
    release = _release_id()
    return f"release/11/{release}/mms" if release else ICD11_LINEARIZATION


def _icd11_search_paths() -> list[str]:
    """Adresy wyszukiwarki od najbardziej do najmniej prawdopodobnego."""
    paths = [f"{_mms_prefix()}/search"]
    if paths[0] != f"{ICD11_LINEARIZATION}/search":
        paths.append(f"{ICD11_LINEARIZATION}/search")
    return paths


# --- Wyszukiwanie i weryfikacja ------------------------------------------------


def _linearization_entity(uri: str, *, language: str) -> IcdMatch | None:
    """Kod i tytuł encji z linearyzacji MMS, po jej identyfikatorze albo pełnym URI."""
    found = _ENTITY_ID_RE.search(uri or "")
    if not found:
        return None
    try:
        payload = _get(f"{_mms_prefix()}/{found.group(1)}", language=language)
    except IcdUnavailable:
        return None
    code = _clean((payload or {}).get("code"))
    title = _title_of(payload or {})
    return IcdMatch(code=code, title=title) if code and title else None


def _matches_from(entities: list[dict], *, language: str) -> list[IcdMatch]:
    """Zamień wynik wyszukiwarki na trafienia z kodem.

    Encje z wyszukiwarki fundacji (i część wyników linearyzacji: rozdziały, bloki)
    **nie mają `theCode`** — kod nadaje dopiero linearyzacja. Odrzucanie takich wpisów
    od razu było przyczyną pustych wyników: zapytanie się udawało, a lista wychodziła
    pusta. Zamiast tego dopytujemy o kod po identyfikatorze encji.
    """
    matches = [
        IcdMatch(code=code, title=_title_of(entity))
        for entity in entities
        if (code := _clean(entity.get("theCode")))
    ]
    if matches:
        return matches

    resolved: list[IcdMatch] = []
    for entity in entities[:_RESOLVE_LIMIT]:
        uri = str(entity.get("id") or entity.get("@id") or entity.get("stemId") or "")
        if hit := _linearization_entity(uri, language=language):
            resolved.append(hit)
    return resolved


def _note(trace: list[dict] | None, **fields: object) -> None:
    if trace is not None:
        trace.append(dict(fields))


def search(
    term: str,
    *,
    icd11: bool = True,
    language: str = "pl",
    trace: list[dict] | None = None,
) -> list[IcdMatch]:
    """Znajdź rozpoznania pasujące do frazy. Pusta lista, gdy nic nie pasuje.

    Wyszukiwanie działa tylko dla ICD-11 — API WHO nie udostępnia go dla ICD-10,
    gdzie potrafimy jedynie sprawdzić konkretny kod (patrz `lookup_code`).

    Przechodzimy kolejno przez warianty zapytania (adres z numerem wydania i bez,
    wyszukiwanie ścisłe i rozmyte) i zwracamy pierwszy, który cokolwiek znalazł.
    `trace`, jeśli podane, dostaje zapis każdej próby — to nim posługuje się
    `scripts/test_icd.py`, żeby pokazać, co dokładnie odpowiedziało WHO.
    """
    if not term.strip() or not icd11:
        return []

    # Awaria tokenu to realna niedostępność rejestru, a nie „brak trafień" —
    # ma polecieć wyżej, zanim zaczniemy przebierać w wariantach zapytania.
    _access_token()

    last_error: IcdUnavailable | None = None
    answered = False

    for lang in _language_order(language):
        for path in _icd11_search_paths():
            for flexi in ("false", "true"):
                params = {"q": term, "flatResults": "true", "useFlexisearch": flexi}
                try:
                    payload = _get(path, language=lang, params=params)
                except IcdUnavailable as exc:
                    last_error = exc
                    _note(trace, path=path, language=lang, flexisearch=flexi, error=str(exc))
                    continue

                answered = True
                entities = (payload or {}).get("destinationEntities") or []
                matches = _matches_from(entities, language=lang)
                _note(
                    trace,
                    path=path,
                    language=lang,
                    flexisearch=flexi,
                    entities=len(entities),
                    matches=len(matches),
                    error=_api_error(payload),
                )
                if matches:
                    return matches

    # Żaden wariant nie dostał poprawnej odpowiedzi — to awaria, nie brak wyniku.
    # Rozróżnienie jest istotne: lekarz ma zobaczyć „rejestr niedostępny",
    # a nie „takiego rozpoznania nie ma".
    if not answered and last_error is not None:
        raise last_error
    return []


def lookup_code(code: str, *, icd11: bool = True, language: str = "pl") -> IcdMatch | None:
    """Oficjalny tytuł dla podanego kodu. `None`, gdy kod nie istnieje w klasyfikacji."""
    code = (code or "").strip()
    if not code:
        return None

    if icd11:
        # `codeinfo` to zapytanie wprost o kod — pewniejsze niż szukanie po jego
        # napisie, bo wyszukiwarka może zwrócić coś podobnego zamiast dokładnego wpisu.
        for lang in _language_order(language):
            try:
                info = _get(f"{_mms_prefix()}/codeinfo/{code}", language=lang)
            except IcdUnavailable:
                info = None
            if info:
                hit = _linearization_entity(str(info.get("stemId") or ""), language=lang)
                if hit and hit.code.upper() == code.upper():
                    return hit
        for candidate in search(code, icd11=True, language=language):
            if candidate.code.upper() == code.upper():
                return candidate
        return None

    for lang in _language_order(language):
        payload = _get(f"{ICD10_RELEASE}/{code}", language=lang)
        if payload:
            title = _title_of(payload)
            if title:
                return IcdMatch(code=code, title=title)
    return None


def _language_order(preferred: str) -> list[str]:
    """Preferowany język, z angielskim jako zapasowym — nie każde wydanie ma tłumaczenia."""
    preferred = (preferred or "en").split("-")[0].lower()
    return [preferred] if preferred == "en" else [preferred, "en"]
