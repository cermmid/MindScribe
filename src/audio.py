import io
import uuid
import wave
from array import array
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


# Nagranie krótsze niż to jest w praktyce puste niezależnie od kontenera.
_MIN_PLAUSIBLE_BYTES = 2_000

# Próg amplitudy (0.0-1.0) poniżej którego uznajemy nagranie za ciszę. Zwykły szum tła
# mikrofonu daje wyraźnie więcej; przeglądarka nagrywająca z martwego urządzenia daje zera.
_SILENCE_PEAK_RATIO = 0.005


def _wav_peak_ratio(data: bytes) -> float | None:
    """Największa amplituda w nagraniu WAV, jako ułamek maksimum. None gdy nie da się odczytać."""
    try:
        with wave.open(io.BytesIO(data)) as w:
            width = w.getsampwidth()
            # Czytamy najwyżej ~30 s — do wykrycia ciszy w zupełności wystarczy.
            frames = w.readframes(min(w.getnframes(), w.getframerate() * 30 or 1))
    except (wave.Error, EOFError, ValueError):
        return None
    if not frames:
        return 0.0

    if width == 2:
        samples = array("h")
        samples.frombytes(frames[: len(frames) - (len(frames) % 2)])
        peak = max((abs(s) for s in samples), default=0)
        return peak / 32768.0
    if width == 1:
        # 8-bit WAV jest bez znaku, cisza to 128.
        peak = max((abs(b - 128) for b in frames), default=0)
        return peak / 128.0
    return None  # nietypowa szerokość próbki — nie zgadujemy


def looks_silent(data: bytes, mime: str | None = None) -> bool:
    """Czy nagranie jest puste albo zawiera samą ciszę.

    Chroni przed najczęstszym scenariuszem: przeglądarka „nagrywa", ale nie dostaje
    dźwięku z mikrofonu (złe urządzenie wejściowe albo blokada uprawnień w systemie).
    Bez tej kontroli wysyłamy do modelu ciszę i płacimy za notatkę bez treści.

    Dla kontenerów, których nie umiemy zdekodować bez dodatkowych bibliotek (webm, mp4),
    sprawdzamy wyłącznie rozmiar — lepiej przepuścić wątpliwe nagranie niż blokować dobre.
    """
    if not data or len(data) < _MIN_PLAUSIBLE_BYTES:
        return True

    is_wav = (mime or "").lower().endswith("wav") or data[:4] == b"RIFF"
    if is_wav:
        peak = _wav_peak_ratio(data)
        if peak is not None:
            return peak < _SILENCE_PEAK_RATIO
    return False


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
