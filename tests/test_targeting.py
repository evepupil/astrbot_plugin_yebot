import asyncio
from types import SimpleNamespace

from yebot.runtime.targeting import TargetResolver, TargetSource, TargetStatus


class FakeActionClient:
    def __init__(self, responses: dict[str, object]) -> None:
        self.responses = responses
        self.calls: list[tuple[str, dict[str, object]]] = []

    async def call_action(self, action: str, **params: object) -> object:
        self.calls.append((action, params))
        return self.responses.get(action, {})


def event(raw_message: dict[str, object]) -> object:
    return SimpleNamespace(message_obj=SimpleNamespace(raw_message=raw_message))


def test_explicit_at_wins_without_querying_onebot() -> None:
    client = FakeActionClient({})
    result = asyncio.run(
        TargetResolver(client).resolve(
            event(
                {
                    "group_id": 100,
                    "message": [
                        {"type": "at", "data": {"qq": "99"}},
                        {"type": "text", "data": {"text": "禁言他"}},
                    ],
                }
            ),
            target_hint="他",
            actor_id="42",
            bot_id="1592829658",
        )
    )

    assert result.status is TargetStatus.RESOLVED
    assert result.user_id == "99"
    assert result.source is TargetSource.MENTION
    assert client.calls == []


def test_reply_author_resolves_before_name_lookup() -> None:
    client = FakeActionClient(
        {
            "get_msg": {
                "data": {
                    "sender": {"user_id": 99, "nickname": "小李", "card": ""}
                }
            }
        }
    )
    result = asyncio.run(
        TargetResolver(client).resolve(
            event(
                {
                    "group_id": 100,
                    "message": [{"type": "reply", "data": {"id": "123"}}],
                }
            ),
            target_hint="他",
            actor_id="42",
        )
    )

    assert result.status is TargetStatus.RESOLVED
    assert result.user_id == "99"
    assert result.source is TargetSource.REPLY
    assert client.calls == [("get_msg", {"message_id": 123})]


def test_unique_group_card_in_natural_language_resolves_to_member_id() -> None:
    client = FakeActionClient(
        {
            "get_group_member_list": {
                "data": [
                    {"user_id": 99, "nickname": "李雷", "card": "小李"},
                    {"user_id": 100, "nickname": "韩梅梅", "card": ""},
                ]
            }
        }
    )
    result = asyncio.run(
        TargetResolver(client).resolve(
            event({"group_id": 100, "message": []}),
            target_hint="把小李禁言一分钟",
            actor_id="42",
        )
    )

    assert result.status is TargetStatus.RESOLVED
    assert result.user_id == "99"
    assert result.source is TargetSource.NAME


def test_same_card_returns_ambiguous_instead_of_picking_a_member() -> None:
    client = FakeActionClient(
        {
            "get_group_member_list": [
                {"user_id": 99, "nickname": "甲", "card": "小王"},
                {"user_id": 100, "nickname": "乙", "card": "小王"},
            ]
        }
    )
    result = asyncio.run(
        TargetResolver(client).resolve(
            event({"group_id": 100, "message": []}),
            target_hint="把小王禁言",
            actor_id="42",
        )
    )

    assert result.status is TargetStatus.AMBIGUOUS
    assert [candidate.user_id for candidate in result.candidates] == ["99", "100"]


def test_pronoun_uses_most_recent_non_actor_non_bot_speaker() -> None:
    client = FakeActionClient(
        {
            "get_group_member_list": [],
            "get_group_msg_history": {
                "data": {
                    "messages": [
                        {
                            "time": 30,
                            "sender": {"user_id": 42, "nickname": "actor"},
                        },
                        {
                            "time": 20,
                            "sender": {"user_id": 1592829658, "nickname": "bot"},
                        },
                        {
                            "time": 10,
                            "sender": {"user_id": 99, "nickname": "小李"},
                        },
                    ]
                }
            },
        }
    )
    result = asyncio.run(
        TargetResolver(client).resolve(
            event({"group_id": 100, "message": []}),
            target_hint="禁言他",
            actor_id="42",
            bot_id="1592829658",
        )
    )

    assert result.status is TargetStatus.RESOLVED
    assert result.user_id == "99"
    assert result.source is TargetSource.RECENT_SPEAKER
