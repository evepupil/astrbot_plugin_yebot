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


def test_resolve_reply_image_recovers_qq_market_face() -> None:
    client = FakeActionClient(
        {
            "get_msg": {
                "data": {
                    "sender": {"user_id": 42},
                    "message": [
                        {
                            "type": "mface",
                            "data": {
                                "emoji_id": "A1B2C3D4E5F6",
                                "emoji_package_id": 3,
                                "key": "native-key",
                                "summary": "商城表情",
                            },
                        }
                    ],
                }
            }
        }
    )

    def downloader(url: str, max_bytes: int) -> tuple[bytes, str]:
        assert url == (
            "https://gxh.vip.qq.com/club/item/parcel/item/A1/A1B2C3D4E5F6/raw300.gif"
        )
        assert max_bytes == 10_000_000
        return b"gif-image", "image/gif"

    result = asyncio.run(
        resolve_reply_image(ReplyEvent(12), client, downloader=downloader)
    )

    assert result is not None
    assert result.source_user_id == "42"
    assert result.data_url == "data:image/gif;base64,Z2lmLWltYWdl"
    assert client.calls == [("get_msg", {"message_id": 12})]


def test_resolve_reply_image_uses_market_face_url_before_file_identifier() -> None:
    client = FakeActionClient(
        {
            "get_msg": {
                "data": {
                    "message": [
                        {
                            "type": "mface",
                            "data": {
                                "emoji_id": "A1B2C3D4E5F6",
                                "file": "unresolvable-file-id",
                                "url": "https://cdn.example.test/market.gif",
                            },
                        }
                    ]
                }
            }
        }
    )

    def downloader(url: str, max_bytes: int) -> tuple[bytes, str]:
        assert url == "https://cdn.example.test/market.gif"
        return b"market-face", "image/gif"

    result = asyncio.run(
        resolve_reply_image(ReplyEvent(12), client, downloader=downloader)
    )

    assert result is not None
    assert result.data_url == "data:image/gif;base64,bWFya2V0LWZhY2U="
    assert client.calls == [("get_msg", {"message_id": 12})]


def test_resolve_reply_image_ignores_replied_text_without_an_image() -> None:
    client = FakeActionClient(
        {"get_msg": {"data": {"message": [{"type": "text", "data": {}}]}}}
    )

    result = asyncio.run(resolve_reply_image(ReplyEvent(12), client))

    assert result is None
