from yebot.runtime.response_media import (
    ResponseMode,
    read_tts_trigger_probability,
    select_response_mode,
)


def test_tts_probability_is_read_from_provider_settings() -> None:
    assert (
        read_tts_trigger_probability(
            {"provider_tts_settings": {"enable": True, "trigger_probability": 0.15}}
        )
        == 0.15
    )
    assert (
        read_tts_trigger_probability(
            {"provider_tts_settings": {"enable": False, "trigger_probability": 1}}
        )
        == 0
    )


def test_automatic_voice_selection_uses_probability() -> None:
    assert (
        select_response_mode(
            explicit=None,
            stored=None,
            default=ResponseMode.TEXT,
            tts_probability=1,
            random_value=0.99,
        )
        is ResponseMode.VOICE
    )
    assert (
        select_response_mode(
            explicit=None,
            stored=None,
            default=ResponseMode.TEXT,
            tts_probability=0,
            random_value=0,
        )
        is ResponseMode.TEXT
    )


def test_explicit_and_saved_modes_override_automatic_probability() -> None:
    assert (
        select_response_mode(
            explicit=ResponseMode.DUAL,
            stored=ResponseMode.TEXT,
            default=ResponseMode.TEXT,
            tts_probability=1,
            random_value=0,
        )
        is ResponseMode.DUAL
    )
    assert (
        select_response_mode(
            explicit=None,
            stored=ResponseMode.TEXT,
            default=ResponseMode.TEXT,
            tts_probability=1,
            random_value=0,
        )
        is ResponseMode.TEXT
    )
