from __future__ import annotations

import asyncio
from types import SimpleNamespace

from yebot.runtime.stickers import (
    StickerImageRef,
    explicit_reply_collect_recent_shortcut,
    resolve_replied_sticker_image,
)


class ReplyComponent:
    type = "Reply"

    def __init__(self, message_id: int) -> None:
        self.id = message_id
        self.message_str = ""


class ReplyEvent:
    def __init__(self, message_id: int) -> None:
        self.message_obj = SimpleNamespace(
            raw_message={"message": [{"type": "reply", "data": {"id": message_id}}]}
        )
        self.component = ReplyComponent(message_id)

    def get_messages(self) -> list[object]:
        return [self.component]


class FakeActionClient:
    def __init__(self, responses: dict[str, object]) -> None:
        self.responses = responses
        self.calls: list[tuple[str, dict[str, object]]] = []

    async def call_action(self, action: str, **params: object) -> object:
        self.calls.append((action, params))
        return self.responses[action]


def test_replied_sticker_image_keeps_reply_source_and_component() -> None:
    client = FakeActionClient(
        {
            "get_msg": {
                "data": {
                    "sender": {"user_id": 42},
                    "message": [
                        {
                            "type": "image",
                            "data": {"file": "file-id"},
                        }
                    ],
                }
            },
            "get_image": {"data": {"base64": "aW1hZ2UtZGF0YQ=="}},
        }
    )

    result = asyncio.run(
        resolve_replied_sticker_image(
            ReplyEvent(12),
            client,
            max_bytes=10_000_000,
            component_factory=lambda data_url: {"data_url": data_url},
        )
    )

    assert result is not None
    assert result.source_message_id == "12"
    assert result.source_user_id == "42"
    assert result.component == {"data_url": "data:image/jpeg;base64,aW1hZ2UtZGF0YQ=="}
    assert result.provider_url == "data:image/jpeg;base64,aW1hZ2UtZGF0YQ=="


def test_replied_sticker_image_returns_none_for_replied_text() -> None:
    client = FakeActionClient(
        {"get_msg": {"data": {"message": [{"type": "text", "data": {}}]}}}
    )

    result = asyncio.run(
        resolve_replied_sticker_image(
            ReplyEvent(12),
            client,
            max_bytes=10_000_000,
            component_factory=lambda data_url: {"data_url": data_url},
        )
    )

    assert result is None


def test_explicit_reply_shortcut_redirects_without_reporting_failure() -> None:
    result = explicit_reply_collect_recent_shortcut(
        StickerImageRef(object(), source_message_id="12")
    )

    assert result is not None
    assert result["status"] == "success"
    payload = result["result"]
    assert isinstance(payload, dict)
    assert payload["reason"] == "explicit_reply_already_attached"
    assert payload["next_tool"] == "yebot_sticker_consider"
    assert payload["image_index"] == 0


def test_unreadable_explicit_reply_shortcut_never_falls_back_to_history() -> None:
    result = explicit_reply_collect_recent_shortcut("unreadable")

    assert result is not None
    assert result["status"] == "success"
    payload = result["result"]
    assert isinstance(payload, dict)
    assert payload == {
        "candidate_images": 0,
        "collected": False,
        "reason": "quoted_image_unreadable",
    }
