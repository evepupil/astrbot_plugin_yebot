from yebot.runtime.group_reply import (
    GroupReplyReason,
    astrbot_call_llm_flag,
    build_group_reply_judgement_prompt,
    initial_group_reply_decision,
    is_contextless_clarification,
    is_no_response_placeholder,
    judgement_decision,
    parse_group_reply_judgement,
)


def test_group_reply_decision_maps_to_astrbot_blocking_flag() -> None:
    assert astrbot_call_llm_flag(True) is False
    assert astrbot_call_llm_flag(False) is True


def test_contextless_clarification_detection_catches_vague_replies() -> None:
    assert is_contextless_clarification("啥意思？你这是在说啥")
    assert is_contextless_clarification("啥意思 f佬是啥")
    assert is_contextless_clarification("你在说什么鬼东西")
    assert is_contextless_clarification("啥意思 没听懂")
    assert is_contextless_clarification("我没听懂，你能具体说说吗")
    assert is_contextless_clarification("量子纠缠是什么意思")
    assert not is_contextless_clarification("啥意思？我给你解释一下量子纠缠")
    assert not is_contextless_clarification("这个问题可以从两个方面回答")


def test_no_response_placeholder_detection_catches_dynamic_participants() -> None:
    assert is_no_response_placeholder("（没有回应，这是别人在和机器人互动）")
    assert is_no_response_placeholder("(没有回应，这是DON在和幽幽子机器人互动)")
    assert is_no_response_placeholder("没有回应，这是xxx在xxx聊天")
    assert is_no_response_placeholder("没有回复，这是A与B的对话")
    assert not is_no_response_placeholder(
        "没有回应，这是DON在和幽幽子机器人互动，我来解释"
    )


def test_direct_address_and_reply_to_bot_bypass_ai_judgement() -> None:
    direct = initial_group_reply_decision(
        directly_addressed=True,
        reply_to_bot=False,
        current_text="hello",
    )
    replied = initial_group_reply_decision(
        directly_addressed=False,
        reply_to_bot=True,
        current_text="continue",
    )

    assert direct.should_call_llm
    assert direct.reason is GroupReplyReason.DIRECT_ADDRESS
    assert replied.should_call_llm
    assert replied.reason is GroupReplyReason.REPLY_TO_BOT


def test_empty_group_content_is_rejected_without_a_model_call() -> None:
    decision = initial_group_reply_decision(
        directly_addressed=False,
        reply_to_bot=False,
        current_text="   ... ",
    )

    assert not decision.should_call_llm
    assert decision.reason is GroupReplyReason.EMPTY_CONTENT
    assert not decision.needs_ai_judgement


def test_unaddressed_meaningful_content_uses_ai_judgement() -> None:
    decision = initial_group_reply_decision(
        directly_addressed=False,
        reply_to_bot=False,
        current_text="this weekend should we go to the cinema",
    )

    assert not decision.should_call_llm
    assert decision.needs_ai_judgement
    assert decision.reason is GroupReplyReason.NEEDS_JUDGEMENT


def test_judgement_parser_fails_closed_and_accepts_embedded_json() -> None:
    assert parse_group_reply_judgement('{"should_reply": true}') is True
    assert parse_group_reply_judgement('result: {"should_reply": false}') is False
    assert parse_group_reply_judgement("I am unsure") is None
    assert not judgement_decision(None).should_call_llm


def test_judgement_prompt_contains_both_context_parts() -> None:
    prompt = build_group_reply_judgement_prompt("current", "quoted", "recent")

    assert "current" in prompt
    assert "quoted" in prompt
    assert "recent" in prompt
    assert '"should_reply"' in prompt
    assert "enough concrete information" in prompt
    assert "what does X mean?" in prompt
