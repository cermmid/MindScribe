from functools import lru_cache
from pathlib import Path

from google import genai
from google.genai import types

from .audio import resolve_audio_mime
from .config import (
    GCP_LOCATION,
    GCP_PROJECT_ID,
    GEMINI_API_KEY,
    GEMINI_MODEL,
    GEMINI_THINKING_BUDGET,
    USE_VERTEX_AI,
    VERIFY_ICD10,
    _gcp_credentials_info,
    thinking_budget_for,
)
from .pricing import estimate_usage_and_cost
from .prompts import DEFAULT_LOOKUP_SYSTEMS, SYSTEM_PROMPT, build_user_prompt
from .schemas import PsychiatricNoteDraft


def _vertex_credentials():
    """Zbuduj poświadczenia service account z secrets — bez polegania na ADC/metadata server."""
    try:
        info = _gcp_credentials_info()
    except Exception as e:
        raise RuntimeError(
            "Nie udało się sparsować poświadczeń service account. "
            "Wklej cały plik JSON jako GOOGLE_APPLICATION_CREDENTIALS_JSON "
            "w potrójnych cudzysłowach, albo użyj sekcji [gcp_service_account] "
            f"z polami pole-po-polu. Szczegóły: {e}"
        ) from e
    if info is None:
        return None
    from google.oauth2 import service_account

    return service_account.Credentials.from_service_account_info(
        info, scopes=["https://www.googleapis.com/auth/cloud-platform"]
    )


@lru_cache(maxsize=1)
def _client() -> genai.Client:
    if USE_VERTEX_AI:
        if not GCP_PROJECT_ID:
            raise RuntimeError(
                "USE_VERTEX_AI=true, ale brak GCP_PROJECT_ID. "
                "Uzupełnij sekrety (GCP_PROJECT_ID, GCP_LOCATION, GOOGLE_APPLICATION_CREDENTIALS_JSON)."
            )
        creds = _vertex_credentials()
        if creds is None:
            raise RuntimeError(
                "USE_VERTEX_AI=true, ale brak poświadczeń service account w sekretach. "
                "Wklej cały plik JSON jako GOOGLE_APPLICATION_CREDENTIALS_JSON "
                "(między potrójnymi cudzysłowami), albo użyj sekcji [gcp_service_account]."
            )
        return genai.Client(
            vertexai=True,
            project=GCP_PROJECT_ID,
            location=GCP_LOCATION,
            credentials=creds,
        )

    if not GEMINI_API_KEY:
        raise RuntimeError(
            "Brak GEMINI_API_KEY. Skopiuj .env.example do .env i uzupełnij klucz, "
            "albo włącz Vertex AI (USE_VERTEX_AI=true)."
        )
    return genai.Client(api_key=GEMINI_API_KEY)


def _lookup_systems() -> list[str]:
    """Klasyfikacje, dla których sami ustalimy kod — model może je zostawić puste."""
    return [*DEFAULT_LOOKUP_SYSTEMS, "ICD-10"] if VERIFY_ICD10 else list(DEFAULT_LOOKUP_SYSTEMS)


def _generation_config() -> types.GenerateContentConfig:
    return types.GenerateContentConfig(
        system_instruction=SYSTEM_PROMPT,
        response_mime_type="application/json",
        response_schema=PsychiatricNoteDraft,
        temperature=0.2,
        thinking_config=types.ThinkingConfig(
            thinking_budget=thinking_budget_for(GEMINI_MODEL, GEMINI_THINKING_BUDGET)
        ),
    )


def _usage_of(response) -> dict:
    """Zużycie i koszt, wyceniane po modelu, który FAKTYCZNIE odpowiedział.

    `model_version` bierzemy przed `GEMINI_MODEL`, bo konfiguracja może wskazywać
    alias (np. `…-latest`), a rachunek wystawia się za wydanie, które policzyło.
    """
    return estimate_usage_and_cost(
        getattr(response, "usage_metadata", None),
        model=getattr(response, "model_version", None) or GEMINI_MODEL,
    )


def _parse(response) -> PsychiatricNoteDraft:
    parsed = getattr(response, "parsed", None)
    if isinstance(parsed, PsychiatricNoteDraft):
        return parsed
    return PsychiatricNoteDraft.model_validate_json(response.text)


def generate_note_from_audio(
    audio_path: Path,
    few_shot_examples: list[dict],
    *,
    mime_type: str | None = None,
    klasyfikacje: list[str] | str = "ICD-10",
) -> tuple[PsychiatricNoteDraft, str, dict]:
    """Send audio inline (as bytes) and request a structured note.

    Inline payload works for both Vertex AI and the Developer API. Vertex AI
    does not expose the Files API, so this is the portable path.
    """
    client = _client()
    mime = resolve_audio_mime(audio_path.suffix, mime_type)
    audio_part = types.Part.from_bytes(
        data=audio_path.read_bytes(),
        mime_type=mime,
    )
    prompt = build_user_prompt(
        few_shot_examples,
        transcript=None,
        klasyfikacje=klasyfikacje,
        lookup_systems=_lookup_systems(),
    )

    response = client.models.generate_content(
        model=GEMINI_MODEL,
        contents=[prompt, audio_part],
        config=_generation_config(),
    )
    usage = _usage_of(response)
    return _parse(response), prompt, usage


def generate_note_from_text(
    transcript: str,
    few_shot_examples: list[dict],
    *,
    klasyfikacje: list[str] | str = "ICD-10",
) -> tuple[PsychiatricNoteDraft, str, dict]:
    """Reserved for the future Whisper → text → Gemini pipeline."""
    client = _client()
    prompt = build_user_prompt(
        few_shot_examples,
        transcript=transcript,
        klasyfikacje=klasyfikacje,
        lookup_systems=_lookup_systems(),
    )
    response = client.models.generate_content(
        model=GEMINI_MODEL,
        contents=[prompt],
        config=_generation_config(),
    )
    usage = _usage_of(response)
    return _parse(response), prompt, usage
