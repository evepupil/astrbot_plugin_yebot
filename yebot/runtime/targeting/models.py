"""Data contracts for human target resolution."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum


class TargetStatus(StrEnum):
    """Whether a reference selected exactly one group member."""

    RESOLVED = "resolved"
    AMBIGUOUS = "ambiguous"
    UNRESOLVED = "unresolved"


class TargetSource(StrEnum):
    """Evidence used to resolve a target."""

    MENTION = "mention"
    REPLY = "reply"
    QQ_ID = "qq_id"
    NAME = "name"
    SELF = "self"
    RECENT_SPEAKER = "recent_speaker"


@dataclass(frozen=True, slots=True)
class TargetCandidate:
    """A group member that may match a natural-language reference."""

    user_id: str
    nickname: str = ""
    card: str = ""
    role: str = ""

    @property
    def display_name(self) -> str:
        """Return the group card first, then the public nickname."""

        return self.card or self.nickname or self.user_id


@dataclass(frozen=True, slots=True)
class TargetResolution:
    """A deterministic target-resolution outcome exposed to tool adapters."""

    status: TargetStatus
    user_id: str | None = None
    source: TargetSource | None = None
    candidates: tuple[TargetCandidate, ...] = ()

    @property
    def resolved(self) -> bool:
        return self.status is TargetStatus.RESOLVED and self.user_id is not None

    @property
    def summary(self) -> str:
        """Return a concise prompt-safe explanation for an unresolved target."""

        if self.status is TargetStatus.AMBIGUOUS:
            choices = ", ".join(
                f"{candidate.display_name}({candidate.user_id})"
                for candidate in self.candidates[:5]
            )
            return f"target is ambiguous: {choices or 'multiple candidates'}"
        return "target could not be resolved; provide a name, QQ number, reply, or @"
