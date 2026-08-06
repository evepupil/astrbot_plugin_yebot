import asyncio
from datetime import UTC, datetime
from types import SimpleNamespace

import pytest

from yebot.runtime.system_info import (
    SystemInfoCollector,
    TokenUsageTracker,
    calculate_cpu_percent,
    format_bytes,
    format_duration,
)


def test_token_usage_tracker_sums_real_usage_and_marks_missing_usage() -> None:
    tracker = TokenUsageTracker()

    assert tracker.record_response(
        SimpleNamespace(
            usage=SimpleNamespace(input_other=100, input_cached=25, output=30)
        )
    )
    assert not tracker.record_response(SimpleNamespace(usage=None))

    snapshot = tracker.snapshot()
    assert snapshot["status"] == "available"
    assert snapshot["source"] == "AstrBot LLMResponse.usage"
    assert snapshot["scope"] == "current_process"
    assert snapshot["responses_with_usage"] == 1
    assert snapshot["responses_without_usage"] == 1
    assert snapshot["input_other_tokens"] == 100
    assert snapshot["input_cached_tokens"] == 25
    assert snapshot["input_tokens"] == 125
    assert snapshot["output_tokens"] == 30
    assert snapshot["total_tokens"] == 155
    assert snapshot["observed_since"]
    assert snapshot["last_observed_at"]


def test_token_usage_tracker_accepts_mapping_usage() -> None:
    tracker = TokenUsageTracker()

    assert tracker.record_usage({"input_other": 4, "input_cached": 6, "output": 10})

    assert tracker.snapshot()["total_tokens"] == 20


def test_system_info_collector_returns_cpu_memory_and_uptime() -> None:
    cpu_values: list[tuple[int, int] | None] = [(100, 40), (200, 90)]
    monotonic_values = [100.0, 112.345]
    wall_clock_value = datetime(2026, 8, 6, 4, 0, tzinfo=UTC)

    def cpu_reader() -> tuple[int, int] | None:
        return cpu_values.pop(0)

    def monotonic() -> float:
        return monotonic_values.pop(0)

    snapshot = asyncio.run(
        SystemInfoCollector(
            sample_interval_seconds=0,
            monotonic=monotonic,
            wall_clock=lambda: wall_clock_value,
            cpu_reader=cpu_reader,
            memory_reader=lambda: (1_000_000, 250_000),
            uptime_reader=lambda: 98_765.0,
            process_memory_reader=lambda: 12_345,
        ).collect()
    )

    assert snapshot["status"] == "ok"
    assert snapshot["cpu"]["usage_percent"] == 50.0  # type: ignore[index]
    assert snapshot["memory"] == {  # type: ignore[comparison-overlap]
        "available": True,
        "total_bytes": 1_000_000,
        "total_display": "976.6 KiB",
        "available_bytes": 250_000,
        "available_display": "244.1 KiB",
        "used_bytes": 750_000,
        "used_display": "732.4 KiB",
        "used_percent": 75.0,
    }
    assert snapshot["system"]["uptime_display"] == "1d 3h 26m 5s"  # type: ignore[index]
    assert snapshot["process"]["uptime_seconds"] == 12.345  # type: ignore[index]
    assert snapshot["process"]["rss_bytes"] == 12_345  # type: ignore[index]
    assert snapshot["process"]["rss_display"] == "12.1 KiB"  # type: ignore[index]


@pytest.mark.parametrize(
    ("before", "after", "expected"),
    [
        ((100, 40), (200, 90), 50.0),
        (None, (200, 90), None),
        ((100, 40), (100, 40), None),
    ],
)
def test_cpu_percent_handles_missing_or_invalid_samples(
    before: tuple[int, int] | None,
    after: tuple[int, int] | None,
    expected: float | None,
) -> None:
    assert calculate_cpu_percent(before, after) == expected


def test_format_duration_uses_compact_units() -> None:
    assert format_duration(90_061) == "1d 1h 1m 1s"


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        (0, "0 B"),
        (1024, "1.0 KiB"),
        (1024**3, "1.0 GiB"),
        (None, None),
    ],
)
def test_format_bytes_uses_binary_units(
    value: int | None, expected: str | None
) -> None:
    assert format_bytes(value) == expected
