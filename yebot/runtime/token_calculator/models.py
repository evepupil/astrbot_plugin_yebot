"""Validated value objects for TokenCal calculations."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum


class TokenScene(StrEnum):
    """The two usage scenarios offered by TokenCal."""

    DOMESTIC = "domestic"
    FOREIGN = "foreign"

    @property
    def ratio(self) -> int:
        return 245 if self is TokenScene.DOMESTIC else 480

    @property
    def label(self) -> str:
        return (
            "国产 / Agent 交互 (245 : 1)"
            if self is TokenScene.DOMESTIC
            else "国外 / 长上下文重用 (480 : 1)"
        )


@dataclass(frozen=True, slots=True)
class TokenCalculation:
    """One bounded TokenCal calculation with unrounded numeric results."""

    scene: TokenScene
    input_price: float
    output_price: float
    cache_price: float
    cache_hit_rate: float
    total_tokens_million: float
    effective_input_price: float
    average_price_per_million: float
    estimated_total_cost: float

    def as_dict(self) -> dict[str, object]:
        return {
            "source": "TokenCal",
            "url": "https://tokencal.chaosyn.com/",
            "scene": self.scene.value,
            "scene_label": self.scene.label,
            "ratio": self.scene.ratio,
            "input_price": self.input_price,
            "output_price": self.output_price,
            "cache_price": self.cache_price,
            "cache_hit_rate": self.cache_hit_rate,
            "total_tokens_million": self.total_tokens_million,
            "effective_input_price": self.effective_input_price,
            "average_price_per_million": self.average_price_per_million,
            "estimated_total_cost": self.estimated_total_cost,
            "average_price_display": (f"${self.average_price_per_million:.5f} / M"),
            "estimated_total_cost_display": f"${self.estimated_total_cost:.2f}",
        }


def normalize_scene(value: object) -> TokenScene:
    """Accept the site's values and common Chinese descriptions."""

    if not isinstance(value, str):
        raise ValueError("scene must be a string")
    normalized = value.strip().casefold()
    if normalized in {"domestic", "国产", "国内", "agent", "agent交互"}:
        return TokenScene.DOMESTIC
    if normalized in {
        "foreign",
        "国外",
        "海外",
        "long_context",
        "long-context",
        "长上下文",
        "长上下文重用",
    }:
        return TokenScene.FOREIGN
    raise ValueError("scene must be domestic or foreign")
