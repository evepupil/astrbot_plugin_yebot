"""Small storage adapters for restart-safe job records."""

from __future__ import annotations

import json
import os
import tempfile
from collections.abc import Iterable
from datetime import datetime
from pathlib import Path
from typing import Protocol

from .models import Job, JobKind, JobStatus


class JobStore(Protocol):
    def list(self) -> tuple[Job, ...]: ...

    def get(self, job_id: str) -> Job | None: ...

    def put(self, job: Job) -> None: ...

    def delete(self, job_id: str) -> None: ...


class MemoryJobStore:
    """Deterministic store used by tests and ephemeral deployments."""

    def __init__(self, jobs: Iterable[Job] = ()) -> None:
        self._jobs = {job.job_id: job for job in jobs}

    def list(self) -> tuple[Job, ...]:
        return tuple(sorted(self._jobs.values(), key=lambda job: job.job_id))

    def get(self, job_id: str) -> Job | None:
        return self._jobs.get(job_id.strip())

    def put(self, job: Job) -> None:
        self._jobs[job.job_id] = job

    def delete(self, job_id: str) -> None:
        self._jobs.pop(job_id.strip(), None)


class JsonJobStore:
    """Atomic JSON persistence with a bounded, data-only schema."""

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        self._jobs: dict[str, Job] = {}
        self._load()

    def list(self) -> tuple[Job, ...]:
        return tuple(sorted(self._jobs.values(), key=lambda job: job.job_id))

    def get(self, job_id: str) -> Job | None:
        return self._jobs.get(job_id.strip())

    def put(self, job: Job) -> None:
        self._jobs[job.job_id] = job
        self._flush()

    def delete(self, job_id: str) -> None:
        self._jobs.pop(job_id.strip(), None)
        self._flush()

    def _load(self) -> None:
        if not self.path.exists():
            return
        try:
            raw = json.loads(self.path.read_text(encoding="utf-8"))
            records = raw.get("jobs", []) if isinstance(raw, dict) else []
            if not isinstance(records, list):
                return
            for record in records:
                job = _decode_job(record)
                if job is not None:
                    self._jobs[job.job_id] = job
        except (OSError, ValueError, TypeError, KeyError):
            self._jobs = {}

    def _flush(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        payload = {"version": 1, "jobs": [_encode_job(job) for job in self.list()]}
        fd, temporary = tempfile.mkstemp(
            prefix=f".{self.path.name}.", suffix=".tmp", dir=self.path.parent
        )
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as stream:
                json.dump(payload, stream, ensure_ascii=False, separators=(",", ":"))
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary, self.path)
        finally:
            if os.path.exists(temporary):
                os.unlink(temporary)


def _encode_job(job: Job) -> dict[str, object]:
    return {
        "job_id": job.job_id,
        "kind": job.kind.value,
        "owner_id": job.owner_id,
        "group_id": job.group_id,
        "payload": dict(job.payload),
        "run_at": job.run_at.isoformat(),
        "status": job.status.value,
        "attempts": job.attempts,
        "max_attempts": job.max_attempts,
        "backoff_seconds": job.backoff_seconds,
        "last_error": job.last_error,
        "created_at": job.created_at.isoformat(),
        "updated_at": job.updated_at.isoformat(),
    }


def _decode_job(value: object) -> Job | None:
    if not isinstance(value, dict):
        return None
    try:
        payload = value.get("payload")
        if not isinstance(payload, dict):
            return None
        return Job(
            job_id=str(value["job_id"]),
            kind=JobKind(str(value["kind"])),
            owner_id=str(value["owner_id"]),
            group_id=str(value["group_id"]),
            payload=payload,
            run_at=_parse_datetime(value["run_at"]),
            status=JobStatus(str(value.get("status", JobStatus.PENDING.value))),
            attempts=int(value.get("attempts", 0)),
            max_attempts=int(value.get("max_attempts", 3)),
            backoff_seconds=int(value.get("backoff_seconds", 30)),
            last_error=(
                str(value["last_error"])
                if value.get("last_error") is not None
                else None
            ),
            created_at=_parse_datetime(value["created_at"]),
            updated_at=_parse_datetime(value["updated_at"]),
        )
    except (KeyError, TypeError, ValueError, OverflowError):
        return None


def _parse_datetime(value: object) -> datetime:
    if not isinstance(value, str):
        raise ValueError("datetime must be a string")
    return datetime.fromisoformat(value)
