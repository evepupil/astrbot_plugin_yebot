"""Small OpenAI-compatible client for the GPT2IMAGE image endpoint."""

from __future__ import annotations

import asyncio
import json
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urljoin, urlparse
from urllib.request import Request, urlopen

Requester = Callable[[str, Mapping[str, str], bytes, float], tuple[int, bytes]]


class ImageGenerationError(RuntimeError):
    """A user-safe image generation failure."""


@dataclass(frozen=True, slots=True)
class GeneratedImage:
    """One image in a response, represented in a form AstrBot can send."""

    url: str = ""
    base64_data: str = ""

    def __post_init__(self) -> None:
        if bool(self.url) == bool(self.base64_data):
            raise ValueError("exactly one image representation is required")


class ImageGenerationClient:
    """Call ``/v1/images/generations`` without adding a runtime dependency."""

    def __init__(
        self,
        *,
        api_key: str,
        base_url: str = "https://gpt2image.superapi.buzz",
        model: str = "gpt-image-2",
        timeout_seconds: float = 180.0,
        requester: Requester | None = None,
    ) -> None:
        if timeout_seconds <= 0:
            raise ValueError("timeout_seconds must be positive")
        self._api_key = api_key.strip()
        self._base_url = base_url.rstrip("/")
        self._model = model.strip() or "gpt-image-2"
        self._timeout_seconds = timeout_seconds
        self._requester = requester or _request_json

    @property
    def is_configured(self) -> bool:
        return bool(self._api_key)

    async def generate(self, prompt: str) -> GeneratedImage:
        normalized_prompt = prompt.strip()
        if not normalized_prompt:
            raise ImageGenerationError("image prompt is empty")
        if not self.is_configured:
            raise ImageGenerationError("image API key is not configured")

        payload = json.dumps(
            {
                "model": self._model,
                "prompt": normalized_prompt,
                "n": 1,
                "size": "1024x1024",
                "quality": "medium",
                "response_format": "url",
            },
            ensure_ascii=False,
        ).encode("utf-8")
        return await self._post_json(self._endpoint, payload)

    async def edit(self, prompt: str, image_data_url: str) -> GeneratedImage:
        """Edit one reference image through the documented JSON edit endpoint."""

        normalized_prompt = prompt.strip()
        if not normalized_prompt:
            raise ImageGenerationError("image edit prompt is empty")
        normalized_image = image_data_url.strip()
        if not normalized_image.lower().startswith("data:image/"):
            raise ImageGenerationError("image reference must be a data URL")
        if not self.is_configured:
            raise ImageGenerationError("image API key is not configured")

        payload = json.dumps(
            {
                "model": self._model,
                "prompt": normalized_prompt,
                "images": [{"image_url": normalized_image}],
                "n": 1,
                "size": "1024x1024",
                "quality": "medium",
                "response_format": "url",
            },
            ensure_ascii=False,
        ).encode("utf-8")
        return await self._post_json(self._edit_endpoint, payload)

    async def _post_json(self, endpoint: str, payload: bytes) -> GeneratedImage:
        headers = {
            "Authorization": f"Bearer {self._api_key}",
            "Content-Type": "application/json",
            "Accept": "application/json",
        }
        try:
            status, body = await asyncio.to_thread(
                self._requester,
                endpoint,
                headers,
                payload,
                self._timeout_seconds,
            )
        except ImageGenerationError:
            raise
        except Exception as error:
            raise ImageGenerationError("image API request failed") from error
        return self._parse_response(status, body)

    @property
    def _endpoint(self) -> str:
        if self._base_url.endswith("/v1"):
            return f"{self._base_url}/images/generations"
        return f"{self._base_url}/v1/images/generations"

    @property
    def _edit_endpoint(self) -> str:
        if self._base_url.endswith("/v1"):
            return f"{self._base_url}/images/edits"
        return f"{self._base_url}/v1/images/edits"

    def _parse_response(self, status: int, body: bytes) -> GeneratedImage:
        try:
            decoded = json.loads(body.decode("utf-8"))
        except (UnicodeDecodeError, ValueError, TypeError) as error:
            raise ImageGenerationError("image API returned invalid JSON") from error
        if not isinstance(decoded, Mapping):
            raise ImageGenerationError("image API returned an invalid response")
        if status >= 400:
            raise ImageGenerationError(_error_message(status, decoded))

        data = decoded.get("data")
        if not isinstance(data, list) or not data or not isinstance(data[0], Mapping):
            raise ImageGenerationError("image API returned no image")
        item: Mapping[str, Any] = data[0]
        raw_url = item.get("url")
        if isinstance(raw_url, str) and raw_url.strip():
            image_url = raw_url.strip()
            parsed_url = urlparse(image_url)
            if not parsed_url.scheme:
                image_url = urljoin(f"{self._base_url}/", image_url)
            if urlparse(image_url).scheme in {"http", "https"}:
                return GeneratedImage(url=image_url)
            raise ImageGenerationError("image API returned an invalid image URL")

        raw_base64 = item.get("b64_json")
        if isinstance(raw_base64, str) and raw_base64.strip():
            return GeneratedImage(base64_data=_normalize_base64(raw_base64))
        raise ImageGenerationError("image API returned no usable image")


def _request_json(
    url: str,
    headers: Mapping[str, str],
    payload: bytes,
    timeout_seconds: float,
) -> tuple[int, bytes]:
    request = Request(url, data=payload, headers=dict(headers), method="POST")
    try:
        with urlopen(request, timeout=timeout_seconds) as response:
            return int(response.status), response.read()
    except HTTPError as error:
        return error.code, error.read()
    except (URLError, TimeoutError, OSError) as error:
        raise ImageGenerationError("image API request failed") from error


def _normalize_base64(value: str) -> str:
    normalized = value.strip()
    if normalized.startswith("base64://"):
        return normalized[len("base64://") :]
    if normalized.startswith("data:") and "," in normalized:
        return normalized.split(",", 1)[1]
    return normalized


def _error_message(status: int, response: Mapping[str, Any]) -> str:
    error = response.get("error")
    if isinstance(error, Mapping):
        message = error.get("message")
        if isinstance(message, str) and message.strip():
            return f"image API error: {message.strip()[:160]}"
    return f"image API returned HTTP {status}"
