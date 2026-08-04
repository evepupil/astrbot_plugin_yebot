import asyncio

from yebot.runtime.tools import OneBotReadCache
from yebot.runtime.tools.onebot import OneBotActionClient


class FakeActionClient:
    def __init__(self) -> None:
        self.calls: list[tuple[str, dict[str, object]]] = []

    async def call_action(self, action: str, **params: object) -> object:
        self.calls.append((action, params))
        if action == "get_group_member_list":
            return [{"user_id": 42, "role": "member"}]
        if action == "get_group_member_info":
            return {"data": {"user_id": 42, "role": "member"}}
        return {"status": "ok"}


def test_onebot_read_cache_reuses_across_clients_and_invalidates_after_write() -> None:
    async def scenario() -> None:
        fake = FakeActionClient()
        read_cache = OneBotReadCache()
        first = OneBotActionClient(fake.call_action, read_cache=read_cache)
        second = OneBotActionClient(fake.call_action, read_cache=read_cache)

        await first.call_action("get_group_member_list", group_id=100)
        await second.call_action("get_group_member_list", group_id=100)
        assert fake.calls == [("get_group_member_list", {"group_id": 100})]

        await first.call_uncached(
            "get_group_member_info",
            group_id=100,
            user_id=42,
        )
        await first.call_action("get_group_member_info", group_id=100, user_id=42)
        assert fake.calls[-1] == (
            "get_group_member_info",
            {"group_id": 100, "user_id": 42},
        )

        await first.call_action("set_group_kick", group_id=100, user_id=42)
        await second.call_action("get_group_member_list", group_id=100)
        assert [action for action, _ in fake.calls].count("get_group_member_list") == 2

    asyncio.run(scenario())
