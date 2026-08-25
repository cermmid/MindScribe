import json
import os
import re
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

ROOT_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = ROOT_DIR / "data"
AUDIO_DIR = DATA_DIR / "audio"
DB_PATH = DATA_DIR / "mindscribe.db"

AUDIO_DIR.mkdir(parents=True, exist_ok=True)


def _from_secrets(key: str):
    """Fallback to Streamlit secrets when env var is not set (used on Streamlit Cloud)."""
    try:
        import streamlit as st

        return st.secrets.get(key)
    except Exception:
        return None


def _as_bool(v) -> bool:
    return str(v).strip().lower() in {"1", "true", "yes", "on"}


def _database_url() -> str:
    """Adres bazy. Bez konfiguracji — lokalny SQLite, żeby dev i testy działały bez serwera.

    Neon podaje adres zaczynający się od `postgresql://`; SQLAlchemy potrzebuje jawnego
    sterownika, więc dopisujemy `+psycopg`. Dzięki temu można wkleić string prosto
    z panelu Neona bez ręcznych poprawek.
    """
    url = (os.getenv("DATABASE_URL") or _from_secrets("DATABASE_URL") or "").strip()
    if not url:
        return f"sqlite:///{DB_PATH}"
    if url.startswith("postgresql://"):
        return url.replace("postgresql://", "postgresql+psycopg://", 1)
    if url.startswith("postgres://"):  # starszy wariant, spotykany u niektórych dostawców
        return url.replace("postgres://", "postgresql+psycopg://", 1)
    return url


DATABASE_URL = _database_url()

GEMINI_API_KEY = os.getenv("GEMINI_API_KEY") or _from_secrets("GEMINI_API_KEY") or ""
GEMINI_MODEL = os.getenv("GEMINI_MODEL") or _from_secrets("GEMINI_MODEL") or "gemini-2.5-flash"

# Poświadczenia do API WHO (icd.who.int/icdapi) — weryfikacja kodów rozpoznań.
# Bez nich aplikacja działa, ale kody zostają oznaczone jako niezweryfikowane.
ICD_CLIENT_ID = os.getenv("ICD_CLIENT_ID") or _from_secrets("ICD_CLIENT_ID") or ""
ICD_CLIENT_SECRET = os.getenv("ICD_CLIENT_SECRET") or _from_secrets("ICD_CLIENT_SECRET") or ""

USE_VERTEX_AI = _as_bool(os.getenv("USE_VERTEX_AI") or _from_secrets("USE_VERTEX_AI") or "false")
GCP_PROJECT_ID = os.getenv("GCP_PROJECT_ID") or _from_secrets("GCP_PROJECT_ID") or ""
GCP_LOCATION = os.getenv("GCP_LOCATION") or _from_secrets("GCP_LOCATION") or "europe-west4"


def _tolerant_json_loads(raw: str) -> dict:
    """json.loads, ale z auto-naprawą literalnych nowych linii w 'private_key'.

    Najczęstszy problem przy wklejaniu klucza service account do TOML:
    wartość private_key zawiera literalne \\n, które po wklejeniu w '''...'''
    stają się prawdziwymi nowymi liniami — JSON tego nie znosi w stringu.
    """
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        pass

    m = re.search(r'"private_key"\s*:\s*"', raw)
    if not m:
        return json.loads(raw)  # rzuci oryginalny błąd

    start = m.end()
    i = start
    while i < len(raw):
        if raw[i] == "\\":
            i += 2
            continue
        if raw[i] == '"':
            break
        i += 1
    if i >= len(raw):
        return json.loads(raw)

    value = raw[start:i]
    fixed_value = value.replace("\r\n", "\\n").replace("\n", "\\n").replace("\r", "\\n")
    return json.loads(raw[:start] + fixed_value + raw[i:])


def _gcp_credentials_info() -> dict | None:
    """Zbierz dict z poświadczeniami service account z dowolnego z obsługiwanych źródeł.

    Kolejność:
      1. GOOGLE_APPLICATION_CREDENTIALS_JSON (string z całym JSON, env lub secrets) — tolerancyjny parser.
      2. Sekcja [gcp_service_account] w secrets (zalecany styl Streamlit dla GCP).
    """
    raw = (
        os.getenv("GOOGLE_APPLICATION_CREDENTIALS_JSON")
        or _from_secrets("GOOGLE_APPLICATION_CREDENTIALS_JSON")
        or ""
    ).strip()
    if raw:
        return _tolerant_json_loads(raw)

    section = _from_secrets("gcp_service_account")
    if section:
        return dict(section)

    return None


FEW_SHOT_LIMIT = 3
