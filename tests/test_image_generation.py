import asyncio
import json
from datetime import datetime
from pathlib import Path

from yebot.runtime.image_generation import (
    DailyImageQuota,
    ImageGenerationClient,
    ImageGenerationError,
    extract_image_edit_prompt,
    extract_image_prompt,
    is_group_image_request_addressed,
)


def test_extract_image_prompt_from_chinese_requests() -> None:
    assert extract_image_prompt("画一只戴墨镜的猫") == "一只戴墨镜的猫"
    assert extract_image_prompt("请帮我生成一张赛博朋克城市") == "赛博朋克城市"
    assert extract_image_prompt("[CQ:at,qq=123] 画海边的日落") == "海边的日落"


def test_extract_image_prompt_supports_english_and_rejects_questions() -> None:
    assert extract_image_prompt("draw a tiny red house") == "a tiny red house"
    assert extract_image_prompt("这个图要怎么画") is None
    assert extract_image_prompt("画") is None


def test_extract_image_edit_prompt_supports_reference_transform_requests() -> None:
    assert extract_image_edit_prompt("把这张图改成电影海报风格") == "电影海报风格"
    assert extract_image_edit_prompt("edit this image into watercolor art") == (
        "watercolor art"
    )
    assert extract_image_edit_prompt("改一下") is None


def test_group_image_request_accepts_a_mention_or_wake_command() -> None:
    without_mention = {"message": [{"type": "text", "data": {"text": "画一只猫"}}]}
    with_other_mention = {"message": [{"type": "at", "data": {"qq": "456"}}]}
    with_bot_mention = {"message": [{"type": "at", "data": {"qq": "123"}}]}

    assert not is_group_image_request_addressed(without_mention, "123")
    assert not is_group_image_request_addressed(with_other_mention, "123")
    assert is_group_image_request_addressed(with_bot_mention, "123")
    assert is_group_image_request_addressed(
        without_mention,
        "123",
        wake_command=True,
    )


def test_daily_quota_is_shared_across_restarts_and_resets_by_day(
    tmp_path: Path,
) -> None:
    quota_path = tmp_path / "quota.json"
    first = DailyImageQuota(quota_path, limit=3)
    day_one = datetime(2026, 8, 3, 12)

    async def reserve_first_day() -> list[bool]:
        decisions = [
            await first.reserve("42", is_owner=False, now=day_one) for _ in range(4)
        ]
        return [decision.allowed for decision in decisions]

    assert asyncio.run(reserve_first_day()) == [True, True, True, False]

    restored = DailyImageQuota(quota_path, limit=3)

    async def reserve_next_day() -> tuple[bool, bool]:
        blocked = await restored.reserve("42", is_owner=False, now=day_one)
        next_day = await restored.reserve(
            "42",
            is_owner=False,
            now=datetime(2026, 8, 4, 1),
        )
        return blocked.allowed, next_day.allowed

    assert asyncio.run(reserve_next_day()) == (False, True)


def test_daily_quota_reservation_is_atomic_and_owner_is_exempt(
    tmp_path: Path,
) -> None:
    quota = DailyImageQuota(tmp_path / "quota.json", limit=3)
    now = datetime(2026, 8, 3, 12)

    async def reserve_concurrently() -> list[bool]:
        decisions = await asyncio.gather(
            *(quota.reserve("42", is_owner=False, now=now) for _ in range(8))
        )
        owner = await quota.reserve("owner", is_owner=True, now=now)
        assert owner.allowed and owner.owner_exempt and owner.remaining is None
        return [decision.allowed for decision in decisions]

    results = asyncio.run(reserve_concurrently())
    assert sum(results) == 3


def test_image_client_posts_documented_payload_and_reads_url() -> None:
    calls: list[tuple[str, dict[str, str], bytes, float]] = []

    def requester(
        url: str,
        headers: dict[str, str] | object,
        payload: bytes,
        timeout: float,
    ) -> tuple[int, bytes]:
        calls.append((url, dict(headers), payload, timeout))  # type: ignore[arg-type]
        return 200, json.dumps({"data": [{"url": "/api/storage/image.png"}]}).encode()

    client = ImageGenerationClient(
        api_key="test-key",
        base_url="https://gpt2image.superapi.buzz/",
        requester=requester,  # type: ignore[arg-type]
    )
    image = asyncio.run(client.generate("一只猫"))

    assert image.url == "https://gpt2image.superapi.buzz/api/storage/image.png"
    assert calls[0][0] == "https://gpt2image.superapi.buzz/v1/images/generations"
    assert calls[0][1]["Authorization"] == "Bearer test-key"
    assert json.loads(calls[0][2]) == {
        "model": "gpt-image-2",
        "prompt": "一只猫",
        "n": 1,
        "size": "1024x1024",
        "quality": "medium",
        "response_format": "url",
    }


def test_image_client_posts_documented_edit_payload_and_reads_url() -> None:
    calls: list[tuple[str, dict[str, str], bytes, float]] = []

    def requester(
        url: str,
        headers: dict[str, str] | object,
        payload: bytes,
        timeout: float,
    ) -> tuple[int, bytes]:
        calls.append((url, dict(headers), payload, timeout))  # type: ignore[arg-type]
        return 200, json.dumps({"data": [{"url": "/api/storage/edit.png"}]}).encode()

    client = ImageGenerationClient(
        api_key="test-key",
        base_url="https://gpt2image.superapi.buzz/",
        requester=requester,  # type: ignore[arg-type]
    )
    image = asyncio.run(client.edit("电影海报风格", "data:image/png;base64,abc"))

    assert image.url == "https://gpt2image.superapi.buzz/api/storage/edit.png"
    assert calls[0][0] == "https://gpt2image.superapi.buzz/v1/images/edits"
    assert json.loads(calls[0][2]) == {
        "model": "gpt-image-2",
        "prompt": "电影海报风格",
        "images": [{"image_url": "data:image/png;base64,abc"}],
        "n": 1,
        "size": "1024x1024",
        "quality": "medium",
        "response_format": "url",
    }


def test_image_client_accepts_base64_and_surfaces_api_errors() -> None:
    def base64_requester(
        url: str,
        headers: object,
        payload: bytes,
        timeout: float,
    ) -> tuple[int, bytes]:
        return 200, json.dumps(
            {"data": [{"b64_json": "data:image/png;base64,abc"}]}
        ).encode()

    base64_client = ImageGenerationClient(
        api_key="test-key",
        requester=base64_requester,  # type: ignore[arg-type]
    )
    image = asyncio.run(base64_client.generate("一只猫"))
    assert image.base64_data == "abc"

    def error_requester(
        url: str,
        headers: object,
        payload: bytes,
        timeout: float,
    ) -> tuple[int, bytes]:
        return 429, json.dumps({"error": {"message": "too many requests"}}).encode()

    error_client = ImageGenerationClient(
        api_key="test-key",
        requester=error_requester,  # type: ignore[arg-type]
    )
    try:
        asyncio.run(error_client.generate("一只猫"))
    except ImageGenerationError as error:
        assert "too many requests" in str(error)
    else:
        raise AssertionError("expected ImageGenerationError")
