"""Validate model-authored fictional dialogue before it reaches OneBot."""

from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass

_MIN_NODES = 3
_MAX_NODES = 12
_MAX_SPEAKER_LENGTH = 32
_MAX_CONTENT_LENGTH = 300
_MAX_TOTAL_CONTENT_LENGTH = 2_000
_FICTION_SUFFIX = "（虚构）"
_SUFFIX_PATTERN = re.compile(r"[（(]\s*虚构\s*[）)]\s*$")
_FORBIDDEN_SPEAKER_PATTERN = re.compile(r"[\r\n\[\]@]")


@dataclass(frozen=True, slots=True)
class ForwardSceneNode:
    """One visibly fictional node sent through a QQ forward message."""

    nickname: str
    content: str


def build_forward_scene(
    nodes: object,
    *,
    target_nickname: str,
) -> tuple[ForwardSceneNode, ...]:
    """Build bounded, plain-text forward nodes from one model tool call.

    ``speaker=target`` is the only way to use the current @ target's nickname.
    Every node is marked fictional by this function, never by the model.
    """

    if not isinstance(nodes, list) or not _MIN_NODES <= len(nodes) <= _MAX_NODES:
        raise ValueError(f"nodes must contain {_MIN_NODES} to {_MAX_NODES} items")

    rendered: list[ForwardSceneNode] = []
    has_target = False
    total_content_length = 0
    for raw_node in nodes:
        if not isinstance(raw_node, Mapping):
            raise ValueError("every node must be an object")
        speaker = _required_text(raw_node.get("speaker"), "speaker")
        content = _required_text(raw_node.get("content"), "content")
        if len(content) > _MAX_CONTENT_LENGTH:
            raise ValueError("node content is too long")
        if "[cq:" in content.lower():
            raise ValueError("node content must be plain text")
        total_content_length += len(content)
        if total_content_length > _MAX_TOTAL_CONTENT_LENGTH:
            raise ValueError("scene content is too long")

        if speaker.lower() == "target":
            nickname = _fictional_name(target_nickname)
            has_target = True
        else:
            nickname = _fictional_name(speaker)
        rendered.append(ForwardSceneNode(nickname, content))

    if not has_target:
        raise ValueError("scene must include the target speaker")
    return tuple(rendered)


def _required_text(value: object, field: str) -> str:
    if not isinstance(value, str):
        raise ValueError(f"{field} must be text")
    text = value.strip()
    if not text:
        raise ValueError(f"{field} is required")
    return text


def _fictional_name(value: str) -> str:
    base = _SUFFIX_PATTERN.sub("", value).strip()
    if not base or len(base) > _MAX_SPEAKER_LENGTH:
        raise ValueError("speaker name has an invalid length")
    if _FORBIDDEN_SPEAKER_PATTERN.search(base):
        raise ValueError("speaker name contains unsupported characters")
    return f"{base}{_FICTION_SUFFIX}"
