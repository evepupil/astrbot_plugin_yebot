"""Atomic JSON index and content-addressed sticker file storage."""

from __future__ import annotations

import hashlib
import json
import os
import re
import tempfile
from collections.abc import Iterable
from contextlib import suppress
from dataclasses import replace
from datetime import datetime
from pathlib import Path
from typing import NamedTuple

from .models import StickerKind, StickerRecord


class StickerAddResult(NamedTuple):
    record: StickerRecord
    duplicate: bool


class StickerStore:
    """Keep sticker metadata restart-safe and image files deduplicated."""

    def __init__(self, path: str | Path, *, max_bytes: int = 10_000_000) -> None:
        self.root = Path(path).resolve()
        self.index_path = self.root / "index.json"
        self.files_path = self.root / "files"
        self.max_bytes = max_bytes
        self._records: dict[str, StickerRecord] = {}
        self._load()

    def add(
        self,
        data: bytes,
        *,
        media_type: str,
        meaning: str,
        tags: Iterable[str],
        group_id: str,
        source_message_id: str,
        source_user_id: str,
        asset_kind: StickerKind = StickerKind.LEGACY,
        confidence: float = 0.0,
        suffix: str = ".jpg",
    ) -> StickerAddResult:
        if not data:
            raise ValueError("sticker image is empty")
        if len(data) > self.max_bytes:
            raise ValueError("sticker image is too large")
        normalized_group = group_id.strip()
        if not normalized_group:
            raise ValueError("sticker collection requires a group")
        digest = hashlib.sha256(data).hexdigest()
        existing = next(
            (record for record in self._records.values() if record.digest == digest),
            None,
        )
        if existing is not None:
            return StickerAddResult(existing, True)
        sticker_id = f"sticker-{digest[:16]}"

        safe_suffix = _safe_suffix(suffix)
        relative_path = f"files/{digest}{safe_suffix}"
        target = self.root / relative_path
        target.parent.mkdir(parents=True, exist_ok=True)
        if not target.exists():
            _write_bytes_atomic(target, data)
        record = StickerRecord(
            sticker_id=sticker_id,
            digest=digest,
            relative_path=relative_path,
            media_type=media_type,
            meaning=meaning,
            tags=tuple(tags),
            group_id=normalized_group,
            source_message_id=source_message_id,
            source_user_id=source_user_id,
            asset_kind=asset_kind,
            confidence=confidence,
        )
        self._records[record.sticker_id] = record
        self._flush()
        return StickerAddResult(record, False)

    def get(self, sticker_id: str, *, group_id: str = "") -> StickerRecord | None:
        """Return a sticker from the shared library.

        ``group_id`` remains accepted for compatibility with older callers, but
        it is no longer an access boundary.
        """

        del group_id
        return self._records.get(sticker_id.strip())

    def search(
        self,
        query: str,
        *,
        group_id: str,
        limit: int = 5,
    ) -> tuple[StickerRecord, ...]:
        del group_id
        bounded_limit = max(1, min(limit, 20))
        terms = _terms(query)
        candidates: list[tuple[int, StickerRecord]] = []
        for record in self._records.values():
            haystack = " ".join((record.meaning, *record.tags)).lower()
            score = sum(
                2 if term == haystack else 1 for term in terms if term in haystack
            )
            if not terms:
                score = 1
            if score:
                candidates.append((score, record))
        candidates.sort(key=lambda item: (-item[0], -item[1].created_at.timestamp()))
        return tuple(record for _, record in candidates[:bounded_limit])

    def mark_used(
        self,
        sticker_id: str,
        *,
        group_id: str = "",
        sent_message_id: str = "",
    ) -> StickerRecord | None:
        record = self.get(sticker_id, group_id=group_id)
        if record is None:
            return None
        updated = replace(
            record,
            use_count=record.use_count + 1,
            sent_message_ids=_append_message_id(
                record.sent_message_ids,
                sent_message_id,
            ),
        )
        self._records[updated.sticker_id] = updated
        self._flush()
        return updated

    def find_by_sent_message_id(self, message_id: str) -> StickerRecord | None:
        """Find a sticker sent by YeBot using the originating QQ message ID."""

        normalized = message_id.strip()
        if not normalized:
            return None
        matches = [
            record
            for record in self._records.values()
            if normalized in record.sent_message_ids
        ]
        return matches[0] if len(matches) == 1 else None

    def attach_native(
        self,
        sticker_id: str,
        *,
        emoji_id: str,
        emoji_package_id: int,
        key: str,
        res_id: str = "",
        md5: str = "",
        summary: str = "",
        native_url: str = "",
    ) -> StickerRecord | None:
        """Persist the QQ-native identifiers returned by NapCat."""

        record = self._records.get(sticker_id.strip())
        if record is None:
            return None
        updated = StickerRecord(
            sticker_id=record.sticker_id,
            digest=record.digest,
            relative_path=record.relative_path,
            media_type=record.media_type,
            meaning=record.meaning,
            tags=record.tags,
            group_id=record.group_id,
            source_message_id=record.source_message_id,
            source_user_id=record.source_user_id,
            asset_kind=record.asset_kind,
            confidence=record.confidence,
            created_at=record.created_at,
            use_count=record.use_count,
            emoji_id=emoji_id,
            emoji_package_id=emoji_package_id,
            key=key,
            res_id=res_id,
            md5=md5,
            summary=summary,
            native_url=native_url,
            sent_message_ids=record.sent_message_ids,
        )
        self._records[updated.sticker_id] = updated
        self._flush()
        return updated

    def delete(self, sticker_id: str) -> StickerRecord | None:
        """Remove one record and its local source file from YeBot's library."""

        record = self._records.pop(sticker_id.strip(), None)
        if record is None:
            return None
        self._flush()
        path = (self.root / record.relative_path).resolve()
        try:
            path.relative_to(self.root)
        except ValueError:
            return record
        # The index is authoritative, so a stale orphan cannot be sent.
        with suppress(OSError):
            path.unlink(missing_ok=True)
        return record

    def file_path(self, record: StickerRecord) -> Path:
        path = (self.root / record.relative_path).resolve()
        try:
            path.relative_to(self.root)
        except ValueError as error:
            raise ValueError("sticker path escapes store root") from error
        if not path.is_file():
            raise FileNotFoundError("sticker file not found")
        return path

    def list_for(self, group_id: str = "") -> tuple[StickerRecord, ...]:
        """Return the shared library in newest-first order.

        The argument is retained for callers written before the library became
        global. It is intentionally ignored.
        """

        del group_id
        return tuple(
            sorted(
                self._records.values(),
                key=lambda record: record.created_at,
                reverse=True,
            )
        )

    def list_recent(self, limit: int = 20) -> tuple[StickerRecord, ...]:
        """Return the newest records from the shared library."""

        bounded_limit = max(1, min(limit, 20))
        return self.list_for()[:bounded_limit]

    def _load(self) -> None:
        if not self.index_path.exists():
            return
        try:
            payload = json.loads(self.index_path.read_text(encoding="utf-8"))
            records = payload.get("stickers", []) if isinstance(payload, dict) else []
            if not isinstance(records, list):
                return
            for value in records:
                record = _decode(value)
                if record is not None:
                    self._records[record.sticker_id] = record
                    _make_record_readable(self.root, record.relative_path)
        except (OSError, ValueError, TypeError, KeyError):
            self._records = {}

    def _flush(self) -> None:
        self.root.mkdir(parents=True, exist_ok=True)
        payload = {
            "version": 2,
            "stickers": [_encode(record) for record in self.list_all()],
        }
        fd, temporary = tempfile.mkstemp(
            prefix=f".{self.index_path.name}.", suffix=".tmp", dir=self.root
        )
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as stream:
                json.dump(payload, stream, ensure_ascii=False, separators=(",", ":"))
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary, self.index_path)
            _make_readable(self.index_path)
        finally:
            if os.path.exists(temporary):
                os.unlink(temporary)

    def list_all(self) -> tuple[StickerRecord, ...]:
        return tuple(
            sorted(self._records.values(), key=lambda record: record.sticker_id)
        )


def _encode(record: StickerRecord) -> dict[str, object]:
    return {
        "sticker_id": record.sticker_id,
        "digest": record.digest,
        "relative_path": record.relative_path,
        "media_type": record.media_type,
        "meaning": record.meaning,
        "tags": list(record.tags),
        "group_id": record.group_id,
        "source_message_id": record.source_message_id,
        "source_user_id": record.source_user_id,
        "asset_kind": record.asset_kind.value,
        "confidence": record.confidence,
        "created_at": record.created_at.isoformat(),
        "use_count": record.use_count,
        "emoji_id": record.emoji_id,
        "emoji_package_id": record.emoji_package_id,
        "key": record.key,
        "res_id": record.res_id,
        "md5": record.md5,
        "summary": record.summary,
        "native_url": record.native_url,
        "sent_message_ids": list(record.sent_message_ids),
    }


def _decode(value: object) -> StickerRecord | None:
    if not isinstance(value, dict):
        return None
    tags = value.get("tags", [])
    if not isinstance(tags, list):
        return None
    sent_message_ids = value.get("sent_message_ids", [])
    if not isinstance(sent_message_ids, list):
        sent_message_ids = []
    try:
        return StickerRecord(
            sticker_id=str(value["sticker_id"]),
            digest=str(value["digest"]),
            relative_path=str(value["relative_path"]),
            media_type=str(value["media_type"]),
            meaning=str(value["meaning"]),
            tags=tuple(str(item) for item in tags),
            group_id=str(value["group_id"]),
            source_message_id=str(value.get("source_message_id", "")),
            source_user_id=str(value.get("source_user_id", "")),
            asset_kind=StickerKind(str(value.get("asset_kind", StickerKind.LEGACY))),
            confidence=float(value.get("confidence", 0.0)),
            created_at=datetime.fromisoformat(str(value["created_at"])),
            use_count=int(value.get("use_count", 0)),
            emoji_id=str(value.get("emoji_id", "")),
            emoji_package_id=int(value.get("emoji_package_id", 0)),
            key=str(value.get("key", "")),
            res_id=str(value.get("res_id", "")),
            md5=str(value.get("md5", "")),
            summary=str(value.get("summary", "")),
            native_url=str(value.get("native_url", "")),
            sent_message_ids=tuple(
                str(item)
                for item in sent_message_ids
                if isinstance(item, (str, int)) and not isinstance(item, bool)
            ),
        )
    except (KeyError, TypeError, ValueError, OverflowError):
        return None


def _write_bytes_atomic(path: Path, data: bytes) -> None:
    fd, temporary = tempfile.mkstemp(
        prefix=f".{path.name}.", suffix=".tmp", dir=path.parent
    )
    try:
        with os.fdopen(fd, "wb") as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
        _make_readable(path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def _append_message_id(values: tuple[str, ...], message_id: str) -> tuple[str, ...]:
    normalized = message_id.strip()[:128]
    if not normalized or normalized in values:
        return values
    return (*values, normalized)[-16:]


def _safe_suffix(value: str) -> str:
    suffix = value.strip().lower()
    if not suffix.startswith(".") or not re.fullmatch(r"\.[a-z0-9]{1,5}", suffix):
        return ".jpg"
    return suffix


def _terms(value: str) -> tuple[str, ...]:
    return tuple(
        term for term in re.findall(r"[\w\u4e00-\u9fff]+", value.lower()) if term
    )


def _make_readable(path: Path) -> None:
    """Allow the NapCat uid to read shared sticker files on Linux."""

    try:
        mode = path.stat().st_mode
        path.chmod(mode | 0o444)
    except OSError:
        # Windows and read-only mounts can reject chmod; the normal write path
        # still works there and NapCat will report a useful action error.
        return


def _make_record_readable(root: Path, relative_path: str) -> None:
    """Repair permissions only for a decoded path inside the store root."""

    path = (root / relative_path).resolve()
    try:
        path.relative_to(root)
    except ValueError:
        return
    _make_readable(path)
