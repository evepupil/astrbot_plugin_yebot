"""Data contracts for a user's preferred response medium."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum


class ResponseMode(StrEnum):
    """How one bot response is rendered after the model has written its text."""

    TEXT = "text"
    VOICE = "voice"
    DUAL = "dual"


@dataclass(frozen=True, slots=True)
class ResponseModeIntent:
    """A bounded media-mode instruction extracted from one user message."""

    mode: ResponseMode | None = None
    persist: bool = False
    clear_preference: bool = False

    @property
    def is_request(self) -> bool:
        return self.mode is not None or self.clear_preference
