"""Small bounded asynchronous caches used by runtime adapters."""

from __future__ import annotations

import asyncio
import math
from collections import OrderedDict
from collections.abc import Awaitable, Callable, Hashable
from dataclasses import dataclass
from time import monotonic
from typing import Generic, TypeVar

CacheKey = TypeVar("CacheKey", bound=Hashable)
CacheValue = TypeVar("CacheValue")


@dataclass(frozen=True, slots=True)
class CacheLookup(Generic[CacheValue]):
    """A value and whether the caller avoided a loader invocation."""

    value: CacheValue
    hit: bool


@dataclass(frozen=True, slots=True)
class CacheStats:
    """Counters useful for bounded, in-process cache diagnostics."""

    hits: int
    misses: int
    coalesced: int
    evictions: int


@dataclass(slots=True)
class _CacheEntry(Generic[CacheValue]):
    value: CacheValue
    expires_at: float


@dataclass(slots=True)
class _InflightEntry(Generic[CacheValue]):
    future: asyncio.Future[CacheValue]
    generation: int


class AsyncTTLCache(Generic[CacheKey, CacheValue]):
    """Bounded TTL cache that merges concurrent loads for the same key."""

    def __init__(
        self,
        *,
        max_entries: int = 256,
        clock: Callable[[], float] = monotonic,
    ) -> None:
        if max_entries < 1:
            raise ValueError("max_entries must be positive")
        self._entries: OrderedDict[CacheKey, _CacheEntry[CacheValue]] = OrderedDict()
        self._inflight: dict[CacheKey, _InflightEntry[CacheValue]] = {}
        self._lock = asyncio.Lock()
        self._max_entries = max_entries
        self._clock = clock
        self._generation = 0
        self._hits = 0
        self._misses = 0
        self._coalesced = 0
        self._evictions = 0

    async def get_or_load(
        self,
        key: CacheKey,
        loader: Callable[[], Awaitable[CacheValue]],
        *,
        ttl_seconds: float,
        cache_result: Callable[[CacheValue], bool] | None = None,
    ) -> CacheLookup[CacheValue]:
        """Return a cached value or load it once for concurrent callers."""

        if not math.isfinite(ttl_seconds) or ttl_seconds < 0:
            raise ValueError("ttl_seconds must be non-negative and finite")

        async with self._lock:
            now = self._clock()
            entry = self._entries.get(key)
            if entry is not None:
                if entry.expires_at > now:
                    self._entries.move_to_end(key)
                    self._hits += 1
                    return CacheLookup(entry.value, True)
                self._entries.pop(key, None)

            inflight = self._inflight.get(key)
            generation = self._generation
            owner = inflight is None or inflight.generation != generation
            if owner:
                future = asyncio.get_running_loop().create_future()
                self._inflight[key] = _InflightEntry(future, generation)
                self._misses += 1
            else:
                assert inflight is not None
                future = inflight.future
                self._coalesced += 1

        assert future is not None
        if not owner:
            return CacheLookup(await asyncio.shield(future), True)

        try:
            value = await loader()
        except BaseException as error:
            async with self._lock:
                inflight = self._inflight.get(key)
                if inflight is not None and inflight.future is future:
                    self._inflight.pop(key, None)
            if not future.done():
                future.set_exception(error)
                future.exception()
            raise

        cache_allowed = ttl_seconds > 0 and (
            cache_result is None or cache_result(value)
        )
        async with self._lock:
            if cache_allowed and generation == self._generation:
                self._entries[key] = _CacheEntry(
                    value=value,
                    expires_at=self._clock() + ttl_seconds,
                )
                self._entries.move_to_end(key)
                while len(self._entries) > self._max_entries:
                    self._entries.popitem(last=False)
                    self._evictions += 1
            inflight = self._inflight.get(key)
            if inflight is not None and inflight.future is future:
                self._inflight.pop(key, None)
            if not future.done():
                future.set_result(value)
        return CacheLookup(value, False)

    def invalidate(self, predicate: Callable[[CacheKey], bool] | None = None) -> None:
        """Drop all entries or only entries matching a predicate."""

        self._generation += 1
        if predicate is None:
            self._entries.clear()
            return
        for key in tuple(self._entries):
            if predicate(key):
                self._entries.pop(key, None)

    def stats(self) -> CacheStats:
        """Return a point-in-time snapshot without exposing cache contents."""

        return CacheStats(
            hits=self._hits,
            misses=self._misses,
            coalesced=self._coalesced,
            evictions=self._evictions,
        )
