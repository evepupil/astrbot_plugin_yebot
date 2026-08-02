"""SQLite persistence for restart-safe YeBot memories."""

from __future__ import annotations

import json
import sqlite3
from collections.abc import Iterable
from datetime import UTC, datetime
from pathlib import Path
from typing import Protocol

from .models import MemoryKind, MemoryRecord, MemoryScope, MemoryStatus


class MemoryStore(Protocol):
    """Storage operations required by the memory service."""

    def save(self, record: MemoryRecord) -> tuple[str, ...]: ...

    def get(self, memory_id: str) -> MemoryRecord | None: ...

    def active_for_scopes(
        self,
        scopes: Iterable[tuple[MemoryScope, str]],
        *,
        now: datetime,
        limit: int = 200,
    ) -> tuple[MemoryRecord, ...]: ...

    def forget(self, memory_id: str, *, updated_at: datetime) -> bool: ...


class SQLiteMemoryStore:
    """Small transactional store with immutable active-record replacement."""

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._initialize()

    def save(self, record: MemoryRecord) -> tuple[str, ...]:
        now = _iso(record.updated_at)
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT memory_id
                FROM memories
                WHERE scope = ? AND scope_id = ? AND subject_id = ?
                  AND topic = ? AND status = 'active'
                ORDER BY updated_at DESC
                """,
                (record.scope.value, record.scope_id, record.subject_id, record.topic),
            ).fetchall()
            previous_ids = tuple(str(row[0]) for row in rows)
            connection.execute(
                """
                UPDATE memories
                SET status = 'superseded', updated_at = ?
                WHERE scope = ? AND scope_id = ? AND subject_id = ?
                  AND topic = ? AND status = 'active'
                """,
                (
                    now,
                    record.scope.value,
                    record.scope_id,
                    record.subject_id,
                    record.topic,
                ),
            )
            connection.execute(
                """
                INSERT INTO memories (
                    memory_id, scope, scope_id, subject_id, topic, kind, content,
                    tags_json, confidence, created_at, updated_at, expires_at,
                    status, source_request_id, supersedes_id
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    record.memory_id,
                    record.scope.value,
                    record.scope_id,
                    record.subject_id,
                    record.topic,
                    record.kind.value,
                    record.content,
                    json.dumps(record.tags, ensure_ascii=False),
                    record.confidence,
                    _iso(record.created_at),
                    now,
                    _iso(record.expires_at) if record.expires_at else None,
                    record.status.value,
                    record.source_request_id,
                    record.supersedes_id or (previous_ids[0] if previous_ids else None),
                ),
            )
        return previous_ids

    def get(self, memory_id: str) -> MemoryRecord | None:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT * FROM memories WHERE memory_id = ?",
                (memory_id.strip(),),
            ).fetchone()
        return _decode(row) if row is not None else None

    def active_for_scopes(
        self,
        scopes: Iterable[tuple[MemoryScope, str]],
        *,
        now: datetime,
        limit: int = 200,
    ) -> tuple[MemoryRecord, ...]:
        normalized = tuple(
            (scope.value, scope_id.strip())
            for scope, scope_id in scopes
            if scope_id.strip()
        )
        if not normalized:
            return ()
        clauses = " OR ".join("(scope = ? AND scope_id = ?)" for _ in normalized)
        parameters: list[object] = [_iso(_utc(now))]
        parameters.extend(item for pair in normalized for item in pair)
        parameters.append(max(1, min(limit, 500)))
        with self._connect() as connection:
            rows = connection.execute(
                f"""
                SELECT * FROM memories
                WHERE status = 'active'
                  AND (expires_at IS NULL OR expires_at > ?)
                  AND ({clauses})
                ORDER BY updated_at DESC
                LIMIT ?
                """,
                parameters,
            ).fetchall()
        return tuple(record for row in rows if (record := _decode(row)) is not None)

    def forget(self, memory_id: str, *, updated_at: datetime) -> bool:
        with self._connect() as connection:
            result = connection.execute(
                """
                UPDATE memories
                SET status = 'forgotten', updated_at = ?
                WHERE memory_id = ? AND status = 'active'
                """,
                (_iso(_utc(updated_at)), memory_id.strip()),
            )
        return result.rowcount == 1

    def _initialize(self) -> None:
        with self._connect() as connection:
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS memories (
                    memory_id TEXT PRIMARY KEY,
                    scope TEXT NOT NULL,
                    scope_id TEXT NOT NULL,
                    subject_id TEXT NOT NULL,
                    topic TEXT NOT NULL,
                    kind TEXT NOT NULL,
                    content TEXT NOT NULL,
                    tags_json TEXT NOT NULL,
                    confidence REAL NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    expires_at TEXT,
                    status TEXT NOT NULL,
                    source_request_id TEXT NOT NULL,
                    supersedes_id TEXT
                );
                CREATE INDEX IF NOT EXISTS idx_memories_scope
                    ON memories (scope, scope_id, status, updated_at);
                CREATE INDEX IF NOT EXISTS idx_memories_topic
                    ON memories (scope, scope_id, subject_id, topic, status);
                """,
            )

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.path, timeout=5)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA journal_mode = WAL")
        connection.execute("PRAGMA foreign_keys = ON")
        return connection


def _decode(row: sqlite3.Row) -> MemoryRecord | None:
    try:
        tags = json.loads(str(row["tags_json"]))
        if not isinstance(tags, list):
            return None
        return MemoryRecord(
            memory_id=str(row["memory_id"]),
            scope=MemoryScope(str(row["scope"])),
            scope_id=str(row["scope_id"]),
            subject_id=str(row["subject_id"]),
            topic=str(row["topic"]),
            kind=MemoryKind(str(row["kind"])),
            content=str(row["content"]),
            tags=tuple(str(tag) for tag in tags),
            confidence=float(row["confidence"]),
            created_at=_parse_datetime(row["created_at"]),
            updated_at=_parse_datetime(row["updated_at"]),
            expires_at=(
                _parse_datetime(row["expires_at"])
                if row["expires_at"] is not None
                else None
            ),
            status=MemoryStatus(str(row["status"])),
            source_request_id=str(row["source_request_id"]),
            supersedes_id=(
                str(row["supersedes_id"]) if row["supersedes_id"] is not None else None
            ),
        )
    except (KeyError, TypeError, ValueError, json.JSONDecodeError):
        return None


def _parse_datetime(value: object) -> datetime:
    if not isinstance(value, str):
        raise ValueError("memory timestamp must be a string")
    return _utc(datetime.fromisoformat(value))


def _utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def _iso(value: datetime) -> str:
    return _utc(value).isoformat()
