"""Process-local aggregation of token usage reported by AstrBot."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from datetime import UTC, datetime


def _utc_now() -> datetime:
    return datetime.now(UTC)


class TokenUsageTracker:
    """Aggregate provider usage observed by YeBot without storing message content."""

    def __init__(self, *, wall_clock: Callable[[], datetime] = _utc_now) -> None:
        self._wall_clock = wall_clock
        self._started_at = _format_timestamp(wall_clock())
        self._responses_with_usage = 0
        self._responses_without_usage = 0
        self._input_other = 0
        self._input_cached = 0
        self._output = 0
        self._last_observed_at: str | None = None

    def record_response(self, response: object) -> bool:
        """Record the usage object attached to one AstrBot LLM response."""

        return self.record_usage(getattr(response, "usage", None))

    def record_usage(self, usage: object) -> bool:
        """Record a TokenUsage-like object and report whether it was usable."""

        values = {
            name: _usage_value(usage, name)
            for name in ("input_other", "input_cached", "output")
        }
        if not any(value is not None for value in values.values()):
            self._responses_without_usage += 1
            return False

        self._responses_with_usage += 1
        self._input_other += values["input_other"] or 0
        self._input_cached += values["input_cached"] or 0
        self._output += values["output"] or 0
        self._last_observed_at = _format_timestamp(self._wall_clock())
        return True

    def snapshot(self) -> dict[str, object]:
        """Return a stable, privacy-preserving summary for the Agent."""

        input_tokens = self._input_other + self._input_cached
        return {
            "status": "available" if self._responses_with_usage else "unavailable",
            "source": "AstrBot LLMResponse.usage",
            "scope": "current_process",
            "observed_since": self._started_at,
            "responses_with_usage": self._responses_with_usage,
            "responses_without_usage": self._responses_without_usage,
            "input_other_tokens": self._input_other,
            "input_cached_tokens": self._input_cached,
            "input_tokens": input_tokens,
            "output_tokens": self._output,
            "total_tokens": input_tokens + self._output,
            "last_observed_at": self._last_observed_at,
        }


def _usage_value(usage: object, name: str) -> int | None:
    candidate: object
    if isinstance(usage, Mapping):
        candidate = usage.get(name)
    else:
        candidate = getattr(usage, name, None)
    if not isinstance(candidate, int) or isinstance(candidate, bool):
        return None
    return max(candidate, 0)


def _format_timestamp(value: datetime) -> str:
    normalized = (
        value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)
    )
    return normalized.isoformat(timespec="seconds").replace("+00:00", "Z")
