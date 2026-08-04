"""Resolve QQ group members from explicit and conversational references."""

from __future__ import annotations

import inspect
import re
from collections.abc import Awaitable, Mapping
from typing import Protocol

from ...domain.identity import extract_mentioned_user_ids, normalize_id
from ..replies import extract_reply_references
from .models import (
    TargetCandidate,
    TargetResolution,
    TargetSource,
    TargetStatus,
)

_QQ_ID_PATTERN = re.compile(r"(?<!\d)(\d{5,12})(?!\d)")
_RECENT_REFERENCE_PATTERN = re.compile(
    r"(?:他|她|它|那个人|这人|刚才(?:那)?(?:个)?人|刚刚(?:那)?(?:个)?人|"
    r"上面(?:那)?(?:个)?人|前面(?:那)?(?:个)?人|最后说话的|最近说话的)"
)
_SELF_REFERENCE_PATTERN = re.compile(r"^(?:我|我自己|本人)$")


class ActionClient(Protocol):
    """Minimal OneBot API surface used for candidate lookup."""

    def call_action(
        self, action: str, **params: object
    ) -> Awaitable[object] | object: ...


class TargetResolver:
    """Use one consistent precedence order for every member-targeting tool."""

    def __init__(self, action_client: ActionClient | None) -> None:
        self._action_client = action_client

    async def resolve(
        self,
        event: object,
        *,
        target_hint: str = "",
        actor_id: str = "",
        bot_id: str = "",
        group_id: str = "",
    ) -> TargetResolution:
        """Resolve one target without making a mutating OneBot call.

        Explicit message structure always wins over language inference. Name and
        numeric matches are verified against the current group member list;
        pronouns can only select a recent non-actor, non-bot speaker.
        """

        raw_event = getattr(getattr(event, "message_obj", None), "raw_message", None)
        event_group_id = ""
        if isinstance(raw_event, Mapping):
            mentioned = extract_mentioned_user_ids(raw_event, excluded_ids=(bot_id,))
            if len(mentioned) == 1:
                return TargetResolution(
                    TargetStatus.RESOLVED,
                    user_id=mentioned[0],
                    source=TargetSource.MENTION,
                )
            if len(mentioned) > 1:
                return _ambiguous_ids(mentioned)
            event_group_id = normalize_id(raw_event.get("group_id"))

        reply_targets = await self._reply_targets(event)
        if len(reply_targets) == 1:
            return TargetResolution(
                TargetStatus.RESOLVED,
                user_id=reply_targets[0].user_id,
                source=TargetSource.REPLY,
                candidates=tuple(reply_targets),
            )
        if len(reply_targets) > 1:
            return TargetResolution(
                TargetStatus.AMBIGUOUS,
                candidates=tuple(reply_targets),
            )

        hint = target_hint.strip()
        normalized_actor = normalize_id(actor_id)
        if _SELF_REFERENCE_PATTERN.fullmatch(hint):
            if normalized_actor:
                return TargetResolution(
                    TargetStatus.RESOLVED,
                    user_id=normalized_actor,
                    source=TargetSource.SELF,
                )
            return TargetResolution(TargetStatus.UNRESOLVED)

        group_id = normalize_id(group_id) or event_group_id
        if not group_id or self._action_client is None:
            return TargetResolution(TargetStatus.UNRESOLVED)

        members = await self._members(group_id)
        numeric = _match_qq_id(hint, members)
        if numeric is not None:
            return TargetResolution(
                TargetStatus.RESOLVED,
                user_id=numeric.user_id,
                source=TargetSource.QQ_ID,
                candidates=(numeric,),
            )

        named = _match_name(hint, members)
        if len(named) == 1:
            return TargetResolution(
                TargetStatus.RESOLVED,
                user_id=named[0].user_id,
                source=TargetSource.NAME,
                candidates=tuple(named),
            )
        if len(named) > 1:
            return TargetResolution(TargetStatus.AMBIGUOUS, candidates=tuple(named))

        if _RECENT_REFERENCE_PATTERN.search(hint):
            recent = await self._recent_speaker(
                group_id,
                actor_id=normalized_actor,
                bot_id=normalize_id(bot_id),
            )
            if recent is not None:
                return TargetResolution(
                    TargetStatus.RESOLVED,
                    user_id=recent.user_id,
                    source=TargetSource.RECENT_SPEAKER,
                    candidates=(recent,),
                )

        return TargetResolution(TargetStatus.UNRESOLVED)

    async def _reply_targets(self, event: object) -> list[TargetCandidate]:
        if self._action_client is None:
            return []
        targets: list[TargetCandidate] = []
        for reference in extract_reply_references(event):
            response = await _call_action(
                self._action_client,
                "get_msg",
                message_id=_message_id_value(reference.message_id),
            )
            candidate = _message_candidate(response)
            if candidate is not None and candidate.user_id not in {
                item.user_id for item in targets
            }:
                targets.append(candidate)
        return targets

    async def _members(self, group_id: str) -> list[TargetCandidate]:
        assert self._action_client is not None
        response = await _call_action(
            self._action_client,
            "get_group_member_list",
            group_id=int(group_id),
        )
        return _member_candidates(response)

    async def _recent_speaker(
        self,
        group_id: str,
        *,
        actor_id: str,
        bot_id: str,
    ) -> TargetCandidate | None:
        assert self._action_client is not None
        response = await _call_action(
            self._action_client,
            "get_group_msg_history",
            group_id=int(group_id),
            count=40,
        )
        excluded = {actor_id, bot_id}
        for candidate in _recent_candidates(response):
            if candidate.user_id and candidate.user_id not in excluded:
                return candidate
        return None


async def _call_action(
    client: ActionClient,
    action: str,
    **params: object,
) -> object:
    try:
        result = client.call_action(action, **params)
        return await result if inspect.isawaitable(result) else result
    except Exception:  # noqa: BLE001 - lookup failures must not invoke writes
        return None


def _ambiguous_ids(values: tuple[str, ...]) -> TargetResolution:
    return TargetResolution(
        TargetStatus.AMBIGUOUS,
        candidates=tuple(TargetCandidate(user_id=value) for value in values),
    )


def _member_candidates(response: object) -> list[TargetCandidate]:
    data = _unwrap_data(response)
    raw_members: object = data
    if isinstance(data, Mapping):
        raw_members = data.get("members", data.get("data", data))
    if not isinstance(raw_members, list):
        return []
    return _candidates_from_records(raw_members)


def _recent_candidates(response: object) -> list[TargetCandidate]:
    data = _unwrap_data(response)
    raw_messages: object = data
    if isinstance(data, Mapping):
        raw_messages = data.get("messages", data.get("message", data))
    if not isinstance(raw_messages, list):
        return []
    ordered = sorted(
        (item for item in raw_messages if isinstance(item, Mapping)),
        key=lambda item: _as_number(item.get("time")),
        reverse=True,
    )
    candidates: list[TargetCandidate] = []
    seen: set[str] = set()
    for message in ordered:
        sender = message.get("sender")
        candidate = _candidate_from_record(sender)
        if candidate is not None and candidate.user_id not in seen:
            candidates.append(candidate)
            seen.add(candidate.user_id)
    return candidates


def _message_candidate(response: object) -> TargetCandidate | None:
    data = _unwrap_data(response)
    if not isinstance(data, Mapping):
        return None
    sender = data.get("sender")
    candidate = _candidate_from_record(sender)
    if candidate is not None:
        return candidate
    return _candidate_from_record(data)


def _unwrap_data(response: object) -> object:
    if isinstance(response, Mapping):
        return response.get("data", response)
    return response


def _candidates_from_records(records: list[object]) -> list[TargetCandidate]:
    candidates: list[TargetCandidate] = []
    seen: set[str] = set()
    for record in records:
        candidate = _candidate_from_record(record)
        if candidate is not None and candidate.user_id not in seen:
            candidates.append(candidate)
            seen.add(candidate.user_id)
    return candidates


def _candidate_from_record(record: object) -> TargetCandidate | None:
    if not isinstance(record, Mapping):
        return None
    user_id = normalize_id(record.get("user_id"))
    if not user_id:
        return None
    return TargetCandidate(
        user_id=user_id,
        nickname=_safe_text(record.get("nickname")),
        card=_safe_text(record.get("card")),
        role=_safe_text(record.get("role")),
    )


def _match_qq_id(
    hint: str,
    members: list[TargetCandidate],
) -> TargetCandidate | None:
    ids = tuple(dict.fromkeys(_QQ_ID_PATTERN.findall(hint)))
    if len(ids) != 1:
        return None
    return next((member for member in members if member.user_id == ids[0]), None)


def _match_name(hint: str, members: list[TargetCandidate]) -> list[TargetCandidate]:
    normalized_hint = _normalized_text(hint)
    if len(normalized_hint) < 2:
        return []
    exact = [
        member
        for member in members
        if normalized_hint
        in {_normalized_text(member.card), _normalized_text(member.nickname)}
    ]
    if exact:
        return exact
    return [
        member
        for member in members
        if any(
            len(name) >= 2 and name in normalized_hint
            for name in (
                _normalized_text(member.card),
                _normalized_text(member.nickname),
            )
        )
    ]


def _normalized_text(value: object) -> str:
    if not isinstance(value, str):
        return ""
    return re.sub(r"\s+", "", value).strip().casefold()


def _safe_text(value: object) -> str:
    return value.strip()[:80] if isinstance(value, str) else ""


def _as_number(value: object) -> float:
    if isinstance(value, int | float) and not isinstance(value, bool):
        return float(value)
    return 0.0


def _message_id_value(value: str) -> str | int:
    return int(value) if value.isdecimal() else value
