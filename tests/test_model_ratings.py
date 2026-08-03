import asyncio

import pytest

from yebot.runtime.model_ratings import ModelRatingsClient, parse_snapshot


def payload() -> dict[str, object]:
    return {
        "ok": True,
        "day": "2026-08-03",
        "timezone": "Asia/Shanghai",
        "refresh_seconds": 300,
        "updated_at": "2026-08-03T14:19:07.363Z",
        "window": "rolling_24h",
        "window_hours": 24,
        "since": "2026-08-02T14:19:07.108Z",
        "until": "2026-08-03T14:19:07.108Z",
        "source": "public_cache",
        "models": [
            {
                "id": "gpt-5.6-sol-medium",
                "label": "GPT-5.6 Sol medium",
                "group": "GPT-5.6 Sol",
                "average": 7.4,
                "count": 41,
            },
            {
                "id": "deepseek-v4-flash-max",
                "label": "DeepSeek V4 Flash max",
                "group": "DeepSeek V4 Flash",
                "average": 9.1,
                "count": 149,
            },
            {
                "id": "gpt-5.6-sol-low",
                "label": "GPT-5.6 Sol low",
                "group": "GPT-5.6 Sol",
                "average": 3.7,
                "count": 7,
            },
        ],
        "history": [
            {
                "day": "2026-08-02",
                "updated_at": "2026-08-03T14:19:07.233Z",
                "models": [
                    {
                        "id": "gpt-5.6-sol-medium",
                        "label": "GPT-5.6 Sol medium",
                        "group": "GPT-5.6 Sol",
                        "average": 8.1,
                        "count": 34,
                    },
                ],
            },
        ],
    }


def test_query_ranks_filters_and_limits_models() -> None:
    client = ModelRatingsClient(loader=payload)

    result = asyncio.run(client.query(query="sol", limit=1))

    assert result["matched_count"] == 2
    assert result["returned_count"] == 1
    assert result["models"] == [
        {
            "rank": 1,
            "id": "gpt-5.6-sol-medium",
            "label": "GPT-5.6 Sol medium",
            "group": "GPT-5.6 Sol",
            "average": 7.4,
            "count": 41,
        }
    ]


def test_query_can_include_history_for_selected_models() -> None:
    client = ModelRatingsClient(loader=payload)

    result = asyncio.run(
        client.query(query="sol medium", limit=5, include_history=True, history_days=1)
    )

    assert result["history"] == [
        {
            "day": "2026-08-02",
            "updated_at": "2026-08-03T14:19:07.233Z",
            "models": [
                {
                    "id": "gpt-5.6-sol-medium",
                    "label": "GPT-5.6 Sol medium",
                    "group": "GPT-5.6 Sol",
                    "average": 8.1,
                    "count": 34,
                }
            ],
        }
    ]


def test_client_reuses_snapshot_within_cache_window() -> None:
    calls = 0

    def loader() -> object:
        nonlocal calls
        calls += 1
        return payload()

    client = ModelRatingsClient(loader=loader, cache_seconds=300)

    asyncio.run(client.query())
    asyncio.run(client.query())

    assert calls == 1


def test_parser_rejects_failed_or_malformed_response() -> None:
    failed = dict(payload())
    failed["ok"] = False
    with pytest.raises(ValueError, match="not ready"):
        parse_snapshot(failed)

    malformed = dict(payload())
    malformed["models"] = [{"id": "broken"}]
    with pytest.raises(ValueError, match="label"):
        parse_snapshot(malformed)
