"""Addressing helpers for AstrBot message chains."""

from __future__ import annotations

from collections.abc import Mapping


def is_reply_prefixed_wake(messages: object, wake_prefixes: object) -> bool:
    """Return whether current text after a reply starts with a wake prefix."""

    prefixes = _normalize_prefixes(wake_prefixes)
    if not prefixes or not isinstance(messages, (list, tuple)):
        return False

    after_reply = False
    current_text: list[str] = []
    for component in messages:
        if _is_reply_component(component):
            after_reply = True
            continue
        if after_reply:
            text = _component_text(component)
            if text:
                current_text.append(text)

    normalized = "".join(current_text).strip()
    return any(normalized.startswith(prefix) for prefix in prefixes)


def _normalize_prefixes(value: object) -> tuple[str, ...]:
    values: object
    if isinstance(value, str):
        values = (value,)
    elif isinstance(value, (list, tuple, set, frozenset)):
        values = value
    else:
        return ()
    return tuple(
        sorted(
            {item.strip() for item in values if isinstance(item, str) and item.strip()},
            key=len,
            reverse=True,
        )
    )


def _component_type(component: object) -> str:
    if isinstance(component, Mapping):
        return str(component.get("type", "")).strip().lower()
    return str(getattr(component, "type", "")).strip().lower()


def _is_reply_component(component: object) -> bool:
    component_type = _component_type(component)
    return component_type.endswith("reply") or type(component).__name__.lower() == (
        "reply"
    )


def _component_text(component: object) -> str:
    if _component_type(component) not in {"plain", "text"}:
        return ""
    if isinstance(component, Mapping):
        data = component.get("data")
        value = data.get("text") if isinstance(data, Mapping) else component.get("text")
    else:
        value = getattr(component, "text", "")
    return value.strip() if isinstance(value, str) else ""
