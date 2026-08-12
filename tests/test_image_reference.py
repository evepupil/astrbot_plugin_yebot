import asyncio
from types import SimpleNamespace

from yebot.runtime.image_generation import resolve_reply_image


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


def test_resolve_reply_image_reads_inline_data_url_from_get_msg() -> None:
    client = FakeActionClient(
        {
            "get_msg": {
                "data": {
                    "message": [
                        {
                            "type": "image",
                            "data": {"file": "data:image/png;base64,aW1hZ2UtZGF0YQ=="},
                        }
                    ]
                }
            }
        }
    )

    result = asyncio.run(resolve_reply_image(ReplyEvent(12), client))

    assert result is not None
    assert result.message_id == "12"
    assert result.source_user_id == ""
    assert result.data_url == "data:image/png;base64,aW1hZ2UtZGF0YQ=="
    assert client.calls == [("get_msg", {"message_id": 12})]


def test_resolve_reply_image_uses_get_image_for_file_id() -> None:
    client = FakeActionClient(
        {
            "get_msg": {
                "data": {"message": [{"type": "image", "data": {"file": "file-id"}}]}
            },
            "get_image": {"data": {"url": "https://cdn.example.test/image.png"}},
        }
    )

    def downloader(url: str, max_bytes: int) -> tuple[bytes, str]:
        assert url == "https://cdn.example.test/image.png"
        assert max_bytes == 10_000_000
        return b"image-data", "image/png"

    result = asyncio.run(
        resolve_reply_image(ReplyEvent(12), client, downloader=downloader)
    )

    assert result is not None
    assert result.data_url == "data:image/png;base64,aW1hZ2UtZGF0YQ=="
    assert client.calls == [
        ("get_msg", {"message_id": 12}),
        ("get_image", {"file": "file-id"}),
    ]


def test_resolve_reply_image_prefers_onebot_file_when_url_is_unavailable() -> None:
    client = FakeActionClient(
        {
            "get_msg": {
                "data": {
                    "sender": {"user_id": 42},
                    "message": [
                        {
                            "type": "image",
                            "data": {
                                "file": "file-id",
                                "url": "https://cdn.example.test/image.png",
                            },
                        }
                    ],
                }
            },
            "get_image": {
                "data": {
                    "base64": "aW1hZ2UtZGF0YQ==",
                }
            },
        }
    )

    result = asyncio.run(resolve_reply_image(ReplyEvent(12), client))

    assert result is not None
    assert result.source_user_id == "42"
    assert result.data_url == "data:image/jpeg;base64,aW1hZ2UtZGF0YQ=="
    assert client.calls == [
        ("get_msg", {"message_id": 12}),
        ("get_image", {"file": "file-id"}),
    ]


def test_resolve_reply_image_ignores_replied_text_without_an_image() -> None:
    client = FakeActionClient(
        {"get_msg": {"data": {"message": [{"type": "text", "data": {}}]}}}
    )

    result = asyncio.run(resolve_reply_image(ReplyEvent(12), client))

    assert result is None
