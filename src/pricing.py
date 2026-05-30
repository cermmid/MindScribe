"""Gemini 2.5 Flash pricing.

Stawki USD per 1M tokens — sprawdź i zaktualizuj na https://ai.google.dev/gemini-api/docs/pricing.
Domyślne wartości to publiczna cena Gemini 2.5 Flash (paid tier) z 2025/2026.
"""

PRICING_USD_PER_1M: dict[str, float] = {
    "text_input": 0.30,
    "audio_input": 1.00,
    "output": 2.50,
}


def _modality_breakdown(prompt_details) -> dict[str, int]:
    """Convert SDK's prompt_tokens_details (list of ModalityTokenCount) -> {modality: count}."""
    out: dict[str, int] = {}
    if not prompt_details:
        return out
    for item in prompt_details:
        modality = getattr(item, "modality", None) or item.get("modality") if isinstance(item, dict) else None
        count = getattr(item, "token_count", None) or (item.get("token_count") if isinstance(item, dict) else 0)
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
            "total_tokens": 0,
            "prompt_audio_tokens": 0,
            "prompt_text_tokens": 0,
            "estimated_cost_usd": 0.0,
        }

    prompt_total = int(getattr(usage_metadata, "prompt_token_count", 0) or 0)
    output_total = int(getattr(usage_metadata, "candidates_token_count", 0) or 0)
    grand_total = int(getattr(usage_metadata, "total_token_count", 0) or (prompt_total + output_total))

    details = _modality_breakdown(getattr(usage_metadata, "prompt_tokens_details", None))
    audio_tokens = details.get("audio", 0)
    text_tokens = details.get("text", 0) + details.get("image", 0) + details.get("video", 0)

    if audio_tokens == 0 and text_tokens == 0:
        audio_tokens = prompt_total
        text_tokens = 0

    cost = (
        audio_tokens * PRICING_USD_PER_1M["audio_input"]
        + text_tokens * PRICING_USD_PER_1M["text_input"]
        + output_total * PRICING_USD_PER_1M["output"]
    ) / 1_000_000

    return {
        "prompt_tokens": prompt_total,
        "output_tokens": output_total,
        "total_tokens": grand_total,
        "prompt_audio_tokens": audio_tokens,
        "prompt_text_tokens": text_tokens,
        "estimated_cost_usd": round(cost, 6),
    }
