"""Public Codex Radar client with bounded caching and response size."""

from __future__ import annotations

import asyncio
import json
import math
import time
from collections.abc import Callable
from urllib.request import Request, urlopen

from .models import (
    ModelRating,
    ModelRatingHistory,
    ModelRatingsSnapshot,
    parse_snapshot,
)

DEFAULT_MODEL_RATINGS_ENDPOINT = (
    "https://codexradar.com/api/model-ratings?view=public&history=14"
)
_MAX_RESPONSE_BYTES = 250_000
_DEFAULT_LIMIT = 10
_MAX_LIMIT = 20
_MAX_HISTORY_DAYS = 14

PayloadLoader = Callable[[], object]


class ModelRatingsClient:
    """Fetch and query the site's public rolling model ratings."""

    def __init__(
        self,
        *,
        timeout_seconds: float = 8.0,
        cache_seconds: float = 300.0,
        loader: PayloadLoader | None = None,
    ) -> None:
        if not math.isfinite(timeout_seconds) or timeout_seconds <= 0:
            raise ValueError("timeout_seconds must be positive and finite")
        if not math.isfinite(cache_seconds) or cache_seconds < 0:
            raise ValueError("cache_seconds must be non-negative and finite")
        self._timeout_seconds = timeout_seconds
        self._cache_seconds = cache_seconds
        self._loader = loader or self._load_payload
        self._cache: ModelRatingsSnapshot | None = None
        self._cache_at = 0.0
        self._lock = asyncio.Lock()

    async def query(
        self,
        *,
        query: str = "",
        limit: int = _DEFAULT_LIMIT,
        include_history: bool = False,
        history_days: int = 7,
    ) -> dict[str, object]:
        """Return a compact, sorted view of the current public rankings."""

        normalized_query = query.strip()
        bounded_limit = max(1, min(limit, _MAX_LIMIT))
        bounded_history_days = max(1, min(history_days, _MAX_HISTORY_DAYS))
        snapshot = await self._snapshot()
        matching = tuple(
            model for model in snapshot.models if _matches(model, normalized_query)
        )
        ranked = tuple(sorted(matching, key=_ranking_key))
        selected = ranked[:bounded_limit]
        result: dict[str, object] = {
            "source": "Codex Radar",
            "url": DEFAULT_MODEL_RATINGS_ENDPOINT,
            "day": snapshot.day,
            "updated_at": snapshot.updated_at,
            "timezone": snapshot.timezone,
            "window": snapshot.window,
            "window_hours": snapshot.window_hours,
            "since": snapshot.since,
            "until": snapshot.until,
            "source_cache": snapshot.source,
            "query": normalized_query,
            "matched_count": len(ranked),
            "returned_count": len(selected),
            "models": [
                _ranked_model(model, rank)
                for rank, model in enumerate(selected, start=1)
            ],
        }
        if include_history:
            selected_ids = {model.id for model in selected}
            history = snapshot.history[-bounded_history_days:]
            result["history"] = [_history_as_dict(day, selected_ids) for day in history]
        return result

    async def _snapshot(self) -> ModelRatingsSnapshot:
        now = time.monotonic()
        cached = self._cache
        if cached is not None and now - self._cache_at < self._cache_seconds:
            return cached
        async with self._lock:
            now = time.monotonic()
            cached = self._cache
            if cached is not None and now - self._cache_at < self._cache_seconds:
                return cached
            payload = await asyncio.wait_for(
                asyncio.to_thread(self._loader),
                timeout=self._timeout_seconds,
            )
            snapshot = parse_snapshot(payload)
            self._cache = snapshot
            self._cache_at = time.monotonic()
            return snapshot

    def _load_payload(self) -> object:
        request = Request(
            DEFAULT_MODEL_RATINGS_ENDPOINT,
            headers={
                "Accept": "application/json",
                "User-Agent": "YeBot/0.1 (+https://codexradar.com/)",
            },
        )
        with urlopen(request, timeout=self._timeout_seconds) as response:
            data = response.read(_MAX_RESPONSE_BYTES + 1)
        if len(data) > _MAX_RESPONSE_BYTES:
            raise ValueError("model ratings response is too large")
        return json.loads(data.decode("utf-8"))


def _matches(model: ModelRating, query: str) -> bool:
    if not query:
        return True
    needle = query.casefold()
    return needle in " ".join((model.id, model.label, model.group)).casefold()


def _ranking_key(model: ModelRating) -> tuple[int, float, int, str]:
    if model.average is None:
        return (1, 0.0, -model.count, model.label.casefold())
    return (0, -model.average, -model.count, model.label.casefold())


def _ranked_model(model: ModelRating, rank: int) -> dict[str, object]:
    return {
        "rank": rank,
        **model.as_dict(),
    }


def _history_as_dict(
    day: ModelRatingHistory,
    selected_ids: set[str],
) -> dict[str, object]:
    return {
        "day": day.day,
        "updated_at": day.updated_at,
        "models": [model.as_dict() for model in day.models if model.id in selected_ids],
    }
