"""Scope checks, validation, recall ranking, and lifecycle operations."""

from __future__ import annotations

import math
import re
import uuid
from collections.abc import Callable, Iterable
from dataclasses import replace
from datetime import UTC, datetime, timedelta

from ...domain.identity import Identity, UserRole, normalize_id
from .models import MemoryKind, MemoryRecord, MemoryScope, MemoryStatus
from .store import MemoryStore

_SENSITIVE_PATTERN = re.compile(
    r"(?:password|passwd|api[_ -]?key|access[_ -]?token|secret|private[_ -]?key|"
    r"cookie|验证码|密码|口令|私钥|访问令牌)",
    re.IGNORECASE,
)
_TERM_PATTERN = re.compile(r"[a-z0-9_]+|[\u4e00-\u9fff]+", re.IGNORECASE)


class MemoryAccessError(PermissionError):
    """Raised when an actor attempts to cross a memory scope boundary."""


class MemoryContentError(ValueError):
    """Raised when a memory is unsafe or exceeds its bounded schema."""


class MemoryService:
    """Provide explicit writes and identity-filtered reads."""

    def __init__(
        self,
        store: MemoryStore,
        *,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self._store = store
        self._clock = clock or (lambda: datetime.now(UTC))

    def remember(
        self,
        identity: Identity,
        *,
        scope: MemoryScope | str,
        topic: str,
        content: str,
        kind: MemoryKind | str = MemoryKind.FACT,
        tags: Iterable[str] = (),
        confidence: float = 1.0,
        expires_days: int | None = None,
        request_id: str = "",
    ) -> MemoryRecord:
        normalized_scope = _scope(scope)
        normalized_kind = _kind(kind)
        scope_id, subject_id = self._write_scope(identity, normalized_scope)
        normalized_topic = _bounded_text(topic, 120, "memory topic")
        normalized_content = _bounded_text(content, 1000, "memory content")
        normalized_tags = _normalize_tags(tags)
        if _SENSITIVE_PATTERN.search(
            " ".join((normalized_topic, normalized_content, *normalized_tags))
        ):
            raise MemoryContentError("memory content contains sensitive data")
        if not math.isfinite(confidence) or not 0 <= confidence <= 1:
            raise MemoryContentError("memory confidence must be between 0 and 1")
        now = _utc(self._clock())
        expiry = None
        if expires_days is not None:
            if expires_days < 1 or expires_days > 3650:
                raise MemoryContentError(
                    "memory expiry must be between 1 and 3650 days"
                )
            expiry = now + timedelta(days=expires_days)
        record = MemoryRecord(
            memory_id=f"memory-{uuid.uuid4().hex}",
            scope=normalized_scope,
            scope_id=scope_id,
            subject_id=subject_id,
            topic=normalized_topic,
            kind=normalized_kind,
            content=normalized_content,
            tags=normalized_tags,
            confidence=confidence,
            created_at=now,
            updated_at=now,
            expires_at=expiry,
            source_request_id=request_id,
        )
        previous_ids = self._store.save(record)
        if previous_ids:
            record = replace(record, supersedes_id=previous_ids[0])
        return record

    def recall(
        self,
        identity: Identity,
        query: str = "",
        *,
        limit: int = 5,
        include_unmatched: bool = False,
    ) -> tuple[MemoryRecord, ...]:
        scopes = self._read_scopes(identity)
        records = self._store.active_for_scopes(
            scopes,
            now=_utc(self._clock()),
            limit=500,
        )
        terms = _terms(query)
        ranked: list[tuple[float, MemoryRecord]] = []
        for record in records:
            score = _score(record, terms)
            if score > 0 or include_unmatched or not terms:
                ranked.append((score, record))
        ranked.sort(
            key=lambda item: (
                -item[0],
                -item[1].confidence,
                -item[1].updated_at.timestamp(),
                item[1].memory_id,
            )
        )
        bounded_limit = max(1, min(limit, 20))
        return tuple(record for _, record in ranked[:bounded_limit])

    def forget(self, identity: Identity, memory_id: str) -> bool:
        record = self._store.get(memory_id)
        if record is None or record.status is not MemoryStatus.ACTIVE:
            return False
        if not self._can_read(identity, record):
            raise MemoryAccessError("memory scope denied")
        return self._store.forget(record.memory_id, updated_at=_utc(self._clock()))

    def can_read(self, identity: Identity, record: MemoryRecord) -> bool:
        return self._can_read(identity, record)

    def _read_scopes(self, identity: Identity) -> tuple[tuple[MemoryScope, str], ...]:
        scopes: list[tuple[MemoryScope, str]] = []
        user_id = normalize_id(identity.user_id)
        group_id = normalize_id(identity.group_id)
        if group_id:
            scopes.append((MemoryScope.GROUP, group_id))
        else:
            if user_id:
                scopes.append((MemoryScope.USER, user_id))
            if identity.role is UserRole.OWNER:
                scopes.append((MemoryScope.BOT, "bot"))
        return tuple(scopes)

    def _write_scope(
        self,
        identity: Identity,
        scope: MemoryScope,
    ) -> tuple[str, str]:
        if scope is MemoryScope.USER:
            user_id = normalize_id(identity.user_id)
            if not user_id:
                raise MemoryAccessError("user memory requires an actor")
            if normalize_id(identity.group_id):
                raise MemoryAccessError("user memory requires a private chat")
            return user_id, user_id
        if scope is MemoryScope.GROUP:
            group_id = normalize_id(identity.group_id)
            if not group_id:
                raise MemoryAccessError("group memory requires a group")
            if identity.role not in {UserRole.OWNER, UserRole.GROUP_ADMIN}:
                raise MemoryAccessError("group memory requires an administrator")
            return group_id, group_id
        if identity.role is not UserRole.OWNER:
            raise MemoryAccessError("bot memory requires the owner")
        if normalize_id(identity.group_id):
            raise MemoryAccessError("bot memory requires a private chat")
        return "bot", "bot"

    @staticmethod
    def _can_read(identity: Identity, record: MemoryRecord) -> bool:
        if record.scope is MemoryScope.USER:
            return (
                not normalize_id(identity.group_id)
                and normalize_id(identity.user_id) == record.scope_id
            )
        if record.scope is MemoryScope.GROUP:
            return (
                bool(identity.group_id)
                and normalize_id(identity.group_id) == record.scope_id
            )
        return identity.role is UserRole.OWNER and not normalize_id(identity.group_id)


def _scope(value: MemoryScope | str) -> MemoryScope:
    try:
        return (
            value
            if isinstance(value, MemoryScope)
            else MemoryScope(value.strip().lower())
        )
    except (AttributeError, ValueError) as error:
        raise MemoryContentError("unknown memory scope") from error


def _kind(value: MemoryKind | str) -> MemoryKind:
    try:
        return (
            value
            if isinstance(value, MemoryKind)
            else MemoryKind(value.strip().lower())
        )
    except (AttributeError, ValueError) as error:
        raise MemoryContentError("unknown memory kind") from error


def _bounded_text(value: str, maximum: int, label: str) -> str:
    if not isinstance(value, str):
        raise MemoryContentError(f"{label} must be text")
    normalized = " ".join(value.split())
    if not normalized:
        raise MemoryContentError(f"{label} must not be empty")
    if len(normalized) > maximum:
        raise MemoryContentError(f"{label} exceeds its bound")
    return normalized


def _normalize_tags(tags: Iterable[str]) -> tuple[str, ...]:
    normalized: list[str] = []
    for tag in tags:
        if not isinstance(tag, str):
            raise MemoryContentError("memory tags must be text")
        value = " ".join(tag.split()).lower()
        if value and value not in normalized:
            if len(value) > 40:
                raise MemoryContentError("memory tag exceeds its bound")
            normalized.append(value)
    if len(normalized) > 10:
        raise MemoryContentError("too many memory tags")
    return tuple(normalized)


def _terms(value: str) -> frozenset[str]:
    terms: set[str] = set()
    for chunk in _TERM_PATTERN.findall(value.lower()):
        if re.fullmatch(r"[\u4e00-\u9fff]+", chunk):
            terms.add(chunk)
            terms.update(chunk[index : index + 2] for index in range(len(chunk) - 1))
        else:
            terms.add(chunk)
    return frozenset(term for term in terms if term)


def _score(record: MemoryRecord, terms: frozenset[str]) -> float:
    if not terms:
        return 1.0
    topic = record.topic.lower()
    content = record.content.lower()
    tags = " ".join(record.tags)
    score = 0.0
    for term in terms:
        if term in topic:
            score += 5
        if term in content:
            score += 3
        if term in tags:
            score += 1
    if score:
        score += record.confidence
    return score


def _utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)
