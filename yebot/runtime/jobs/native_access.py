"""Compatibility access rules for AstrBot's native future-task tool."""

from __future__ import annotations

import re
from collections.abc import Mapping
from typing import Any

_GROUP_SESSION_PATTERN = re.compile(
    r"^(?P<platform>.+):(?P<message_type>[^:]+):(?P<group_id>\d+)$",
    re.IGNORECASE,
)


def _group_scope(session: object) -> tuple[str, str] | None:
    if not isinstance(session, str):
        return None
    match = _GROUP_SESSION_PATTERN.fullmatch(session.strip())
    if match is None:
        return None
    message_type = match.group("message_type").replace("_", "").lower()
    if message_type != "groupmessage":
        return None
    platform = match.group("platform").strip().lower()
    group_id = match.group("group_id").strip()
    if not platform or not group_id:
        return None
    return platform, group_id


def group_scope_from_session(session: object) -> tuple[str, str] | None:
    """Return the platform and group ID encoded in a group message session."""

    return _group_scope(session)


def _payload(job: Any) -> Mapping[str, object] | None:
    payload = getattr(job, "payload", None)
    return payload if isinstance(payload, Mapping) else None


def _text_field(payload: Mapping[str, object] | None, key: str) -> str:
    if payload is None:
        return ""
    value = payload.get(key)
    return str(value).strip() if value is not None else ""


def native_cron_job_accessible(
    job: Any,
    current_umo: str,
    current_sender_id: str,
) -> bool:
    """Return whether a caller can manage one native AstrBot cron job.

    Group jobs are shared by callers on the same platform and group. Private
    jobs, API-created jobs without a group session, and malformed sessions keep
    AstrBot's original owner-only behavior.
    """

    payload = _payload(job)
    job_session = _text_field(payload, "session")
    current_session = current_umo.strip()
    job_scope = _group_scope(job_session)
    current_scope = _group_scope(current_session)
    if job_scope is not None and current_scope is not None:
        return job_scope == current_scope
    return (
        job_session == current_session
        and _text_field(payload, "sender_id") == current_sender_id.strip()
    )


def install_native_cron_group_sharing() -> bool:
    """Patch AstrBot's built-in future-task predicate for this plugin runtime."""

    try:
        from astrbot.core.tools import cron_tools  # type: ignore[import-not-found]
    except ImportError:
        return False

    if getattr(cron_tools, "_yebot_group_shared_installed", False):
        return True
    predicate = getattr(cron_tools, "_job_belongs_to_current_sender", None)
    if not callable(predicate):
        return False

    def group_shared_predicate(
        job: Any,
        current_umo: str,
        current_sender_id: str,
    ) -> bool:
        return native_cron_job_accessible(job, current_umo, current_sender_id)

    cron_tools._job_belongs_to_current_sender = group_shared_predicate
    cron_tools._yebot_group_shared_installed = True
    return True


__all__ = [
    "group_scope_from_session",
    "install_native_cron_group_sharing",
    "native_cron_job_accessible",
]
