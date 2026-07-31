import pytest

from yebot.domain.identity import Identity, UserRole
from yebot.domain.permissions import (
    Capability,
    PermissionDecisionCode,
    authorize,
)


def identity(role: UserRole, group_id: str = "100") -> Identity:
    return Identity("42", group_id, role, role.value)


@pytest.mark.parametrize(
    ("role", "capability", "allowed"),
    [
        (UserRole.MEMBER, Capability.READ, True),
        (UserRole.MEMBER, Capability.SEND_MESSAGE, True),
        (UserRole.MEMBER, Capability.MANAGE_GROUP, False),
        (UserRole.MEMBER, Capability.MANAGE_BOT, False),
        (UserRole.MEMBER, Capability.EXTERNAL_WRITE, False),
        (UserRole.GROUP_ADMIN, Capability.READ, True),
        (UserRole.GROUP_ADMIN, Capability.SEND_MESSAGE, True),
        (UserRole.GROUP_ADMIN, Capability.MANAGE_GROUP, True),
        (UserRole.GROUP_ADMIN, Capability.MANAGE_BOT, False),
        (UserRole.GROUP_ADMIN, Capability.EXTERNAL_WRITE, False),
        (UserRole.OWNER, Capability.READ, True),
        (UserRole.OWNER, Capability.SEND_MESSAGE, True),
        (UserRole.OWNER, Capability.MANAGE_GROUP, True),
        (UserRole.OWNER, Capability.MANAGE_BOT, True),
        (UserRole.OWNER, Capability.EXTERNAL_WRITE, True),
    ],
)
def test_role_capability_matrix(
    role: UserRole, capability: Capability, allowed: bool
) -> None:
    assert authorize(identity(role), capability).allowed is allowed


def test_group_admin_cannot_touch_another_group() -> None:
    decision = authorize(
        identity(UserRole.GROUP_ADMIN, "100"),
        Capability.MANAGE_GROUP,
        target_group_id="200",
    )

    assert decision.code is PermissionDecisionCode.OUT_OF_SCOPE
    assert not decision.allowed


def test_owner_can_target_another_group() -> None:
    decision = authorize(
        identity(UserRole.OWNER, "100"),
        Capability.MANAGE_GROUP,
        target_group_id="200",
    )

    assert decision.code is PermissionDecisionCode.ALLOW
    assert decision.target_group_id == "200"


def test_group_capability_requires_a_group() -> None:
    decision = authorize(
        identity(UserRole.OWNER, ""),
        Capability.SEND_MESSAGE,
    )

    assert decision.code is PermissionDecisionCode.GROUP_REQUIRED


def test_unknown_capability_is_denied() -> None:
    decision = authorize(identity(UserRole.OWNER), "delete_everything")

    assert decision.code is PermissionDecisionCode.UNKNOWN_CAPABILITY
    assert not decision.allowed
