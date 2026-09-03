"""Testy wyceny zużycia Gemini.

Punkt wyjścia: stawki były zaszyte dla Gemini 2.5 Flash bez wymiaru modelu, więc
przełączenie na Pro dałoby koszt zaniżony ponad dwukrotnie — i to bez żadnego
sygnału, bo nic by nie rzuciło wyjątku. Te testy pilnują, żeby każda przyszła
pomyłka w cenniku była głośna, a nie cicha.
"""

from types import SimpleNamespace

import pytest

from src import pricing
from src.pricing import (
    MODEL_PRICING_USD_PER_1M,
    estimate_usage_and_cost,
    is_priced,
    normalize_model_id,
    resolve_rates,
)

# Klucze, na których stoją `db.insert_visit` i panel właściciela. Ich usunięcie albo
# przemianowanie po cichu wyzeruje kolumny w bazie, więc traktujemy je jak kontrakt.
LEGACY_KEYS = {
    "prompt_tokens",
    "output_tokens",
    "thoughts_tokens",
    "total_tokens",
    "prompt_audio_tokens",
    "prompt_text_tokens",
    "modality_known",
    "estimated_cost_usd",
}


def usage(
    *,
    prompt: int = 100_000,
    output: int = 2_500,
    thoughts: int = 0,
    audio: int | None = 86_400,
    text: int | None = 13_600,
):
    """Fałszywe `usage_metadata` w kształcie, w jakim zwraca je SDK."""
    details = None
    if audio is not None or text is not None:
        details = [
            SimpleNamespace(modality=name, token_count=count)
            for name, count in (("AUDIO", audio), ("TEXT", text))
            if count is not None
        ]
    return SimpleNamespace(
        prompt_token_count=prompt,
        candidates_token_count=output,
        thoughts_token_count=thoughts,
        total_token_count=prompt + output + thoughts,
        prompt_tokens_details=details,
    )


class TestKnownModels:
    def test_flash_golden_number(self):
        """Dowód, że refaktor nie zmienił kosztu istniejących wierszy."""
        result = estimate_usage_and_cost(usage(), model="gemini-2.5-flash")
        expected = (86_400 * 1.00 + 13_600 * 0.30 + 2_500 * 2.50) / 1_000_000
        assert result["estimated_cost_usd"] == pytest.approx(round(expected, 6))
        assert result["pricing_tier"] == "standard"
        assert result["pricing_known"] is True

    def test_pro_costs_more_than_flash(self):
        flash = estimate_usage_and_cost(usage(), model="gemini-2.5-flash")
        pro = estimate_usage_and_cost(usage(), model="gemini-2.5-pro")
        expected = (86_400 * 1.25 + 13_600 * 1.25 + 2_500 * 10.00) / 1_000_000
        assert pro["estimated_cost_usd"] == pytest.approx(round(expected, 6))
        assert pro["estimated_cost_usd"] > flash["estimated_cost_usd"]

    def test_thinking_tokens_billed_as_output(self):
        """Przy Pro to one, a nie audio, odpowiadają za wzrost rachunku."""
        without = estimate_usage_and_cost(usage(), model="gemini-2.5-pro")
        with_thinking = estimate_usage_and_cost(usage(thoughts=1_000), model="gemini-2.5-pro")
        delta = with_thinking["estimated_cost_usd"] - without["estimated_cost_usd"]
        assert delta == pytest.approx(1_000 * 10.00 / 1_000_000)
        assert with_thinking["thoughts_tokens"] == 1_000


class TestLongContextTier:
    """200 tys. tokenów to ~1 h 44 min nagrania — próg jest osiągalny, nie teoretyczny."""

    def test_at_threshold_still_standard(self):
        result = estimate_usage_and_cost(
            usage(prompt=200_000, audio=200_000, text=0), model="gemini-2.5-pro"
        )
        assert result["pricing_tier"] == "standard"

    def test_one_token_over_switches_tier(self):
        result = estimate_usage_and_cost(
            usage(prompt=200_001, audio=200_001, text=0), model="gemini-2.5-pro"
        )
        assert result["pricing_tier"] == "long_context"
        expected = (200_001 * 2.50 + 2_500 * 15.00) / 1_000_000
        assert result["estimated_cost_usd"] == pytest.approx(round(expected, 6))

    def test_output_follows_the_prompt_tier(self):
        """Krótka odpowiedź na wielki prompt też idzie po wyższej stawce."""
        result = estimate_usage_and_cost(
            usage(prompt=250_000, output=100, audio=250_000, text=0), model="gemini-2.5-pro"
        )
        expected = (250_000 * 2.50 + 100 * 15.00) / 1_000_000
        assert result["estimated_cost_usd"] == pytest.approx(round(expected, 6))

    def test_flash_has_no_tier(self):
        result = estimate_usage_and_cost(
            usage(prompt=500_000, audio=500_000, text=0), model="gemini-2.5-flash"
        )
        assert result["pricing_tier"] == "standard"


class TestUnknownModel:
    def test_does_not_raise_and_does_not_under_report(self):
        result = estimate_usage_and_cost(usage(), model="gemini-9-ultra")
        assert result["pricing_known"] is False
        assert result["pricing_tier"] == "fallback"
        assert result["estimated_cost_usd"] > 0

    def test_fallback_is_never_cheaper_than_a_known_model(self):
        """Własność, która przeżyje przyszłe zmiany cen — dlatego pętla po tabeli."""
        unknown = estimate_usage_and_cost(usage(), model="gemini-9-ultra")
        for name in MODEL_PRICING_USD_PER_1M:
            known = estimate_usage_and_cost(usage(), model=name)
            assert unknown["estimated_cost_usd"] >= known["estimated_cost_usd"], name

    def test_listed_but_unpriced_models_do_not_borrow_family_rates(self):
        """`flash-lite` nie jest Flashem. Dopasowanie prefiksowe wyceniłoby go za drogo."""
        for name in pricing.UNPRICED_MODELS:
            assert is_priced(name) is False
            assert estimate_usage_and_cost(usage(), model=name)["pricing_known"] is False


class TestModelIdentification:
    @pytest.mark.parametrize(
        "raw",
        [
            "gemini-2.5-pro",
            "models/gemini-2.5-pro",
            "publishers/google/models/gemini-2.5-pro",
            "gemini-2.5-pro@001",
            "  Gemini-2.5-Pro  ",
        ],
    )
    def test_normalizes_to_the_same_model(self, raw):
        assert normalize_model_id(raw) == "gemini-2.5-pro"
        assert is_priced(raw) is True

    def test_dated_preview_resolves_through_alias(self):
        rates, tier, known = resolve_rates("gemini-2.5-pro-preview-06-05", 1_000)
        assert known is True
        assert tier == "standard"
        assert rates.output == 10.00

    def test_empty_model_is_unknown_not_a_crash(self):
        assert is_priced("") is False
        assert is_priced(None) is False


class TestContractAndEdgeCases:
    def test_model_is_required(self):
        """Brak domyślnej wartości to mechanizm wymuszający — stąd test."""
        with pytest.raises(TypeError):
            estimate_usage_and_cost(usage())  # type: ignore[call-arg]

    def test_legacy_keys_are_preserved(self):
        result = estimate_usage_and_cost(usage(), model="gemini-2.5-pro")
        assert LEGACY_KEYS <= set(result)

    def test_missing_usage_metadata_returns_zeros(self):
        result = estimate_usage_and_cost(None, model="gemini-2.5-pro")
        assert result["estimated_cost_usd"] == 0.0
        assert result["total_tokens"] == 0
        assert LEGACY_KEYS <= set(result)

    def test_unknown_modality_bills_whole_prompt_as_audio(self):
        result = estimate_usage_and_cost(
            usage(audio=None, text=None), model="gemini-2.5-flash"
        )
        assert result["modality_known"] is False
        assert result["prompt_audio_tokens"] == 100_000
        expected = (100_000 * 1.00 + 2_500 * 2.50) / 1_000_000
        assert result["estimated_cost_usd"] == pytest.approx(round(expected, 6))

    def test_unknown_modality_is_harmless_on_pro(self):
        """Przy Pro audio i tekst kosztują tyle samo, więc zapasowa ścieżka nic nie zmienia."""
        known = estimate_usage_and_cost(usage(), model="gemini-2.5-pro")
        unknown = estimate_usage_and_cost(usage(audio=None, text=None), model="gemini-2.5-pro")
        assert unknown["estimated_cost_usd"] == pytest.approx(known["estimated_cost_usd"])
