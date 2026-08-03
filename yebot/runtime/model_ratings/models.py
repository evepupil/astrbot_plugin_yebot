"""Validated data contracts for the Codex Radar ratings response."""

from __future__ import annotations

import math
from collections.abc import Mapping
from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class ModelRating:
    """One model's rolling community rating."""

    id: str
    label: str
    group: str
    average: float | None
    count: int

    def as_dict(self) -> dict[str, object]:
        return {
            "id": self.id,
            "label": self.label,
            "group": self.group,
            "average": self.average,
            "count": self.count,
        }


@dataclass(frozen=True, slots=True)
class ModelRatingHistory:
    """One completed day's model ratings."""

    day: str
    updated_at: str
    models: tuple[ModelRating, ...]


@dataclass(frozen=True, slots=True)
class ModelRatingsSnapshot:
    """The public ratings snapshot returned by Codex Radar."""

    day: str
    timezone: str
    refresh_seconds: int
    updated_at: str
    window: str
    window_hours: int
    since: str
    until: str
    source: str
    models: tuple[ModelRating, ...]
    history: tuple[ModelRatingHistory, ...]


def parse_snapshot(payload: object) -> ModelRatingsSnapshot:
    """Validate and normalize the public API payload."""

    data = _as_mapping(payload, "response")
    if data.get("ok") is not True:
        raise ValueError("model ratings response is not ready")

    models_value = data.get("models")
    if not isinstance(models_value, list | tuple):
        raise ValueError("model ratings response has no model list")
    models = tuple(
        _parse_model(value, f"models[{index}]")
        for index, value in enumerate(models_value[:100])
    )

    history_value = data.get("history", [])
    if not isinstance(history_value, list | tuple):
        raise ValueError("model ratings response has invalid history")
    history = tuple(
        _parse_history(value, f"history[{index}]")
        for index, value in enumerate(history_value[:31])
    )

    return ModelRatingsSnapshot(
        day=_required_text(data.get("day"), "day", 32),
        timezone=_required_text(data.get("timezone"), "timezone", 64),
        refresh_seconds=_bounded_int(
            data.get("refresh_seconds"), "refresh_seconds", minimum=1, maximum=86_400
        ),
        updated_at=_required_text(data.get("updated_at"), "updated_at", 64),
        window=_required_text(data.get("window"), "window", 64),
        window_hours=_bounded_int(
            data.get("window_hours"), "window_hours", minimum=1, maximum=168
        ),
        since=_required_text(data.get("since"), "since", 64),
        until=_required_text(data.get("until"), "until", 64),
        source=_required_text(data.get("source"), "source", 64),
        models=models,
        history=history,
    )


def _parse_history(value: object, label: str) -> ModelRatingHistory:
    data = _as_mapping(value, label)
    models_value = data.get("models")
    if not isinstance(models_value, list | tuple):
        raise ValueError(f"{label}.models must be a list")
    return ModelRatingHistory(
        day=_required_text(data.get("day"), f"{label}.day", 32),
        updated_at=_required_text(data.get("updated_at"), f"{label}.updated_at", 64),
        models=tuple(
            _parse_model(item, f"{label}.models[{index}]")
            for index, item in enumerate(models_value[:100])
        ),
    )


def _parse_model(value: object, label: str) -> ModelRating:
    data = _as_mapping(value, label)
    average_value = data.get("average")
    average: float | None
    if average_value is None:
        average = None
    elif isinstance(average_value, (int, float)) and not isinstance(
        average_value, bool
    ):
        average = float(average_value)
        if not math.isfinite(average) or not 0 <= average <= 10:
            raise ValueError(f"{label}.average is out of range")
    else:
        raise ValueError(f"{label}.average must be a number or null")
    return ModelRating(
        id=_required_text(data.get("id"), f"{label}.id", 128),
        label=_required_text(data.get("label"), f"{label}.label", 200),
        group=_required_text(data.get("group"), f"{label}.group", 100),
        average=average,
        count=_bounded_int(
            data.get("count"), f"{label}.count", minimum=0, maximum=10_000_000
        ),
    )


def _as_mapping(value: object, label: str) -> Mapping[str, object]:
    if not isinstance(value, Mapping):
        raise ValueError(f"{label} must be an object")
    return value


def _required_text(value: object, label: str, maximum: int) -> str:
    if not isinstance(value, str):
        raise ValueError(f"{label} must be text")
    text = value.strip()
    if not text or len(text) > maximum:
        raise ValueError(f"{label} is invalid")
    return text


def _bounded_int(
    value: object,
    label: str,
    *,
    minimum: int,
    maximum: int,
) -> int:
    if not isinstance(value, int) or isinstance(value, bool):
        raise ValueError(f"{label} must be an integer")
    if not minimum <= value <= maximum:
        raise ValueError(f"{label} is out of range")
    return value
