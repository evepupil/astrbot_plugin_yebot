"""Per-request budgets shared by repeated main-agent tool calls."""

from __future__ import annotations

import time
from collections.abc import Callable
from dataclasses import dataclass

from .models import AgentBudget, RunStatus


@dataclass(frozen=True, slots=True)
class Reservation:
    """Outcome of reserving one step in a request budget."""

    allowed: bool
    status: RunStatus | None
    steps_used: int
    elapsed_seconds: float

    @property
    def summary(self) -> str:
        if self.status is RunStatus.STEP_LIMIT:
            return f"step limit reached after {self.steps_used} step(s)"
        if self.status is RunStatus.TIMEOUT:
            return "orchestration timed out before the next step"
        return "step reserved"


@dataclass(slots=True)
class _RequestState:
    started_at: float
    last_seen: float
    steps_used: int = 0


class AgentRequestTracker:
    """Keep a short-lived budget state without retaining message content."""

    def __init__(
        self,
        budget: AgentBudget,
        *,
        clock: Callable[[], float] = time.monotonic,
        max_entries: int = 1024,
    ) -> None:
        if max_entries < 1:
            raise ValueError("max_entries must be positive")
        self._budget = budget
        self._clock = clock
        self._max_entries = max_entries
        self._states: dict[str, _RequestState] = {}

    def reserve(self, request_id: str) -> Reservation:
        """Reserve one step, returning a stable denial after the budget ends."""

        key = request_id.strip()
        now = self._clock()
        if not key:
            return Reservation(True, None, 1, 0.0)

        self._prune(now)
        state = self._states.get(key)
        if state is None:
            state = _RequestState(started_at=now, last_seen=now)
            self._states[key] = state
        state.last_seen = now
        elapsed = max(0.0, now - state.started_at)
        if elapsed >= self._budget.timeout_seconds:
            return Reservation(False, RunStatus.TIMEOUT, state.steps_used, elapsed)
        if state.steps_used >= self._budget.max_steps:
            return Reservation(False, RunStatus.STEP_LIMIT, state.steps_used, elapsed)
        state.steps_used += 1
        return Reservation(True, None, state.steps_used, elapsed)

    def _prune(self, now: float) -> None:
        expiry = max(60.0, self._budget.timeout_seconds * 2)
        expired = [
            key for key, state in self._states.items() if now - state.last_seen > expiry
        ]
        for key in expired:
            del self._states[key]
        if len(self._states) <= self._max_entries:
            return
        excess = len(self._states) - self._max_entries
        oldest = sorted(self._states, key=lambda key: self._states[key].last_seen)
        for key in oldest[:excess]:
            del self._states[key]
