from yebot.runtime.stickers import build_sticker_consider_arguments


def test_sticker_consider_defaults_fail_closed() -> None:
    assert build_sticker_consider_arguments() == {
        "should_collect": False,
        "asset_kind": "other",
        "reaction_ready": False,
        "meaning": "",
        "image_index": 0,
        "confidence": 0.0,
    }


def test_sticker_consider_arguments_normalize_integer_image_index() -> None:
    assert build_sticker_consider_arguments(
        should_collect=True,
        asset_kind="reaction_sticker",
        reaction_ready=True,
        confidence=0.95,
        meaning="开心",
        tags=["开心"],
        image_index=1.0,
    ) == {
        "should_collect": True,
        "asset_kind": "reaction_sticker",
        "reaction_ready": True,
        "meaning": "开心",
        "image_index": 1,
        "confidence": 0.95,
        "tags": ["开心"],
    }
