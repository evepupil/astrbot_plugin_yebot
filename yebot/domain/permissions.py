"""Role-based capability authorization for tools."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from enum import StrEnum
from types import MappingProxyType
from typing import Final

from .identity import Identity, UserRole, normalize_id


class Capability(StrEnum):
    """Capabilities that a tool may request."""

    READ = "read"
    SEND_MESSAGE = "send_message"
    MANAGE_GROUP = "manage_group"
    MANAGE_BOT = "manage_bot"
    EXTERNAL_WRITE = "external_write"


class PermissionScope(StrEnum):
    """The resource scope a capability is allowed to touch."""

    GLOBAL = "global"
    CURRENT_GROUP = "current_group"


class PermissionDecisionCode(StrEnum):
    """Stable reasons returned to callers and audit code."""

    ALLOW = "allow"
    ROLE_DENIED = "role_denied"
    OUT_OF_SCOPE = "out_of_scope"
    GROUP_REQUIRED = "group_required"
    UNKNOWN_CAPABILITY = "unknown_capability"


@dataclass(frozen=True, slots=True)
class CapabilityPolicy:
    """Role and scope requirements for one capability."""

    allowed_roles: frozenset[UserRole]
    scope: PermissionScope


CAPABILITY_POLICIES: Final[Mapping[str, CapabilityPolicy]] = MappingProxyType(
    {
        Capability.READ: CapabilityPolicy(frozenset(UserRole), PermissionScope.GLOBAL),
        Capability.SEND_MESSAGE: CapabilityPolicy(
            frozenset(UserRole), PermissionScope.CURRENT_GROUP
        ),
        Capability.MANAGE_GROUP: CapabilityPolicy(
            frozenset({UserRole.OWNER, UserRole.GROUP_ADMIN}),
            PermissionScope.CURRENT_GROUP,
        ),
        Capability.MANAGE_BOT: CapabilityPolicy(
            frozenset({UserRole.OWNER}), PermissionScope.GLOBAL
        ),
        Capability.EXTERNAL_WRITE: CapabilityPolicy(
            frozenset({UserRole.OWNER}), PermissionScope.GLOBAL
        ),
    }
)


TOOL_PERMISSION_POLICIES: Final[Mapping[str, CapabilityPolicy]] = MappingProxyType(
    {
        "read": CAPABILITY_POLICIES[Capability.READ],
        "send_message": CAPABILITY_POLICIES[Capability.SEND_MESSAGE],
        "manage_group": CAPABILITY_POLICIES[Capability.MANAGE_GROUP],
        "manage_bot": CAPABILITY_POLICIES[Capability.MANAGE_BOT],
        "external_write": CAPABILITY_POLICIES[Capability.EXTERNAL_WRITE],
        "message.read": CapabilityPolicy(frozenset(UserRole), PermissionScope.GLOBAL),
        "message.send": CapabilityPolicy(
            frozenset(UserRole), PermissionScope.CURRENT_GROUP
        ),
        "message.recall": CapabilityPolicy(
            frozenset({UserRole.OWNER, UserRole.GROUP_ADMIN}),
            PermissionScope.CURRENT_GROUP,
        ),
        "message.forward_scene": CapabilityPolicy(
            frozenset({UserRole.OWNER}), PermissionScope.CURRENT_GROUP
        ),
        "group.member.read": CapabilityPolicy(
            frozenset(UserRole), PermissionScope.CURRENT_GROUP
        ),
        "group.member.kick": CapabilityPolicy(
            frozenset({UserRole.OWNER, UserRole.GROUP_ADMIN}),
            PermissionScope.CURRENT_GROUP,
        ),
        "group.member.mute": CapabilityPolicy(
            frozenset({UserRole.OWNER, UserRole.GROUP_ADMIN}),
            PermissionScope.CURRENT_GROUP,
        ),
        "group.member.edit": CapabilityPolicy(
            frozenset({UserRole.OWNER, UserRole.GROUP_ADMIN}),
            PermissionScope.CURRENT_GROUP,
        ),
        "bot.manage": CapabilityPolicy(
            frozenset({UserRole.OWNER}), PermissionScope.GLOBAL
        ),
        "external.write": CapabilityPolicy(
            frozenset({UserRole.OWNER}), PermissionScope.GLOBAL
        ),
        "job.reminder.create": CapabilityPolicy(
            frozenset(UserRole), PermissionScope.CURRENT_GROUP
        ),
        "job.reminder.read": CapabilityPolicy(
            frozenset(UserRole), PermissionScope.CURRENT_GROUP
        ),
        "job.reminder.manage": CapabilityPolicy(
            frozenset(UserRole), PermissionScope.CURRENT_GROUP
        ),
        "file.read": CapabilityPolicy(
            frozenset({UserRole.OWNER}), PermissionScope.GLOBAL
        ),
        "web.fetch": CapabilityPolicy(
            frozenset({UserRole.OWNER}), PermissionScope.GLOBAL
        ),
        "model.ratings.read": CapabilityPolicy(
            frozenset(UserRole), PermissionScope.GLOBAL
        ),
        "sticker.consider": CapabilityPolicy(
            frozenset(UserRole), PermissionScope.CURRENT_GROUP
        ),
        "sticker.search": CapabilityPolicy(
            frozenset(UserRole), PermissionScope.CURRENT_GROUP
        ),
        "sticker.send": CapabilityPolicy(
            frozenset(UserRole), PermissionScope.CURRENT_GROUP
        ),
        "memory.read": CapabilityPolicy(frozenset(UserRole), PermissionScope.GLOBAL),
        "memory.write": CapabilityPolicy(frozenset(UserRole), PermissionScope.GLOBAL),
        "memory.forget": CapabilityPolicy(frozenset(UserRole), PermissionScope.GLOBAL),
        "sticker.manage": CapabilityPolicy(
            frozenset({UserRole.OWNER}), PermissionScope.GLOBAL
        ),
    }
)


@dataclass(frozen=True, slots=True)
class PermissionDecision:
    """Authorization result without any message content."""

    capability: str
    role: UserRole
    target_group_id: str
    code: PermissionDecisionCode

    @property
    def allowed(self) -> bool:
        return self.code is PermissionDecisionCode.ALLOW


def authorize(
    identity: Identity,
    capability: Capability | str,
    *,
    target_group_id: str | None = None,
    policies: Mapping[str, CapabilityPolicy] = CAPABILITY_POLICIES,
) -> PermissionDecision:
    """Authorize a capability for an identity and optional target group.

    Group-scoped capabilities default to the sender's current group. Owners may
    target another group, while every other role is limited to its current group.
    """

    capability_name = (
        capability.value
        if isinstance(capability, Capability)
        else str(capability).strip().lower()
    )
    try:
        normalized_capability = Capability(capability_name).value
    except ValueError:
        normalized_capability = capability_name

    policy = policies.get(normalized_capability)
    if policy is None:
        return PermissionDecision(
            capability=normalized_capability,
            role=identity.role,
            target_group_id=normalize_id(target_group_id),
            code=PermissionDecisionCode.UNKNOWN_CAPABILITY,
        )
    requested_group_id = normalize_id(target_group_id)
    if identity.role not in policy.allowed_roles:
        return PermissionDecision(
            capability=normalized_capability,
            role=identity.role,
            target_group_id=requested_group_id,
            code=PermissionDecisionCode.ROLE_DENIED,
        )

    if policy.scope is PermissionScope.CURRENT_GROUP:
        requested_group_id = requested_group_id or identity.group_id
        if not requested_group_id:
            return PermissionDecision(
                capability=normalized_capability,
                role=identity.role,
                target_group_id="",
                code=PermissionDecisionCode.GROUP_REQUIRED,
            )
        if (
            identity.role is not UserRole.OWNER
            and requested_group_id != identity.group_id
        ):
            return PermissionDecision(
                capability=normalized_capability,
                role=identity.role,
                target_group_id=requested_group_id,
                code=PermissionDecisionCode.OUT_OF_SCOPE,
            )

    return PermissionDecision(
        capability=normalized_capability,
        role=identity.role,
        target_group_id=requested_group_id,
        code=PermissionDecisionCode.ALLOW,
    )
