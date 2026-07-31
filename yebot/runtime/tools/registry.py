"""Registration and lookup for executable tool handlers."""

from __future__ import annotations

from dataclasses import dataclass

from .models import ToolDefinition, ToolHandler


class ToolRegistrationError(ValueError):
    """Raised when a tool cannot be added to a registry."""


@dataclass(frozen=True, slots=True)
class RegisteredTool:
    definition: ToolDefinition
    handler: ToolHandler


class ToolRegistry:
    """Keep one canonical handler for every declared tool name."""

    def __init__(self) -> None:
        self._tools: dict[str, RegisteredTool] = {}

    def register(self, definition: ToolDefinition, handler: ToolHandler) -> None:
        """Register a handler, rejecting duplicate names explicitly."""

        if not callable(handler):
            raise ToolRegistrationError("tool handler must be callable")
        if definition.name in self._tools:
            raise ToolRegistrationError(f"tool already registered: {definition.name}")
        self._tools[definition.name] = RegisteredTool(definition, handler)

    def resolve(self, name: str) -> RegisteredTool | None:
        """Resolve a user/model supplied name after basic normalization."""

        return self._tools.get(name.strip().lower())

    def definitions(self) -> tuple[ToolDefinition, ...]:
        """Return deterministic metadata for tool discovery."""

        return tuple(
            registered.definition
            for registered in sorted(
                self._tools.values(), key=lambda item: item.definition.name
            )
        )

    def __len__(self) -> int:
        return len(self._tools)
