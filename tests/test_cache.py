import asyncio

import pytest

from yebot.runtime.cache import AsyncTTLCache


class Clock:
    def __init__(self) -> None:
        self.value = 0.0

    def __call__(self) -> float:
        return self.value


def test_ttl_cache_reuses_then_expires_values() -> None:
    async def scenario() -> None:
        clock = Clock()
        cache: AsyncTTLCache[str, str] = AsyncTTLCache(clock=clock)
        calls = 0

        async def loader() -> str:
            nonlocal calls
            calls += 1
            return f"value-{calls}"

        assert (
            await cache.get_or_load("key", loader, ttl_seconds=10)
        ).value == "value-1"
        assert (
            await cache.get_or_load("key", loader, ttl_seconds=10)
        ).value == "value-1"
        clock.value = 10
        assert (
            await cache.get_or_load("key", loader, ttl_seconds=10)
        ).value == "value-2"
        assert calls == 2

    asyncio.run(scenario())


def test_ttl_cache_coalesces_concurrent_loads() -> None:
    async def scenario() -> None:
        cache: AsyncTTLCache[str, str] = AsyncTTLCache()
        calls = 0

        async def loader() -> str:
            nonlocal calls
            calls += 1
            await asyncio.sleep(0)
            return "shared"

        first, second = await asyncio.gather(
            cache.get_or_load("key", loader, ttl_seconds=10),
            cache.get_or_load("key", loader, ttl_seconds=10),
        )

        assert first.value == second.value == "shared"
        assert calls == 1
        assert cache.stats().coalesced == 1

    asyncio.run(scenario())


def test_ttl_cache_does_not_cache_loader_errors() -> None:
    async def scenario() -> None:
        cache: AsyncTTLCache[str, str] = AsyncTTLCache()
        calls = 0

        async def loader() -> str:
            nonlocal calls
            calls += 1
            raise RuntimeError("upstream failed")

        for _ in range(2):
            with pytest.raises(RuntimeError, match="upstream failed"):
                await cache.get_or_load("key", loader, ttl_seconds=10)
        assert calls == 2

    asyncio.run(scenario())


def test_invalidation_does_not_reuse_or_repopulate_an_old_load() -> None:
    async def scenario() -> None:
        cache: AsyncTTLCache[str, str] = AsyncTTLCache()
        first_started = asyncio.Event()
        second_started = asyncio.Event()
        release_first = asyncio.Event()
        release_second = asyncio.Event()
        calls = 0

        async def loader() -> str:
            nonlocal calls
            calls += 1
            current = calls
            if current == 1:
                first_started.set()
                await release_first.wait()
            else:
                second_started.set()
                await release_second.wait()
            return f"value-{current}"

        first_task = asyncio.create_task(
            cache.get_or_load("key", loader, ttl_seconds=10)
        )
        await first_started.wait()
        cache.invalidate()

        second_task = asyncio.create_task(
            cache.get_or_load("key", loader, ttl_seconds=10)
        )
        await second_started.wait()

        release_first.set()
        first_result = await first_task
        assert first_result.value == "value-1"
        assert not first_result.hit
        release_second.set()
        second_result = await second_task
        assert second_result.value == "value-2"
        assert not second_result.hit
        cached_result = await cache.get_or_load("key", loader, ttl_seconds=10)
        assert cached_result.value == "value-2"
        assert cached_result.hit
        assert calls == 2

    asyncio.run(scenario())
