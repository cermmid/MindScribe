import os
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

ROOT_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = ROOT_DIR / "data"
AUDIO_DIR = DATA_DIR / "audio"
DB_PATH = DATA_DIR / "mindscribe.db"

AUDIO_DIR.mkdir(parents=True, exist_ok=True)


def _from_secrets(key: str) -> str | None:
    """Fallback to Streamlit secrets when env var is not set (used on Streamlit Cloud)."""
    try:
        import streamlit as st

        return st.secrets.get(key)
    except Exception:
        return None


GEMINI_API_KEY = os.getenv("GEMINI_API_KEY") or _from_secrets("GEMINI_API_KEY") or ""
GEMINI_MODEL = os.getenv("GEMINI_MODEL") or _from_secrets("GEMINI_MODEL") or "gemini-2.5-flash"

FEW_SHOT_LIMIT = 3
