from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import pytest

from yebot.domain.identity import Identity, UserRole
from yebot.runtime.jobs import JobScheduler, JobStatus, JsonJobStore, MemoryJobStore
from yebot.runtime.jobs.native_access import native_cron_job_accessible


def identity(user_id: str = "42", group_id: str = "100") -> Identity:
    return Identity(user_id, group_id, UserRole.MEMBER, "member")


def test_reminder_lifecycle_is_shared_within_group() -> None:
    now = [datetime(2026, 1, 1, tzinfo=UTC)]
    scheduler = JobScheduler(MemoryJobStore(), clock=lambda: now[0])
    job = scheduler.create_reminder(identity(), delay_seconds=60, message="开会")

    assert job.status is JobStatus.PENDING
    other_member = identity("43")
    assert scheduler.list_for_group(other_member) == (job,)

    paused = scheduler.pause(other_member, job.job_id)
    assert paused.status is JobStatus.PAUSED
    resumed = scheduler.resume(identity(), job.job_id)
    assert resumed.status is JobStatus.PENDING
    cancelled = scheduler.cancel(other_member, job.job_id)
    assert cancelled.status is JobStatus.CANCELLED


def test_reminder_management_stays_within_current_group() -> None:
    scheduler = JobScheduler(MemoryJobStore())
    job = scheduler.create_reminder(identity(), delay_seconds=60, message="提醒")
    other_group_member = identity("43", "101")

    assert scheduler.list_for_group(other_group_member) == ()
    with pytest.raises(KeyError):
        scheduler.cancel(other_group_member, job.job_id)


def test_native_cron_group_tasks_are_shared_but_private_tasks_are_not() -> None:
    group_job = SimpleNamespace(
        payload={
            "session": "default:GroupMessage:100",
            "sender_id": "77",
        }
    )
    private_job = SimpleNamespace(
        payload={
            "session": "default:FriendMessage:77",
            "sender_id": "77",
        }
    )

    assert native_cron_job_accessible(
        group_job,
        "default:GroupMessage:100",
        "43",
    )
    assert not native_cron_job_accessible(
        group_job,
        "default:GroupMessage:101",
        "43",
    )
    assert native_cron_job_accessible(
        private_job,
        "default:FriendMessage:77",
        "77",
    )
    assert not native_cron_job_accessible(
        private_job,
        "default:FriendMessage:77",
        "43",
    )


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
