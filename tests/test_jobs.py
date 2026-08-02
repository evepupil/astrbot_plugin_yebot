from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta

import pytest

from yebot.domain.identity import Identity, UserRole
from yebot.runtime.jobs import JobScheduler, JobStatus, JsonJobStore, MemoryJobStore


def identity(user_id: str = "42") -> Identity:
    return Identity(user_id, "100", UserRole.MEMBER, "member")


def test_reminder_lifecycle_and_member_scope() -> None:
    now = [datetime(2026, 1, 1, tzinfo=UTC)]
    scheduler = JobScheduler(MemoryJobStore(), clock=lambda: now[0])
    job = scheduler.create_reminder(identity(), delay_seconds=60, message="开会")

    assert job.status is JobStatus.PENDING
    assert scheduler.list_for(identity()) == (job,)
    with pytest.raises(PermissionError):
        scheduler.cancel(identity("43"), job.job_id)

    paused = scheduler.pause(identity(), job.job_id)
    assert paused.status is JobStatus.PAUSED
    resumed = scheduler.resume(identity(), job.job_id)
    assert resumed.status is JobStatus.PENDING
    cancelled = scheduler.cancel(identity(), job.job_id)
    assert cancelled.status is JobStatus.CANCELLED


def test_due_job_retries_with_backoff_then_completes() -> None:
    now = [datetime(2026, 1, 1, tzinfo=UTC)]
    store = MemoryJobStore()
    scheduler = JobScheduler(store, clock=lambda: now[0])
    job = scheduler.create_reminder(identity(), delay_seconds=1, message="提醒")
    now[0] = job.run_at
    calls = [0]

    async def flaky_executor(_job: object) -> None:
        calls[0] += 1
        if calls[0] == 1:
            raise RuntimeError("temporary")

    first = asyncio.run(scheduler.run_due(flaky_executor, now=now[0]))
    assert first[0].status is JobStatus.PENDING
    assert first[0].attempts == 1
    assert first[0].run_at == now[0] + timedelta(seconds=30)

    now[0] = first[0].run_at
    second = asyncio.run(scheduler.run_due(flaky_executor, now=now[0]))
    assert second[0].status is JobStatus.COMPLETED
    assert calls[0] == 2


def test_failed_job_stops_after_max_attempts() -> None:
    now = [datetime(2026, 1, 1, tzinfo=UTC)]
    store = MemoryJobStore()
    scheduler = JobScheduler(store, clock=lambda: now[0])
    original = scheduler.create_reminder(identity(), delay_seconds=1, message="失败")
    current = original

    async def failing_executor(_job: object) -> None:
        raise ValueError("bad")

    for _ in range(original.max_attempts):
        now[0] = current.run_at
        current = asyncio.run(scheduler.run_due(failing_executor, now=now[0]))[0]

    assert current.status is JobStatus.FAILED
    assert current.last_error == "ValueError"


def test_json_store_round_trip(tmp_path: object) -> None:
    path = tmp_path / "jobs.json"
    store = JsonJobStore(path)
    scheduler = JobScheduler(store)
    job = scheduler.create_reminder(identity(), delay_seconds=60, message="持久化")

    restored = JsonJobStore(path)
    assert restored.get(job.job_id) == job
