"""Stable data contracts for persistent background jobs."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field, replace
from datetime import UTC, datetime
from enum import StrEnum
from types import MappingProxyType


class JobKind(StrEnum):
    REMINDER = "reminder"


class JobStatus(StrEnum):
    PENDING = "pending"
    RUNNING = "running"
    PAUSED = "paused"
    CANCELLED = "cancelled"
    COMPLETED = "completed"
    FAILED = "failed"


@dataclass(frozen=True, slots=True)
class Job:
    """A restart-safe task record with no executable code in its payload."""

    job_id: str
    kind: JobKind
    owner_id: str
    group_id: str
    payload: Mapping[str, object]
    run_at: datetime
    status: JobStatus = JobStatus.PENDING
    attempts: int = 0
    max_attempts: int = 3
    backoff_seconds: int = 30
    last_error: str | None = None
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    updated_at: datetime = field(default_factory=lambda: datetime.now(UTC))

    def __post_init__(self) -> None:
        if (
            not self.job_id.strip()
            or not self.owner_id.strip()
            or not self.group_id.strip()
        ):
            raise ValueError("job identity fields must not be empty")
        if self.attempts < 0 or self.max_attempts < 1:
            raise ValueError("job attempts must be non-negative and bounded")
        if self.attempts > self.max_attempts:
            raise ValueError("job attempts must not exceed max_attempts")
        if self.backoff_seconds < 1:
            raise ValueError("backoff_seconds must be positive")
        object.__setattr__(self, "job_id", self.job_id.strip())
        object.__setattr__(self, "owner_id", self.owner_id.strip())
        object.__setattr__(self, "group_id", self.group_id.strip())
        object.__setattr__(self, "payload", MappingProxyType(dict(self.payload)))
        object.__setattr__(self, "run_at", _utc(self.run_at))
        object.__setattr__(self, "created_at", _utc(self.created_at))
        object.__setattr__(self, "updated_at", _utc(self.updated_at))
        if self.last_error is not None:
            object.__setattr__(self, "last_error", self.last_error.strip()[:128])

    def is_due(self, now: datetime) -> bool:
        return self.status is JobStatus.PENDING and _utc(now) >= self.run_at

    def with_update(
        self,
        *,
        status: JobStatus | None = None,
        attempts: int | None = None,
        run_at: datetime | None = None,
        last_error: str | None = None,
    ) -> Job:
        return replace(
            self,
            status=self.status if status is None else status,
            attempts=self.attempts if attempts is None else attempts,
            run_at=self.run_at if run_at is None else run_at,
            last_error=self.last_error if last_error is None else last_error,
            updated_at=_utc(datetime.now(UTC)),
        )


def _utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)
