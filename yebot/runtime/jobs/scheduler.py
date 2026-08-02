"""Bounded reminder scheduling with pause, cancel, retry, and backoff."""

from __future__ import annotations

import asyncio
import uuid
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime, timedelta

from ...domain.identity import Identity, UserRole, normalize_id
from ..release import RuntimeMetrics
from .models import Job, JobKind, JobStatus
from .store import JobStore

JobExecutor = Callable[[Job], Awaitable[None]]


class JobScheduler:
    """Keep task lifecycle transitions explicit and restart-safe."""

    def __init__(
        self,
        store: JobStore,
        *,
        clock: Callable[[], datetime] | None = None,
        max_message_length: int = 1000,
        metrics: RuntimeMetrics | None = None,
    ) -> None:
        self._store = store
        self._clock = clock or (lambda: datetime.now(UTC))
        self._max_message_length = max_message_length
        self._metrics = metrics
        self._run_lock = asyncio.Lock()

    def create_reminder(
        self,
        identity: Identity,
        *,
        delay_seconds: int,
        message: str,
    ) -> Job:
        if not identity.group_id:
            raise ValueError("reminders require a group")
        if delay_seconds < 1 or delay_seconds > 2_592_000:
            raise ValueError("delay_seconds is outside the supported range")
        text = message.strip()
        if not text or len(text) > self._max_message_length:
            raise ValueError("message is empty or too long")
        now = self._now()
        job = Job(
            job_id=f"job-{uuid.uuid4().hex[:16]}",
            kind=JobKind.REMINDER,
            owner_id=normalize_id(identity.user_id),
            group_id=normalize_id(identity.group_id),
            payload={"message": text},
            run_at=now + timedelta(seconds=delay_seconds),
            created_at=now,
            updated_at=now,
        )
        self._store.put(job)
        return job

    def list_for(self, identity: Identity) -> tuple[Job, ...]:
        jobs = [job for job in self._store.list() if job.group_id == identity.group_id]
        if identity.role is UserRole.MEMBER:
            jobs = [job for job in jobs if job.owner_id == identity.user_id]
        return tuple(jobs)

    def cancel(self, identity: Identity, job_id: str) -> Job:
        return self._change_status(identity, job_id, JobStatus.CANCELLED)

    def pause(self, identity: Identity, job_id: str) -> Job:
        return self._change_status(identity, job_id, JobStatus.PAUSED)

    def resume(self, identity: Identity, job_id: str) -> Job:
        return self._change_status(identity, job_id, JobStatus.PENDING)

    async def run_due(
        self,
        executor: JobExecutor,
        *,
        now: datetime | None = None,
        limit: int = 10,
    ) -> tuple[Job, ...]:
        """Run a bounded batch and converge failures into retry or failed states."""

        if limit < 1:
            raise ValueError("limit must be positive")
        async with self._run_lock:
            current = self._now() if now is None else _utc(now)
            due = [job for job in self._store.list() if job.is_due(current)][:limit]
            finished: list[Job] = []
            for job in due:
                running = job.with_update(status=JobStatus.RUNNING)
                self._store.put(running)
                try:
                    await executor(running)
                except Exception as error:
                    if self._metrics is not None:
                        self._metrics.record_job("failed")
                    attempts = running.attempts + 1
                    if attempts >= running.max_attempts:
                        failed = running.with_update(
                            status=JobStatus.FAILED,
                            attempts=attempts,
                            last_error=type(error).__name__,
                        )
                    else:
                        retry_at = current + timedelta(
                            seconds=running.backoff_seconds * (2 ** (attempts - 1))
                        )
                        failed = running.with_update(
                            status=JobStatus.PENDING,
                            attempts=attempts,
                            run_at=retry_at,
                            last_error=type(error).__name__,
                        )
                    self._store.put(failed)
                    finished.append(failed)
                    continue
                completed = running.with_update(status=JobStatus.COMPLETED)
                self._store.put(completed)
                if self._metrics is not None:
                    self._metrics.record_job("completed")
                finished.append(completed)
            return tuple(finished)

    def _change_status(self, identity: Identity, job_id: str, status: JobStatus) -> Job:
        job = self._store.get(job_id)
        if job is None or job.group_id != identity.group_id:
            raise KeyError("job not found")
        if identity.role is UserRole.MEMBER and job.owner_id != identity.user_id:
            raise PermissionError("job belongs to another member")
        if job.status in {JobStatus.COMPLETED, JobStatus.CANCELLED, JobStatus.FAILED}:
            raise ValueError("job is already terminal")
        changed = job.with_update(status=status)
        self._store.put(changed)
        return changed

    def _now(self) -> datetime:
        return _utc(self._clock())


def _utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)
