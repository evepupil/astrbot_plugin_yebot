import asyncio
from types import SimpleNamespace

from yebot.runtime.replies import (
    encode_onebot_message,
    extract_reply_references,
    resolve_reply_context,
)


class ReplyComponent:
    type = "Reply"

    def __init__(self, message_id: int, message_str: str = "") -> None:
        self.id = message_id
        self.message_str = message_str


class ReplyEvent:
    def __init__(self, component: object, raw_message: object | None = None) -> None:
        self.message_obj = SimpleNamespace(raw_message=raw_message)
        self.component = component

    def get_messages(self) -> list[object]:
        return [self.component]


class FakeActionClient:
    def __init__(self, response: object) -> None:
        self.response = response
        self.calls: list[tuple[str, dict[str, object]]] = []

    async def call_action(self, action: str, **params: object) -> object:
        self.calls.append((action, params))
        return self.response


def test_reply_context_uses_attached_astrbot_text_without_action() -> None:
    event = ReplyEvent(ReplyComponent(12, "原消息内容"))

    references = extract_reply_references(event)
    context = asyncio.run(resolve_reply_context(event, None))

    assert references[0].message_id == "12"
    assert "原消息内容" in context


def test_reply_context_fetches_missing_body_from_onebot() -> None:
    event = ReplyEvent(
        ReplyComponent(12),
        raw_message={"message": [{"type": "reply", "data": {"id": "12"}}]},
    )
    client = FakeActionClient(
        {
            "data": {
                "message": [
                    {"type": "text", "data": {"text": "被引用的文本"}},
                    {"type": "image", "data": {"file": "secret-url"}},
                ]
            }
        }
    )

    context = asyncio.run(resolve_reply_context(event, client))

    assert client.calls == [("get_msg", {"message_id": 12})]
    assert "被引用的文本" in context
    assert "[图片]" in context
    assert "secret-url" not in context


def test_reply_context_prefers_inline_text_when_raw_segment_duplicates_it() -> None:
    event = ReplyEvent(
        ReplyComponent(12, "AstrBot 已解析的内容"),
        raw_message={"message": [{"type": "reply", "data": {"id": "12"}}]},
    )
    client = FakeActionClient({"data": {"message_str": "不应重复查询"}})

    context = asyncio.run(resolve_reply_context(event, client))

    assert client.calls == []
    assert context.count("消息ID=12") == 1
    assert "AstrBot 已解析的内容" in context


def test_encode_onebot_message_converts_explicit_at_markers() -> None:
    assert encode_onebot_message("[CQ:at,qq=42] 请看 [At:43]") == [
        {"type": "at", "data": {"qq": "42"}},
        {"type": "text", "data": {"text": " 请看 "}},
        {"type": "at", "data": {"qq": "43"}},
    ]


def test_encode_onebot_message_keeps_plain_at_text() -> None:
    message = "@42 只是文本 [CQ:at,qq=not-a-qq]"

    assert encode_onebot_message(message) == message
