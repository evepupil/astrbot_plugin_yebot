"""Small in-process counters for health and operational summaries."""

from __future__ import annotations

from collections import Counter
from collections.abc import Mapping
from dataclasses import dataclass
from types import MappingProxyType


@dataclass(frozen=True, slots=True)
class MetricsSnapshot:
    tool_calls: int
    tool_failures: int
    job_runs: int
    job_failures: int
    by_tool: Mapping[str, int]
    by_outcome: Mapping[str, int]


class RuntimeMetrics:
    """Avoid raw messages and credentials while tracking runtime health."""

    def __init__(self) -> None:
        self._tool_calls = 0
        self._tool_failures = 0
        self._job_runs = 0
        self._job_failures = 0
        self._by_tool: Counter[str] = Counter()
        self._by_outcome: Counter[str] = Counter()

    def record_tool(self, tool_name: str, outcome: str) -> None:
        normalized_tool = tool_name.strip().lower()
        normalized_outcome = outcome.strip().lower()
        self._tool_calls += 1
        self._by_tool[normalized_tool] += 1
        self._by_outcome[normalized_outcome] += 1
        if normalized_outcome in {
            "error",
            "failed",
            "timeout",
            "quota_exceeded",
            "execution_error",
            "role_denied",
            "out_of_scope",
        }:
            self._tool_failures += 1

    def record_job(self, outcome: str) -> None:
        normalized = outcome.strip().lower()
        self._job_runs += 1
        if normalized not in {"completed", "success"}:
            self._job_failures += 1

    def snapshot(self) -> MetricsSnapshot:
        return MetricsSnapshot(
            self._tool_calls,
            self._tool_failures,
            self._job_runs,
            self._job_failures,
            MappingProxyType(dict(self._by_tool)),
            MappingProxyType(dict(self._by_outcome)),
        )
