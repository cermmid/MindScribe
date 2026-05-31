import json
import os
import stat
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

ROOT_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = ROOT_DIR / "data"
AUDIO_DIR = DATA_DIR / "audio"
DB_PATH = DATA_DIR / "mindscribe.db"
GCP_KEY_PATH = DATA_DIR / ".gcp-key.json"

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


GEMINI_API_KEY = os.getenv("GEMINI_API_KEY") or _from_secrets("GEMINI_API_KEY") or ""
GEMINI_MODEL = os.getenv("GEMINI_MODEL") or _from_secrets("GEMINI_MODEL") or "gemini-2.5-flash"

USE_VERTEX_AI = _as_bool(os.getenv("USE_VERTEX_AI") or _from_secrets("USE_VERTEX_AI") or "false")
GCP_PROJECT_ID = os.getenv("GCP_PROJECT_ID") or _from_secrets("GCP_PROJECT_ID") or ""
GCP_LOCATION = os.getenv("GCP_LOCATION") or _from_secrets("GCP_LOCATION") or "europe-west4"
_GCP_KEY_JSON = (
    os.getenv("GOOGLE_APPLICATION_CREDENTIALS_JSON")
    or _from_secrets("GOOGLE_APPLICATION_CREDENTIALS_JSON")
    or ""
)


def _materialize_gcp_key() -> None:
    """Zapisz JSON klucza service account do pliku i wystaw zmienną GOOGLE_APPLICATION_CREDENTIALS."""
    if not USE_VERTEX_AI or not _GCP_KEY_JSON:
        return
    try:
        json.loads(_GCP_KEY_JSON)
    except Exception:
        return
    GCP_KEY_PATH.write_text(_GCP_KEY_JSON)
    try:
        os.chmod(GCP_KEY_PATH, stat.S_IRUSR | stat.S_IWUSR)
    except Exception:
        pass
    os.environ["GOOGLE_APPLICATION_CREDENTIALS"] = str(GCP_KEY_PATH)


_materialize_gcp_key()

FEW_SHOT_LIMIT = 3
