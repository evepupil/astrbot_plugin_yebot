"""Automatic response-medium selection."""

from __future__ import annotations

import math
from collections.abc import Mapping

from .models import ResponseMode


def normalize_tts_trigger_probability(value: object) -> float:
    """Clamp a provider TTS probability to a finite value in the unit interval."""

    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return 0.0
    if not math.isfinite(float(value)):
        return 0.0
    return min(1.0, max(0.0, float(value)))


def read_tts_trigger_probability(config: Mapping[str, object] | object) -> float:
    """Read AstrBot's provider TTS trigger probability from its config."""

    if not isinstance(config, Mapping):
        return 0.0
    settings = config.get("provider_tts_settings")
    if not isinstance(settings, Mapping):
        return 0.0
    if settings.get("enable") is False:
        return 0.0
    return normalize_tts_trigger_probability(settings.get("trigger_probability"))


def select_response_mode(
    *,
    explicit: ResponseMode | None,
    stored: ResponseMode | None,
    default: ResponseMode,
    tts_probability: float,
    random_value: float,
) -> ResponseMode:
    """Apply explicit and saved choices before the automatic TTS probability."""

    if explicit is not None:
        return explicit
    if stored is not None:
        return stored
    if default is not ResponseMode.TEXT:
        return default
    probability = normalize_tts_trigger_probability(tts_probability)
    bounded_random = min(1.0, max(0.0, random_value))
    return ResponseMode.VOICE if bounded_random < probability else ResponseMode.TEXT
