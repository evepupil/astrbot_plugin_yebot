"""Pure local TokenCal formula with bounded numeric inputs."""

from __future__ import annotations

import math

from .models import TokenCalculation, normalize_scene

DEFAULT_TOKEN_CALCULATOR_URL = "https://tokencal.chaosyn.com/"
DEFAULT_INPUT_PRICE = 1.40
DEFAULT_OUTPUT_PRICE = 4.40
DEFAULT_CACHE_PRICE = 0.26
DEFAULT_CACHE_HIT_RATE = 92.2
_MAX_PRICE = 1_000_000.0
_MAX_TOTAL_TOKENS_MILLION = 1_000_000_000.0


class TokenCalculator:
    """Calculate blended TokenCal price and estimated total cost locally."""

    def calculate(
        self,
        *,
        total_tokens_million: float,
        scene: str = "domestic",
        input_price: float = DEFAULT_INPUT_PRICE,
        output_price: float = DEFAULT_OUTPUT_PRICE,
        cache_price: float = DEFAULT_CACHE_PRICE,
        cache_hit_rate: float = DEFAULT_CACHE_HIT_RATE,
    ) -> dict[str, object]:
        selected_scene = normalize_scene(scene)
        bounded_input_price = _bounded_number(
            input_price, "input_price", maximum=_MAX_PRICE
        )
        bounded_output_price = _bounded_number(
            output_price, "output_price", maximum=_MAX_PRICE
        )
        bounded_cache_price = _bounded_number(
            cache_price, "cache_price", maximum=_MAX_PRICE
        )
        bounded_cache_hit_rate = _bounded_number(
            cache_hit_rate, "cache_hit_rate", maximum=100.0
        )
        bounded_total_tokens = _bounded_number(
            total_tokens_million,
            "total_tokens_million",
            maximum=_MAX_TOTAL_TOKENS_MILLION,
        )

        cache_ratio = bounded_cache_hit_rate / 100.0
        ratio = selected_scene.ratio
        denominator = ratio + 1
        effective_input_price = (
            1 - cache_ratio
        ) * bounded_input_price + cache_ratio * bounded_cache_price
        average_price = (
            ratio * effective_input_price + bounded_output_price
        ) / denominator
        estimated_total_cost = average_price * bounded_total_tokens
        return TokenCalculation(
            scene=selected_scene,
            input_price=bounded_input_price,
            output_price=bounded_output_price,
            cache_price=bounded_cache_price,
            cache_hit_rate=bounded_cache_hit_rate,
            total_tokens_million=bounded_total_tokens,
            effective_input_price=effective_input_price,
            average_price_per_million=average_price,
            estimated_total_cost=estimated_total_cost,
        ).as_dict()


def _bounded_number(value: object, label: str, *, maximum: float) -> float:
    if not isinstance(value, (int, float)) or isinstance(value, bool):
        raise ValueError(f"{label} must be a number")
    number = float(value)
    if not math.isfinite(number) or number < 0 or number > maximum:
        raise ValueError(f"{label} is out of range")
    return number
