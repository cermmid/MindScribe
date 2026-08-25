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


# --- Wyszukiwanie i weryfikacja ------------------------------------------------


def search(term: str, *, icd11: bool = True, language: str = "pl") -> list[IcdMatch]:
    """Znajdź rozpoznania pasujące do frazy. Pusta lista, gdy nic nie pasuje.

    Wyszukiwanie działa tylko dla ICD-11 — API WHO nie udostępnia go dla ICD-10,
    gdzie potrafimy jedynie sprawdzić konkretny kod (patrz `lookup_code`).
    """
    if not term.strip() or not icd11:
        return []

    for lang in _language_order(language):
        payload = _get(
            f"{ICD11_LINEARIZATION}/search",
            language=lang,
            params={"q": term, "flatResults": "true", "useFlexisearch": "false"},
        )
        entities = (payload or {}).get("destinationEntities") or []
        matches = [
            IcdMatch(code=code, title=_title_of(entity))
            for entity in entities
            if (code := _clean(entity.get("theCode")))
        ]
        if matches:
            return matches
    return []


def lookup_code(code: str, *, icd11: bool = True, language: str = "pl") -> IcdMatch | None:
    """Oficjalny tytuł dla podanego kodu. `None`, gdy kod nie istnieje w klasyfikacji."""
    code = (code or "").strip()
    if not code:
        return None

    if icd11:
        # Szukanie po samym kodzie jest tańsze niż codeinfo + pobranie encji,
        # a potwierdzenie wymaga dokładnego dopasowania `theCode`.
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
