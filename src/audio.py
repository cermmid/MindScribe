import uuid
from pathlib import Path

from .config import AUDIO_DIR

# Typ MIME zgadywany z rozszerzenia — używany TYLKO gdy przeglądarka nie poda własnego.
_AUDIO_MIME = {
    ".mp3": "audio/mpeg",
    ".wav": "audio/wav",
    ".m4a": "audio/mp4",
    ".mp4": "audio/mp4",
    ".ogg": "audio/ogg",
    ".oga": "audio/ogg",
    ".webm": "audio/webm",
    ".flac": "audio/flac",
    ".aac": "audio/aac",
}

DEFAULT_AUDIO_MIME = "audio/wav"


def save_uploaded_audio(file_bytes: bytes, suffix: str = ".wav") -> Path:
    """Persist uploaded audio under data/audio/ and return its path."""
    if not suffix.startswith("."):
        suffix = "." + suffix
    name = f"{uuid.uuid4().hex}{suffix}"
    path = AUDIO_DIR / name
    path.write_bytes(file_bytes)
    return path


def resolve_audio_mime(suffix: str | None, declared_mime: str | None = None) -> str:
    """Ustal typ MIME nagrania — zgłoszony przez przeglądarkę ma pierwszeństwo.

    To NIE jest kosmetyka. `st.audio_input` zwraca webm, mp4 albo wav zależnie od
    przeglądarki. Wysłanie takich bajtów z etykietą `audio/wav` sprawia, że model
    nie potrafi zdekodować nagrania — a mając wymagane pole na transkrypcję i
    przykłady few-shot przed oczami, zaczyna transkrypcję ZMYŚLAĆ.
    """
    if declared_mime:
        cleaned = declared_mime.split(";")[0].strip().lower()
        # Przeglądarki potrafią zwrócić video/webm dla nagrania z samym audio.
        if cleaned.startswith("audio/") or cleaned.startswith("video/"):
            return cleaned
    if suffix:
        return _AUDIO_MIME.get(suffix.strip().lower(), DEFAULT_AUDIO_MIME)
    return DEFAULT_AUDIO_MIME
