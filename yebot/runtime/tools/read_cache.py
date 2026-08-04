"""Short-lived caching policy for read-only OneBot actions."""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Hashable, Mapping
from dataclasses import dataclass
from time import monotonic

from ..cache import AsyncTTLCache, CacheStats

_READ_ACTION_TTLS: Mapping[str, float] = {
    "get_group_member_list": 30.0,
    "get_group_member_info": 30.0,
    "get_group_msg_history": 5.0,
    "get_msg": 60.0,
    "get_image": 60.0,
}


@dataclass(frozen=True, slots=True)
class _ActionCacheKey:
    action: str
    params: tuple[tuple[str, Hashable], ...]


class OneBotReadCache:
    """Cache safe OneBot reads while keeping write paths observable and fresh."""

    def __init__(
        self,
        *,
        max_entries: int = 512,
        clock: Callable[[], float] = monotonic,
    ) -> None:
        self._cache: AsyncTTLCache[_ActionCacheKey, object] = AsyncTTLCache(
            max_entries=max_entries,
            clock=clock,
        )

    async def get_or_load(
        self,
        action: str,
        params: Mapping[str, object],
        loader: Callable[[], Awaitable[object]],
    ) -> object:
        """Return a cached read or execute ``loader`` once."""

        ttl_seconds = _READ_ACTION_TTLS.get(action)
        if ttl_seconds is None:
            return await loader()
        key = _ActionCacheKey(
            action=action,
            params=tuple(
                sorted((str(name), _freeze(value)) for name, value in params.items())
            ),
        )
        lookup = await self._cache.get_or_load(
            key,
            loader,
            ttl_seconds=ttl_seconds,
        )
        return lookup.value

    def invalidate_group(self, group_id: object) -> None:
        """Drop cached reads associated with one group after a write."""

        normalized = str(group_id).strip()
        if not normalized:
            return
        self._cache.invalidate(lambda key: _parameter(key, "group_id") == normalized)

    def after_write(self, action: str, params: Mapping[str, object]) -> None:
        """Invalidate data that a successful mutating action may have changed."""

        if action in _READ_ACTION_TTLS:
            return
        if "group_id" in params:
            self.invalidate_group(params["group_id"])
        elif action == "delete_msg":
            self._cache.invalidate()

    def stats(self) -> CacheStats:
        """Expose only counters, never cached QQ data."""

        return self._cache.stats()


def _parameter(key: _ActionCacheKey, name: str) -> str:
    for parameter, value in key.params:
        if parameter == name:
            return str(value)
    return ""


def _freeze(value: object) -> Hashable:
    """Turn action parameters into bounded, hashable cache-key values."""

    if value is None or isinstance(value, (str, int, float, bool, bytes)):
        return value
    if isinstance(value, Mapping):
        return tuple(sorted((str(key), _freeze(item)) for key, item in value.items()))
    if isinstance(value, (list, tuple, set, frozenset)):
        return tuple(_freeze(item) for item in value)
    text = repr(value)
    return text[:256]
