import asyncio
import base64
from pathlib import Path

from yebot.runtime.stickers import StickerCaptionCache, image_reference_fingerprint


def test_image_fingerprint_matches_local_file_and_data_url(tmp_path: Path) -> None:
    image = b"same-image"
    path = tmp_path / "image.jpg"
    path.write_bytes(image)
    data_url = "data:image/jpeg;base64," + base64.b64encode(image).decode()

    async def scenario() -> None:
        assert await image_reference_fingerprint((str(path),)) == (
            await image_reference_fingerprint((data_url,))
        )

    asyncio.run(scenario())


def test_caption_cache_keys_provider_and_model_and_skips_empty_results(
    tmp_path: Path,
) -> None:
    path = tmp_path / "image.jpg"
    path.write_bytes(b"image")

    async def scenario() -> None:
        cache = StickerCaptionCache(ttl_seconds=60)
        calls = 0

        async def empty() -> str:
            nonlocal calls
            calls += 1
            return ""

        async def caption() -> str:
            nonlocal calls
            calls += 1
            return "一张反应图"

        assert (
            await cache.get_or_load(
                (str(path),),
                provider_id="provider-a",
                model_id="model-a",
                loader=empty,
            )
            == ""
        )
        assert (
            await cache.get_or_load(
                (str(path),),
                provider_id="provider-a",
                model_id="model-a",
                loader=caption,
            )
            == "一张反应图"
        )
        assert (
            await cache.get_or_load(
                (str(path),),
                provider_id="provider-a",
                model_id="model-a",
                loader=caption,
            )
            == "一张反应图"
        )
        assert (
            await cache.get_or_load(
                (str(path),),
                provider_id="provider-b",
                model_id="model-a",
                loader=caption,
            )
            == "一张反应图"
        )
        assert calls == 3

    asyncio.run(scenario())
