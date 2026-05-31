from functools import lru_cache
from pathlib import Path

from google import genai
from google.genai import types

from .config import (
    GCP_LOCATION,
    GCP_PROJECT_ID,
    GEMINI_API_KEY,
    GEMINI_MODEL,
    USE_VERTEX_AI,
)
from .pricing import estimate_usage_and_cost
from .prompts import SYSTEM_PROMPT, build_user_prompt
from .schemas import PsychiatricNote

_AUDIO_MIME = {
    ".mp3": "audio/mpeg",
    ".wav": "audio/wav",
    ".m4a": "audio/mp4",
    ".ogg": "audio/ogg",
    ".webm": "audio/webm",
    ".flac": "audio/flac",
}


@lru_cache(maxsize=1)
def _client() -> genai.Client:
    if USE_VERTEX_AI:
        if not GCP_PROJECT_ID:
            raise RuntimeError(
                "USE_VERTEX_AI=true, ale brak GCP_PROJECT_ID. "
                "Uzupełnij sekrety (GCP_PROJECT_ID, GCP_LOCATION, GOOGLE_APPLICATION_CREDENTIALS_JSON)."
            )
        return genai.Client(vertexai=True, project=GCP_PROJECT_ID, location=GCP_LOCATION)

    if not GEMINI_API_KEY:
        raise RuntimeError(
            "Brak GEMINI_API_KEY. Skopiuj .env.example do .env i uzupełnij klucz, "
            "albo włącz Vertex AI (USE_VERTEX_AI=true)."
        )
    return genai.Client(api_key=GEMINI_API_KEY)


def _generation_config() -> types.GenerateContentConfig:
    return types.GenerateContentConfig(
        system_instruction=SYSTEM_PROMPT,
        response_mime_type="application/json",
        response_schema=PsychiatricNote,
        temperature=0.2,
    )


def _parse(response) -> PsychiatricNote:
    parsed = getattr(response, "parsed", None)
    if isinstance(parsed, PsychiatricNote):
        return parsed
    return PsychiatricNote.model_validate_json(response.text)


def generate_note_from_audio(
    audio_path: Path,
    few_shot_examples: list[dict],
) -> tuple[PsychiatricNote, str, dict]:
    """Send audio inline (as bytes) and request a structured note.

    Inline payload works for both Vertex AI and the Developer API. Vertex AI
    does not expose the Files API, so this is the portable path.
    """
    client = _client()
    mime = _AUDIO_MIME.get(audio_path.suffix.lower(), "audio/mpeg")
    audio_part = types.Part.from_bytes(
        data=audio_path.read_bytes(),
        mime_type=mime,
    )
    prompt = build_user_prompt(few_shot_examples, transcript=None)

    response = client.models.generate_content(
        model=GEMINI_MODEL,
        contents=[prompt, audio_part],
        config=_generation_config(),
    )
    usage = estimate_usage_and_cost(getattr(response, "usage_metadata", None))
    return _parse(response), prompt, usage


def generate_note_from_text(
    transcript: str,
    few_shot_examples: list[dict],
) -> tuple[PsychiatricNote, str, dict]:
    """Reserved for the future Whisper → text → Gemini pipeline."""
    client = _client()
    prompt = build_user_prompt(few_shot_examples, transcript=transcript)
    response = client.models.generate_content(
        model=GEMINI_MODEL,
        contents=[prompt],
        config=_generation_config(),
    )
    usage = estimate_usage_and_cost(getattr(response, "usage_metadata", None))
    return _parse(response), prompt, usage
