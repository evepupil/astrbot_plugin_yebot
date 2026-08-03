import math

import pytest

from yebot.runtime.token_calculator import TokenCalculator, TokenScene, normalize_scene


def test_default_domestic_calculation_matches_token_cal() -> None:
    result = TokenCalculator().calculate(total_tokens_million=563.37)

    assert result["scene"] == "domestic"
    assert result["ratio"] == 245
    assert result["average_price_per_million"] == pytest.approx(0.3653878048780488)
    assert result["estimated_total_cost"] == pytest.approx(205.8485276341463)
    assert result["average_price_display"] == "$0.36539 / M"
    assert result["estimated_total_cost_display"] == "$205.85"


def test_foreign_scene_and_chinese_alias_are_supported() -> None:
    assert normalize_scene("长上下文重用") is TokenScene.FOREIGN

    result = TokenCalculator().calculate(
        total_tokens_million=1,
        scene="国外",
        input_price=2,
        output_price=5,
        cache_price=0.5,
        cache_hit_rate=50,
    )

    assert result["scene"] == "foreign"
    assert result["ratio"] == 480
    assert result["effective_input_price"] == pytest.approx(1.25)
    assert result["average_price_per_million"] == pytest.approx(
        (480 * 1.25 + 5) / 481
    )


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("total_tokens_million", -1),
        ("input_price", math.inf),
        ("output_price", math.nan),
        ("cache_price", 1_000_001),
        ("cache_hit_rate", 100.1),
    ],
)
def test_calculator_rejects_invalid_numeric_values(field: str, value: object) -> None:
    arguments: dict[str, object] = {"total_tokens_million": 1}
    arguments[field] = value

    with pytest.raises(ValueError):
        TokenCalculator().calculate(**arguments)  # type: ignore[arg-type]


def test_calculator_rejects_unknown_scene() -> None:
    with pytest.raises(ValueError, match="domestic or foreign"):
        TokenCalculator().calculate(total_tokens_million=1, scene="unknown")
