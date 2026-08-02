import asyncio
import hashlib
from pathlib import Path
from types import SimpleNamespace

from yebot.domain.identity import Identity, UserRole
from yebot.runtime.stickers import StickerService, StickerStore
from yebot.runtime.stickers.native import parse_native_sticker
from yebot.runtime.tools import ToolContext, ToolResultCode
from yebot.runtime.tools.onebot import OneBotActionClient, OneBotToolRuntime


class DummyImage:
    type = "Image"

    def __init__(self, path: Path) -> None:
        self.path = path

    async def convert_to_file_path(self) -> str:
        return str(self.path)


class Base64Image:
    type = "image"

    async def convert_to_base64(self) -> str:
        return "base64://aW1hZ2UtZGF0YQ=="


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


class NativeFaceActionClient(FakeActionClient):
    async def call_action(self, action: str, **params: object) -> object:
        self.calls.append((action, params))
        if action == "add_custom_face":
            return {
                "data": {
                    "emojiId": "emoji-1",
                    "emojiPackageId": 0,
                    "key": "native-key",
                    "resId": "res-1",
                    "md5": "native-md5",
                }
            }
        return {"status": "ok"}


class PersonalFaceActionClient(FakeActionClient):
    async def call_action(self, action: str, **params: object) -> object:
        self.calls.append((action, params))
        if action == "add_custom_face":
            return {"result": 0, "errMsg": "success", "isExist": 1}
        if action == "fetch_custom_face_detail":
            return [
                {
                    "uin": "1592829658",
                    "emoId": 7,
                    "resId": "1592829658_0_0_0_NATIVE_0_0",
                    "url": "https://p.qpic.cn/qq_expression/native/0",
                    "md5": hashlib.md5(b"image-data").hexdigest().upper(),
                    "epId": "0",
                    "desc": "个人收藏表情",
                }
            ]
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


def test_service_exposes_provider_readable_image_urls(tmp_path: Path) -> None:
    image_path = tmp_path / "source.jpg"
    image_path.write_bytes(b"image-data")
    service = StickerService(StickerStore(tmp_path / "stickers"))

    local_urls = asyncio.run(service.image_urls(DummyEvent(DummyImage(image_path))))
    data_urls = asyncio.run(service.image_urls(DummyEvent(Base64Image())))

    assert local_urls == (str(image_path),)
    assert data_urls == ("data:image/jpeg;base64,aW1hZ2UtZGF0YQ==",)


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
    send_call = next(call for call in client.calls if call[0] == "send_group_msg")
    assert send_call[1]["message"][0]["type"] == "image"
    assert store.get(sticker_id, group_id="100").use_count == 1


def test_collection_calls_native_custom_face_action(tmp_path: Path) -> None:
    image_path = tmp_path / "source.jpg"
    image_path.write_bytes(b"image-data")
    store = StickerStore(tmp_path / "stickers")
    client = NativeFaceActionClient()
    runtime = OneBotToolRuntime.from_client(
        OneBotActionClient(client.call_action),
        dry_run=False,
        sticker_store=store,
        event=DummyEvent(DummyImage(image_path)),
    )

    result = asyncio.run(
        runtime.execute(
            "sticker.consider",
            {"should_collect": True, "meaning": "开心", "tags": ["开心"]},
            ToolContext(identity()),
        )
    )

    assert result.code is ToolResultCode.SUCCESS
    sticker_id = result.value["sticker"]["sticker_id"]
    record = store.get(sticker_id, group_id="100")
    assert record is not None and record.has_native_face
    assert result.value["native_synced"] is True
    assert client.calls[0][0] == "add_custom_face"
    assert client.calls[0][1]["md5"] == hashlib.md5(b"image-data").hexdigest()


def test_native_face_fields_are_persisted_and_sent_as_mface(tmp_path: Path) -> None:
    source = tmp_path / "source.png"
    source.write_bytes(b"png-data")
    store = StickerStore(tmp_path / "stickers")
    added = store.add(
        b"png-data",
        media_type="image/png",
        meaning="开心",
        tags=("开心",),
        group_id="100",
        source_message_id="m1",
        source_user_id="42",
    )
    attached = store.attach_native(
        added.record.sticker_id,
        emoji_id="emoji-1",
        emoji_package_id=0,
        key="native-key",
        res_id="res-1",
        md5=added.record.digest,
        summary="开心",
    )
    assert attached is not None and attached.has_native_face
    restored = StickerStore(tmp_path / "stickers")
    assert restored.get(added.record.sticker_id, group_id="100") == attached

    client = FakeActionClient()
    runtime = OneBotToolRuntime.from_client(
        OneBotActionClient(client.call_action),
        dry_run=False,
        sticker_store=restored,
    )
    sent = asyncio.run(
        runtime.execute(
            "sticker.send",
            {"sticker_id": added.record.sticker_id},
            ToolContext(identity()),
        )
    )

    assert sent.code is ToolResultCode.SUCCESS
    assert sent.value["format"] == "mface"
    assert client.calls == [
        (
            "send_group_msg",
            {
                "group_id": 100,
                "message": [
                    {
                        "type": "mface",
                        "data": {
                            "emoji_package_id": 0,
                            "emoji_id": "emoji-1",
                            "key": "native-key",
                            "summary": "开心",
                        },
                    }
                ],
            },
        )
    ]


def test_native_face_parser_accepts_napcat_detail_shape() -> None:
    parsed = parse_native_sticker(
        {
            "data": {
                "emojiInfoList": [
                    {
                        "emojiId": "emoji-1",
                        "emojiPackageId": "2",
                        "key": "native-key",
                        "resId": "res-1",
                        "md5": "ABCDEF",
                    }
                ]
            }
        }
    )

    assert parsed is not None
    assert parsed.emoji_id == "emoji-1"
    assert parsed.emoji_package_id == 2
    assert parsed.key == "native-key"
    assert parsed.md5 == "ABCDEF"


def test_native_face_parser_accepts_personal_emoji_detail_shape() -> None:
    parsed = parse_native_sticker(
        {
            "uin": "1592829658",
            "emoId": 7,
            "resId": "1592829658_0_0_0_NATIVE_0_0",
            "url": "https://p.qpic.cn/qq_expression/native/0",
            "md5": "ABCDEF",
            "epId": "0",
            "desc": "个人收藏表情",
        }
    )

    assert parsed is not None
    assert parsed.emoji_id == ""
    assert parsed.key == ""
    assert parsed.res_id.endswith("NATIVE_0_0")
    assert parsed.url.endswith("/0")
    assert parsed.summary == "个人收藏表情"


def test_personal_native_face_is_persisted_and_sent_by_qq_url(tmp_path: Path) -> None:
    image_path = tmp_path / "source.jpg"
    image_path.write_bytes(b"image-data")
    store = StickerStore(tmp_path / "stickers")
    client = PersonalFaceActionClient()
    runtime = OneBotToolRuntime.from_client(
        OneBotActionClient(client.call_action),
        dry_run=False,
        sticker_store=store,
        event=DummyEvent(DummyImage(image_path)),
    )

    result = asyncio.run(
        runtime.execute(
            "sticker.consider",
            {"should_collect": True, "meaning": "个人收藏", "tags": []},
            ToolContext(identity()),
        )
    )

    assert result.code is ToolResultCode.SUCCESS
    sticker_id = result.value["sticker"]["sticker_id"]
    record = store.get(sticker_id, group_id="100")
    assert record is not None
    assert record.has_native_asset is True
    assert record.has_native_face is False
    sent = asyncio.run(
        runtime.execute(
            "sticker.send",
            {"sticker_id": sticker_id},
            ToolContext(identity()),
        )
    )
    assert sent.code is ToolResultCode.SUCCESS
    assert sent.value["format"] == "image_fallback"
    send_call = next(call for call in client.calls if call[0] == "send_group_msg")
    assert send_call[1]["message"][0]["data"]["file"].startswith(
        "https://p.qpic.cn/"
    )
