"""Restart-safe daily quotas for user-triggered image generation."""

from __future__ import annotations

import asyncio
import json
import os
import tempfile
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path


@dataclass(frozen=True, slots=True)
class QuotaDecision:
    """Result of reserving one image-generation opportunity."""

    allowed: bool
    remaining: int | None
    owner_exempt: bool = False


@dataclass(frozen=True, slots=True)
class _QuotaRecord:
    day: str
    count: int


class DailyImageQuota:
    """Keep one daily counter per user, shared across groups and private chats."""

    def __init__(self, path: str | Path, limit: int = 3) -> None:
        if limit < 0:
            raise ValueError("limit must be non-negative")
        self.path = Path(path)
        self.limit = limit
        self._records: dict[str, _QuotaRecord] = {}
        self._lock = asyncio.Lock()
        self._load()

    async def reserve(
        self,
        user_id: str,
        *,
        is_owner: bool,
        now: date | datetime | None = None,
    ) -> QuotaDecision:
        """Atomically reserve one opportunity before starting a remote request."""

        if is_owner:
            return QuotaDecision(True, None, owner_exempt=True)

        normalized_user_id = user_id.strip()
        if not normalized_user_id:
            return QuotaDecision(False, 0)

        current_day = _day_key(now)
        async with self._lock:
            previous = self._records.get(normalized_user_id)
            used = (
                previous.count
                if previous is not None and previous.day == current_day
                else 0
            )
            if used >= self.limit:
                return QuotaDecision(False, 0)

            used += 1
            self._records[normalized_user_id] = _QuotaRecord(current_day, used)
            self._flush()
            return QuotaDecision(True, self.limit - used)

    def _load(self) -> None:
        try:
            raw = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, TypeError, ValueError):
            return
        if not isinstance(raw, Mapping):
            return
        users = raw.get("users")
        if not isinstance(users, Mapping):
            return
        for user_id, value in users.items():
            if not isinstance(user_id, str) or not isinstance(value, Mapping):
                continue
            day = value.get("day")
            count = value.get("count")
            if (
                isinstance(day, str)
                and isinstance(count, int)
                and not isinstance(count, bool)
                and count >= 0
            ):
                self._records[user_id] = _QuotaRecord(day, count)

    def _flush(self) -> None:
        payload = {
            "version": 1,
            "users": {
                user_id: {"day": record.day, "count": record.count}
                for user_id, record in self._records.items()
            },
        }
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            descriptor, temporary = tempfile.mkstemp(
                prefix=f".{self.path.name}.",
                suffix=".tmp",
                dir=self.path.parent,
            )
            try:
                with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
                    json.dump(
                        payload, stream, ensure_ascii=False, separators=(",", ":")
                    )
                    stream.flush()
                    os.fsync(stream.fileno())
                os.replace(temporary, self.path)
            finally:
                if os.path.exists(temporary):
                    os.unlink(temporary)
        except OSError:
            # The in-memory counter still protects the current process if the
            # configured persistence path is temporarily unavailable.
            return


def _day_key(value: date | datetime | None) -> str:
    if value is None:
        return datetime.now().astimezone().date().isoformat()
    if isinstance(value, datetime):
        return (
            value.astimezone().date().isoformat()
            if value.tzinfo
            else value.date().isoformat()
        )
    return value.isoformat()
