"""In-memory confirmation, quota, idempotency, and audit coordination."""

from __future__ import annotations

import hashlib
import json
import secrets
import uuid
from collections.abc import Callable, Mapping
from datetime import UTC, date, datetime

from ...domain.identity import Identity, normalize_id
from .models import (
    AuditEvent,
    GuardrailCode,
    GuardrailDecision,
    GuardrailSettings,
    PendingConfirmation,
    confirmation_expiry,
)


class GuardrailManager:
    """Coordinate safety gates without retaining raw chat messages."""

    def __init__(
        self,
        settings: GuardrailSettings | None = None,
        *,
        clock: Callable[[], datetime] | None = None,
        token_factory: Callable[[], str] | None = None,
        protected_target_ids: tuple[str, ...] = (),
        audit_sink: Callable[[AuditEvent], None] | None = None,
    ) -> None:
        self.settings = settings or GuardrailSettings()
        self._clock = clock or (lambda: datetime.now(UTC))
        self._token_factory = token_factory or (lambda: secrets.token_urlsafe(12))
        self._protected_target_ids = frozenset(
            normalized
            for item in protected_target_ids
            if (normalized := normalize_id(item))
        )
        self._audit_sink = audit_sink
        self._pending: dict[str, PendingConfirmation] = {}
        self._consumed_tokens: set[str] = set()
        self._daily_counts: dict[tuple[date, str, str, str], int] = {}
        self._in_flight = 0
        self._audit: list[AuditEvent] = []
        self._completed: dict[str, object] = {}

    def begin(
        self,
        tool_name: str,
        arguments: Mapping[str, object],
        identity: Identity,
        *,
        request_id: str = "",
        confirmation_token: str = "",
    ) -> GuardrailDecision:
        """Reserve an execution or return a confirmation/limit decision."""

        normalized_tool = tool_name.strip().lower()
        normalized_request = request_id.strip()
        idempotency_key = self._idempotency_key(
            normalized_request, normalized_tool, arguments
        )
        if idempotency_key and idempotency_key in self._completed:
            return GuardrailDecision(
                GuardrailCode.IDEMPOTENT_REPLAY,
                cached_result=self._completed[idempotency_key],
            )

        target_user_id = self._target_user_id(arguments)
        if target_user_id and (
            target_user_id == normalize_id(identity.user_id)
            or target_user_id in self._protected_target_ids
        ):
            self._record(
                identity,
                normalized_tool,
                "target_protected",
                request_id=normalized_request,
                target_user_id=target_user_id,
            )
            return GuardrailDecision(GuardrailCode.TARGET_PROTECTED)

        quota_key = self._quota_key(identity, normalized_tool)
        if self._daily_counts.get(quota_key, 0) >= self._daily_limit(normalized_tool):
            self._record(
                identity,
                normalized_tool,
                "quota_exceeded",
                request_id=normalized_request,
                target_user_id=target_user_id,
            )
            return GuardrailDecision(GuardrailCode.QUOTA_EXCEEDED)
        if self._in_flight >= self.settings.max_concurrent_actions:
            self._record(
                identity,
                normalized_tool,
                "concurrency_limit",
                request_id=normalized_request,
                target_user_id=target_user_id,
            )
            return GuardrailDecision(GuardrailCode.CONCURRENCY_LIMIT)

        if (
            normalized_tool in self.settings.confirmation_tools
            and not confirmation_token
        ):
            created_at = self._now()
            pending = PendingConfirmation(
                token=self._new_token(),
                tool_name=normalized_tool,
                arguments=arguments,
                actor_id=normalize_id(identity.user_id),
                group_id=normalize_id(identity.group_id),
                request_id=normalized_request,
                created_at=created_at,
                expires_at=confirmation_expiry(
                    created_at, self.settings.confirmation_ttl_seconds
                ),
            )
            self._pending[pending.token] = pending
            self._record(
                identity,
                normalized_tool,
                "confirmation_requested",
                request_id=normalized_request,
                target_user_id=target_user_id,
            )
            return GuardrailDecision(
                GuardrailCode.CONFIRMATION_REQUIRED,
                token=pending.token,
                pending=pending,
            )

        if confirmation_token:
            confirmation = self._pending.get(confirmation_token.strip())
            if confirmation is None:
                outcome = (
                    "confirmation_replayed"
                    if confirmation_token.strip() in self._consumed_tokens
                    else "invalid_confirmation"
                )
                self._record(
                    identity,
                    normalized_tool,
                    outcome,
                    request_id=normalized_request,
                    target_user_id=target_user_id,
                )
                return GuardrailDecision(
                    GuardrailCode.CONFIRMATION_REPLAYED
                    if outcome == "confirmation_replayed"
                    else GuardrailCode.INVALID_CONFIRMATION
                )
            if self._now() >= confirmation.expires_at:
                self._pending.pop(confirmation.token, None)
                self._record(
                    identity,
                    normalized_tool,
                    "confirmation_expired",
                    request_id=normalized_request,
                    target_user_id=target_user_id,
                )
                return GuardrailDecision(GuardrailCode.CONFIRMATION_EXPIRED)
            if not self._matches_confirmation(
                confirmation,
                normalized_tool,
                arguments,
                identity,
            ):
                self._record(
                    identity,
                    normalized_tool,
                    "invalid_confirmation",
                    request_id=normalized_request,
                    target_user_id=target_user_id,
                )
                return GuardrailDecision(GuardrailCode.INVALID_CONFIRMATION)
            self._pending.pop(confirmation.token, None)
            self._consumed_tokens.add(confirmation.token)
            self._record(
                identity,
                normalized_tool,
                "confirmation_accepted",
                request_id=normalized_request,
                target_user_id=target_user_id,
            )

        self._in_flight += 1
        self._daily_counts[quota_key] = self._daily_counts.get(quota_key, 0) + 1
        return GuardrailDecision(GuardrailCode.ALLOW)

    def complete(
        self,
        tool_name: str,
        arguments: Mapping[str, object],
        identity: Identity,
        *,
        request_id: str = "",
        result: object | None = None,
        outcome: str = "success",
    ) -> None:
        """Release concurrency and retain a sanitized idempotent result."""

        self._in_flight = max(0, self._in_flight - 1)
        normalized_tool = tool_name.strip().lower()
        key = self._idempotency_key(request_id.strip(), normalized_tool, arguments)
        if key and result is not None:
            self._completed[key] = result
        self._record(
            identity,
            normalized_tool,
            outcome,
            request_id=request_id,
            target_user_id=self._target_user_id(arguments),
        )

    def pending(self, token: str) -> PendingConfirmation | None:
        """Return a pending proposal for the confirmation adapter."""

        value = self._pending.get(token.strip())
        if value is None:
            return None
        if self._now() >= value.expires_at:
            self._pending.pop(value.token, None)
            return None
        return value

    def was_consumed(self, token: str) -> bool:
        """Tell adapters whether a missing token was already used once."""

        return token.strip() in self._consumed_tokens

    def audit_events(self) -> tuple[AuditEvent, ...]:
        return tuple(self._audit)

    @property
    def in_flight(self) -> int:
        return self._in_flight

    def _matches_confirmation(
        self,
        pending: PendingConfirmation,
        tool_name: str,
        arguments: Mapping[str, object],
        identity: Identity,
    ) -> bool:
        return (
            pending.tool_name == tool_name
            and self._canonical_arguments(pending.arguments)
            == self._canonical_arguments(arguments)
            and pending.actor_id == normalize_id(identity.user_id)
            and pending.group_id == normalize_id(identity.group_id)
        )

    def _quota_key(
        self, identity: Identity, tool_name: str
    ) -> tuple[date, str, str, str]:
        now = self._now().date()
        return (
            now,
            normalize_id(identity.user_id),
            normalize_id(identity.group_id),
            tool_name,
        )

    def _daily_limit(self, tool_name: str) -> int:
        if tool_name == "group.kick_member":
            return self.settings.daily_kick_limit
        return self.settings.daily_action_limit

    def _record(
        self,
        identity: Identity,
        tool_name: str,
        outcome: str,
        *,
        request_id: str,
        target_user_id: str,
    ) -> None:
        event = AuditEvent(
            event_id=uuid.uuid4().hex,
            timestamp=self._now(),
            actor_id=normalize_id(identity.user_id),
            group_id=normalize_id(identity.group_id),
            tool_name=tool_name,
            outcome=outcome,
            request_id=request_id,
            target_user_id=target_user_id,
        )
        self._audit.append(event)
        if self._audit_sink is not None:
            self._audit_sink(event)

    def _now(self) -> datetime:
        value = self._clock()
        if value.tzinfo is None:
            return value.replace(tzinfo=UTC)
        return value.astimezone(UTC)

    def _new_token(self) -> str:
        token = self._token_factory().strip()
        if not token:
            raise ValueError("token_factory returned an empty token")
        return token

    @staticmethod
    def _target_user_id(arguments: Mapping[str, object]) -> str:
        return normalize_id(arguments.get("user_id"))

    @staticmethod
    def _canonical_arguments(arguments: Mapping[str, object]) -> str:
        return json.dumps(
            dict(arguments), sort_keys=True, separators=(",", ":"), default=str
        )

    @classmethod
    def _idempotency_key(
        cls,
        request_id: str,
        tool_name: str,
        arguments: Mapping[str, object],
    ) -> str:
        if not request_id:
            return ""
        raw = "|".join((request_id, tool_name, cls._canonical_arguments(arguments)))
        return hashlib.sha256(raw.encode("utf-8")).hexdigest()
