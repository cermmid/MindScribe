from functools import lru_cache
from pathlib import Path

from google import genai
from google.genai import types

from .config import GEMINI_API_KEY, GEMINI_MODEL
from .pricing import estimate_usage_and_cost
from .prompts import SYSTEM_PROMPT, build_user_prompt
from .schemas import PsychiatricNote


@lru_cache(maxsize=1)
def _client() -> genai.Client:
    if not GEMINI_API_KEY:
        raise RuntimeError(
            "Brak GEMINI_API_KEY w .env. Skopiuj .env.example do .env i uzupełnij klucz."
        )
    # Produkcyjnie: genai.Client(vertexai=True, project=..., location=...) — patrz README.
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
    """Upload audio to Gemini Files API and request a structured note.

    Returns (note, full_prompt_for_debug, usage_dict).
    """
    client = _client()
    uploaded = client.files.upload(file=str(audio_path))
    prompt = build_user_prompt(few_shot_examples, transcript=None)

    response = client.models.generate_content(
        model=GEMINI_MODEL,
        contents=[prompt, uploaded],
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
