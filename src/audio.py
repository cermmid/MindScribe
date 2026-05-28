import uuid
from pathlib import Path

from .config import AUDIO_DIR


def save_uploaded_audio(file_bytes: bytes, suffix: str = ".wav") -> Path:
    """Persist uploaded audio under data/audio/ and return its path."""
    if not suffix.startswith("."):
        suffix = "." + suffix
    name = f"{uuid.uuid4().hex}{suffix}"
    path = AUDIO_DIR / name
    path.write_bytes(file_bytes)
    return path
