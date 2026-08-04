from __future__ import annotations

import asyncio
from pathlib import Path
from types import SimpleNamespace

from yebot.domain.identity import Identity, UserRole
from yebot.runtime.stickers import StickerImageRef, StickerService, StickerStore
from yebot.runtime.stickers.history import (
    enrich_history_image_source,
    extract_history_image_sources,
)


class _Image:
    type = "image"

    def __init__(self, path: Path) -> None:
        self.path = path

    async def convert_to_file_path(self) -> str:
        return str(self.path)


class _HistoricalEvent:
    def __init__(self, ref: StickerImageRef) -> None:
        self.message_obj = SimpleNamespace(message_id="current")
        self._refs = (ref,)

    def get_messages(self) -> list[object]:
        return []

    def get_extra(self, key: str, default: object = None) -> object:
        if key == "yebot.sticker.image_refs":
            return self._refs
        return default


def test_history_images_are_newest_first_and_skip_current_message() -> None:
    response = {
        "data": {
            "messages": [
                {
                    "time": 10,
                    "message_id": 100,
                    "sender": {"user_id": 7},
                    "message": [
                        {
                            "type": "image",
                            "data": {"file": "old.jpg", "url": "https://img/old"},
                        }
                    ],
                },
                {
                    "time": 20,
                    "message_id": 101,
                    "sender": {"user_id": 8},
                    "message": [
                        {
                            "type": "image",
                            "data": {"file": "new.jpg", "url": "https://img/new"},
                        }
                    ],
                },
                {
                    "time": 30,
                    "message_id": 102,
                    "sender": {"user_id": 9},
                    "message": [
                        {
                            "type": "image",
                            "data": {"file": "current.jpg"},
                        }
                    ],
                },
            ]
        }
    }

    sources = extract_history_image_sources(
        response,
        current_message_id="102",
        max_images=2,
    )

    assert [source.message_id for source in sources] == ["101", "100"]
    assert sources[0].source_user_id == "8"
    assert sources[0].url == "https://img/new"


def test_history_images_support_cq_image_strings() -> None:
    response = {
        "messages": [
            {
                "time": 1,
                "message_id": 20,
                "sender": {"user_id": 7},
                "message": "看图 [CQ:image,file=face.png,url=https://img/face]",
            }
        ]
    }

    sources = extract_history_image_sources(response)

    assert len(sources) == 1
    assert sources[0].file == "face.png"
    assert sources[0].url == "https://img/face"


def test_history_image_source_can_be_enriched_by_get_image() -> None:
    sources = extract_history_image_sources(
        {
            "messages": [
                {
                    "message_id": 20,
                    "message": [{"type": "image", "data": {"file": "face.png"}}],
                }
            ]
        }
    )

    enriched = enrich_history_image_source(
        sources[0],
        {"data": {"url": "https://img/face", "file": "face.png"}},
    )

    assert enriched.file == "face.png"
    assert enriched.url == "https://img/face"


def test_service_collects_an_explicit_historical_image_ref(tmp_path: Path) -> None:
    image_path = tmp_path / "historical.jpg"
    image_path.write_bytes(b"historical-image")
    store = StickerStore(tmp_path / "stickers")
    service = StickerService(store)
    event = _HistoricalEvent(
        StickerImageRef(
            _Image(image_path),
            source_message_id="old-message",
            source_user_id="8",
        )
    )

    result = asyncio.run(
        service.consider(
            event,
            Identity("42", "100", UserRole.MEMBER, "member"),
            {
                "should_collect": True,
                "asset_kind": "meme",
                "reaction_ready": True,
                "confidence": 0.95,
                "meaning": "历史表情",
                "tags": ["历史"],
            },
        )
    )

    assert result["collected"] is True  # type: ignore[index]
    record = store.list_for("100")[0]
    assert record.source_message_id == "old-message"
    assert record.source_user_id == "8"
