"""Gemini 2.5 Flash pricing.

Stawki USD per 1M tokens — sprawdź i zaktualizuj na https://ai.google.dev/gemini-api/docs/pricing.
Domyślne wartości to publiczna cena Gemini 2.5 Flash (paid tier) z 2025/2026.
"""

PRICING_USD_PER_1M: dict[str, float] = {
    "text_input": 0.30,
    "audio_input": 1.00,
    "output": 2.50,
}


def usd_to_pln(usd: float, rate: float) -> float:
    return float(usd) * float(rate)


# Gemini tokenizuje audio ze stałą częstotliwością — stąd da się z tokenów odtworzyć
# przybliżoną długość nagrania.
AUDIO_TOKENS_PER_SECOND = 32

# Poniżej tego progu szacunek jest bezwartościowy: narzut tekstowy promptu (system
# prompt, schemat, few-shot) to rząd 1-3 tys. tokenów, więc przy krótkim nagraniu
# dominuje wynik. Przy realnej wizycie stanowi kilka procent i jest do przyjęcia.
_MIN_TRUSTWORTHY_SECONDS = 300


def estimate_audio_seconds(
    audio_tokens: int | None,
    *,
    modality_known: bool = True,
    tokens_per_second: int = AUDIO_TOKENS_PER_SECOND,
) -> float | None:
    """Przybliżona długość nagrania z liczby tokenów audio.

    Zwraca `None`, gdy szacunek byłby niewiarygodny — brak danych, brak rozbicia
    modalności (wtedy liczba zawiera też tekst promptu) albo wynik poniżej progu.
    Wołający ma pokazać „—", a nie zmyśloną wartość.
    """
    if not audio_tokens or audio_tokens <= 0 or not modality_known:
        return None
    seconds = float(audio_tokens) / float(tokens_per_second)
    if seconds < _MIN_TRUSTWORTHY_SECONDS:
        return None
    return round(seconds, 1)


def format_duration(seconds: float | None) -> str:
    """Sekundy → „1 h 23 min" / „14 min" / „—"."""
    if not seconds or seconds <= 0:
        return "—"
    total_minutes = int(round(seconds / 60))
    hours, minutes = divmod(total_minutes, 60)
    if hours:
        return f"{hours} h {minutes} min"
    return f"{minutes} min"


def _modality_breakdown(prompt_details) -> dict[str, int]:
    """Convert SDK's prompt_tokens_details (list of ModalityTokenCount) -> {modality: count}."""
    out: dict[str, int] = {}
    if not prompt_details:
        return out
    for item in prompt_details:
        if isinstance(item, dict):
            modality = item.get("modality")
            count = item.get("token_count")
        else:
            modality = getattr(item, "modality", None)
            count = getattr(item, "token_count", None)
        if modality is None:
            continue
        key = str(modality).lower().split(".")[-1]
        out[key] = out.get(key, 0) + int(count or 0)
    return out


def estimate_usage_and_cost(usage_metadata) -> dict:
    """Return a flat dict with token counts and USD cost estimate.

    Falls back to charging the full prompt at the audio rate when the SDK
    doesn't break prompt tokens down by modality — that's the conservative
    estimate for our pipeline (audio input dominates).
    """
    if usage_metadata is None:
        return {
            "prompt_tokens": 0,
            "output_tokens": 0,
            "thoughts_tokens": 0,
            "total_tokens": 0,
            "prompt_audio_tokens": 0,
            "prompt_text_tokens": 0,
            "modality_known": False,
            "estimated_cost_usd": 0.0,
        }

    prompt_total = int(getattr(usage_metadata, "prompt_token_count", 0) or 0)
    output_total = int(getattr(usage_metadata, "candidates_token_count", 0) or 0)
    # Tokeny "myślenia" (Gemini 2.5). Bywają raportowane osobno i też są płatne jak output.
    thoughts_total = int(getattr(usage_metadata, "thoughts_token_count", 0) or 0)
    grand_total = int(
        getattr(usage_metadata, "total_token_count", 0)
        or (prompt_total + output_total + thoughts_total)
    )

    details = _modality_breakdown(getattr(usage_metadata, "prompt_tokens_details", None))
    audio_tokens = details.get("audio", 0)
    text_tokens = details.get("text", 0) + details.get("image", 0) + details.get("video", 0)

    modality_known = bool(audio_tokens or text_tokens)
    if not modality_known:
        audio_tokens = prompt_total
        text_tokens = 0

    billable_output = output_total + thoughts_total
    cost = (
        audio_tokens * PRICING_USD_PER_1M["audio_input"]
        + text_tokens * PRICING_USD_PER_1M["text_input"]
        + billable_output * PRICING_USD_PER_1M["output"]
    ) / 1_000_000

    return {
        "prompt_tokens": prompt_total,
        "output_tokens": output_total,
        "thoughts_tokens": thoughts_total,
        "total_tokens": grand_total,
        "prompt_audio_tokens": audio_tokens,
        "prompt_text_tokens": text_tokens,
        "modality_known": modality_known,
        "estimated_cost_usd": round(cost, 6),
    }
