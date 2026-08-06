from __future__ import annotations

from yebot.runtime.response_media import (
    ResponseMode,
    ResponseModeStore,
    build_response_media_guidance,
    parse_response_mode_intent,
)


def test_parse_one_time_response_media_requests() -> None:
    assert parse_response_mode_intent("用语音回答我这个问题").mode is ResponseMode.VOICE
    assert parse_response_mode_intent("我叫他发语音").mode is ResponseMode.VOICE
    assert parse_response_mode_intent("请用文字回复").mode is ResponseMode.TEXT
    assert parse_response_mode_intent("文字和语音都发").mode is ResponseMode.DUAL


def test_voice_guidance_treats_media_delivery_as_available() -> None:
    guidance = build_response_media_guidance(ResponseMode.VOICE)

    assert "自动把文本转换成选定的语音并发送" in guidance
    assert "发不了语音" in guidance
    assert "好的，我用语音回复你" in guidance


def test_text_mode_has_no_voice_guidance() -> None:
    assert build_response_media_guidance(ResponseMode.TEXT) == ""


def test_parse_persistent_response_media_request() -> None:
    intent = parse_response_mode_intent("以后都用语音回复我")

    assert intent.mode is ResponseMode.VOICE
    assert intent.persist is True


def test_parse_clear_response_media_preference() -> None:
    intent = parse_response_mode_intent("清除我的回复媒介偏好")

    assert intent.clear_preference is True
    assert intent.persist is True


def test_unrelated_media_discussion_does_not_claim_response_mode() -> None:
    assert (
        parse_response_mode_intent("这个语音模型的文本效果怎么样").is_request is False
    )


def test_response_mode_store_persists_per_qq_preference(tmp_path) -> None:
    path = tmp_path / "response-modes.json"
    store = ResponseModeStore(path)

    store.set("42", ResponseMode.VOICE)
    restored = ResponseModeStore(path)

    assert restored.get("42") is ResponseMode.VOICE
    assert restored.get("43") is None
    assert restored.clear("42") is True
    assert ResponseModeStore(path).get("42") is None
