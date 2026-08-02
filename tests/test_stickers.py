import asyncio
from pathlib import Path
from types import SimpleNamespace

from yebot.domain.identity import Identity, UserRole
from yebot.runtime.stickers import StickerService, StickerStore
from yebot.runtime.tools import ToolContext, ToolResultCode
from yebot.runtime.tools.onebot import OneBotActionClient, OneBotToolRuntime


class DummyImage:
    type = "Image"

    def __init__(self, path: Path) -> None:
        self.path = path

    async def convert_to_file_path(self) -> str:
        return str(self.path)


class DummyEvent:
    def __init__(self, image: DummyImage) -> None:
        self.message_obj = SimpleNamespace(message_id="message-1")
        self.image = image

    def get_messages(self) -> list[DummyImage]:
        return [self.image]


class FakeActionClient:
    def __init__(self) -> None:
        self.calls: list[tuple[str, dict[str, object]]] = []

    async def call_action(self, action: str, **params: object) -> object:
        self.calls.append((action, params))
        return {"status": "ok"}


def identity() -> Identity:
    return Identity("42", "100", UserRole.MEMBER, "member")


def test_store_deduplicates_and_recovers_from_json(tmp_path: Path) -> None:
    store = StickerStore(tmp_path / "stickers")
    first = store.add(
        b"image-data",
        media_type="image/jpeg",
        meaning="无语吐槽",
        tags=("无语", "吐槽"),
        group_id="100",
        source_message_id="m1",
        source_user_id="42",
    )
    duplicate = store.add(
        b"image-data",
        media_type="image/jpeg",
        meaning="另一个描述",
        tags=(),
        group_id="100",
        source_message_id="m2",
        source_user_id="43",
    )

    assert first.duplicate is False
    assert duplicate.duplicate is True
    assert len(store.search("吐槽", group_id="100")) == 1
    restored = StickerStore(tmp_path / "stickers")
    assert restored.get(first.record.sticker_id, group_id="100") == first.record


def test_service_can_decline_without_writing(tmp_path: Path) -> None:
    image_path = tmp_path / "source.jpg"
    image_path.write_bytes(b"image-data")
    service = StickerService(StickerStore(tmp_path / "stickers"))
    result = asyncio.run(
        service.consider(
            DummyEvent(DummyImage(image_path)),
            identity(),
            {"should_collect": False},
        )
    )

    assert result == {"collected": False, "reason": "model_decided_not_useful"}
    assert service.store.list_for("100") == ()


def test_runtime_sends_saved_sticker_as_onebot_image(tmp_path: Path) -> None:
    source = tmp_path / "source.png"
    source.write_bytes(b"png-data")
    store = StickerStore(tmp_path / "stickers")
    event = DummyEvent(DummyImage(source))
    client = FakeActionClient()
    runtime = OneBotToolRuntime.from_client(
        OneBotActionClient(client.call_action),
        dry_run=False,
        sticker_store=store,
        event=event,
    )
    context = ToolContext(identity())
    considered = asyncio.run(
        runtime.execute(
            "sticker.consider",
            {
                "should_collect": True,
                "meaning": "开心",
                "tags": ["开心"],
            },
            context,
        )
    )
    sticker_id = considered.value["sticker"]["sticker_id"]
    sent = asyncio.run(
        runtime.execute("sticker.send", {"sticker_id": sticker_id}, context)
    )

    assert considered.code is ToolResultCode.SUCCESS
    assert sent.code is ToolResultCode.SUCCESS
    assert sent.value["sent"] is True
    assert client.calls[0][0] == "send_group_msg"
    assert client.calls[0][1]["message"][0]["type"] == "image"
    assert store.get(sticker_id, group_id="100").use_count == 1
