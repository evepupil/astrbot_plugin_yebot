"""Cross-platform, standard-library system information collection."""

from __future__ import annotations

import asyncio
import ctypes
import math
import os
import platform
import time
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path

CpuTimes = tuple[int, int]
MemoryValues = tuple[int, int]
CpuReader = Callable[[], CpuTimes | None]
MemoryReader = Callable[[], MemoryValues | None]
UptimeReader = Callable[[], float | None]
ProcessMemoryReader = Callable[[], int | None]


def _utc_now() -> datetime:
    return datetime.now(UTC)


class SystemInfoCollector:
    """Collect host and YeBot process metrics without external dependencies."""

    def __init__(
        self,
        *,
        sample_interval_seconds: float = 0.05,
        monotonic: Callable[[], float] = time.monotonic,
        wall_clock: Callable[[], datetime] = _utc_now,
        cpu_reader: CpuReader = lambda: _read_cpu_times(),
        memory_reader: MemoryReader = lambda: _read_memory_values(),
        uptime_reader: UptimeReader = lambda: _read_system_uptime(),
        process_memory_reader: ProcessMemoryReader = lambda: _read_process_rss(),
    ) -> None:
        if not math.isfinite(sample_interval_seconds) or sample_interval_seconds < 0:
            raise ValueError("sample_interval_seconds must be non-negative and finite")
        self._sample_interval_seconds = sample_interval_seconds
        self._monotonic = monotonic
        self._wall_clock = wall_clock
        self._cpu_reader = cpu_reader
        self._memory_reader = memory_reader
        self._uptime_reader = uptime_reader
        self._process_memory_reader = process_memory_reader
        self._started_monotonic = monotonic()
        self._started_at = _format_timestamp(wall_clock())

    async def collect(self) -> dict[str, object]:
        """Return one point-in-time snapshot for an operations query."""

        cpu_before = self._cpu_reader()
        if cpu_before is not None and self._sample_interval_seconds > 0:
            await asyncio.sleep(self._sample_interval_seconds)
        cpu_after = self._cpu_reader()
        cpu_percent = calculate_cpu_percent(cpu_before, cpu_after)

        memory = _memory_payload(self._memory_reader())
        system_uptime = self._uptime_reader()
        process_uptime = max(0.0, self._monotonic() - self._started_monotonic)
        load_average = _read_load_average()
        wall_clock = self._wall_clock()
        rss_bytes = self._process_memory_reader()

        return {
            "status": "ok",
            "source": "Python standard library",
            "collected_at": _format_timestamp(wall_clock),
            "host": {
                "os": platform.system() or "unknown",
                "release": platform.release() or "unknown",
                "machine": platform.machine() or "unknown",
                "python": platform.python_version(),
            },
            "cpu": {
                "logical_cores": os.cpu_count() or 1,
                "usage_percent": cpu_percent,
                "load_average": list(load_average) if load_average else None,
            },
            "memory": memory,
            "system": {
                "uptime_seconds": system_uptime,
                "uptime_display": (
                    format_duration(system_uptime)
                    if system_uptime is not None
                    else None
                ),
            },
            "process": {
                "pid": os.getpid(),
                "started_at": self._started_at,
                "uptime_seconds": round(process_uptime, 3),
                "uptime_display": format_duration(process_uptime),
                "rss_bytes": rss_bytes,
                "rss_display": format_bytes(rss_bytes),
            },
        }


def calculate_cpu_percent(
    before: CpuTimes | None,
    after: CpuTimes | None,
) -> float | None:
    """Calculate busy CPU percentage from two cumulative CPU readings."""

    if before is None or after is None:
        return None
    total_delta = after[0] - before[0]
    idle_delta = after[1] - before[1]
    if total_delta <= 0 or idle_delta < 0:
        return None
    percentage = (total_delta - idle_delta) / total_delta * 100
    return round(max(0.0, min(100.0, percentage)), 1)


def format_duration(seconds: float) -> str:
    """Format seconds as a compact, stable duration for an Agent reply."""

    if not math.isfinite(seconds):
        return "unknown"
    remaining = max(0, int(seconds))
    days, remaining = divmod(remaining, 86_400)
    hours, remaining = divmod(remaining, 3_600)
    minutes, seconds_value = divmod(remaining, 60)
    parts: list[str] = []
    if days:
        parts.append(f"{days}d")
    if hours or days:
        parts.append(f"{hours}h")
    if minutes or hours or days:
        parts.append(f"{minutes}m")
    parts.append(f"{seconds_value}s")
    return " ".join(parts)


def format_bytes(value: int | None) -> str | None:
    """Format bytes with a stable binary unit for human-readable replies."""

    if value is None:
        return None
    amount = float(max(0, value))
    units = ("B", "KiB", "MiB", "GiB", "TiB")
    unit_index = 0
    while amount >= 1024 and unit_index < len(units) - 1:
        amount /= 1024
        unit_index += 1
    if unit_index == 0:
        return f"{amount:.0f} {units[unit_index]}"
    return f"{amount:.1f} {units[unit_index]}"


def _read_cpu_times() -> CpuTimes | None:
    if os.name == "nt":
        return _read_windows_cpu_times()
    try:
        fields = Path("/proc/stat").read_text(encoding="ascii").splitlines()[0].split()
    except (OSError, IndexError):
        return None
    if not fields or fields[0] != "cpu":
        return None
    try:
        values = [int(value) for value in fields[1:]]
    except ValueError:
        return None
    if len(values) < 4:
        return None
    total = sum(values)
    idle = values[3] + (values[4] if len(values) > 4 else 0)
    return total, idle


def _read_memory_values() -> MemoryValues | None:
    if os.name == "nt":
        return _read_windows_memory_values()
    try:
        values: dict[str, int] = {}
        for line in Path("/proc/meminfo").read_text(encoding="ascii").splitlines():
            name, separator, raw_value = line.partition(":")
            if not separator:
                continue
            pieces = raw_value.strip().split()
            if not pieces:
                continue
            value = int(pieces[0])
            multiplier = 1024 if len(pieces) > 1 and pieces[1].lower() == "kb" else 1
            values[name] = value * multiplier
        total = values.get("MemTotal")
        available = values.get("MemAvailable", values.get("MemFree"))
        if total is None or available is None:
            return None
        return total, min(total, max(0, available))
    except (OSError, ValueError):
        return None


def _read_system_uptime() -> float | None:
    if os.name == "nt":
        return _read_windows_uptime()
    try:
        value = float(Path("/proc/uptime").read_text(encoding="ascii").split()[0])
    except (OSError, IndexError, ValueError):
        return None
    return value if math.isfinite(value) and value >= 0 else None


def _read_process_rss() -> int | None:
    if os.name == "nt":
        return _read_windows_process_rss()
    try:
        for line in Path("/proc/self/status").read_text(encoding="ascii").splitlines():
            if not line.startswith("VmRSS:"):
                continue
            pieces = line.split()
            if len(pieces) < 2:
                return None
            return int(pieces[1]) * 1024
    except (OSError, ValueError):
        return None
    return None


def _read_load_average() -> tuple[float, ...] | None:
    get_load_average = getattr(os, "getloadavg", None)
    if not callable(get_load_average):
        return None
    try:
        values = get_load_average()
    except OSError:
        return None
    return tuple(
        float(value) for value in values if math.isfinite(value) and value >= 0
    )


def _memory_payload(values: MemoryValues | None) -> dict[str, object]:
    if values is None:
        return {
            "available": False,
            "total_bytes": None,
            "total_display": None,
            "available_bytes": None,
            "available_display": None,
            "used_bytes": None,
            "used_display": None,
            "used_percent": None,
        }
    total, available = values
    bounded_total = max(0, total)
    bounded_available = min(bounded_total, max(0, available))
    used = bounded_total - bounded_available
    return {
        "available": True,
        "total_bytes": bounded_total,
        "total_display": format_bytes(bounded_total),
        "available_bytes": bounded_available,
        "available_display": format_bytes(bounded_available),
        "used_bytes": used,
        "used_display": format_bytes(used),
        "used_percent": (
            round(used / bounded_total * 100, 1) if bounded_total else 0.0
        ),
    }


def _read_windows_cpu_times() -> CpuTimes | None:
    windll = getattr(ctypes, "windll", None)
    kernel32 = getattr(windll, "kernel32", None)
    get_system_times = getattr(kernel32, "GetSystemTimes", None)
    if get_system_times is None:
        return None
    get_system_times.argtypes = [
        ctypes.POINTER(_FileTime),
        ctypes.POINTER(_FileTime),
        ctypes.POINTER(_FileTime),
    ]
    get_system_times.restype = ctypes.c_bool

    idle = _FileTime()
    kernel = _FileTime()
    user = _FileTime()
    if not get_system_times(
        ctypes.byref(idle), ctypes.byref(kernel), ctypes.byref(user)
    ):
        return None
    return _filetime_value(kernel) + _filetime_value(user), _filetime_value(idle)


def _read_windows_memory_values() -> MemoryValues | None:
    windll = getattr(ctypes, "windll", None)
    kernel32 = getattr(windll, "kernel32", None)
    global_memory_status = getattr(kernel32, "GlobalMemoryStatusEx", None)
    if global_memory_status is None:
        return None
    global_memory_status.argtypes = [ctypes.POINTER(_MemoryStatusEx)]
    global_memory_status.restype = ctypes.c_bool

    status = _MemoryStatusEx()
    status.length = ctypes.sizeof(status)
    if not global_memory_status(ctypes.byref(status)):
        return None
    return int(status.total_physical), int(status.available_physical)


def _read_windows_uptime() -> float | None:
    windll = getattr(ctypes, "windll", None)
    kernel32 = getattr(windll, "kernel32", None)
    get_tick_count = getattr(kernel32, "GetTickCount64", None)
    if get_tick_count is None:
        return None
    get_tick_count.restype = ctypes.c_uint64
    return float(get_tick_count()) / 1000


def _read_windows_process_rss() -> int | None:
    windll = getattr(ctypes, "windll", None)
    kernel32 = getattr(windll, "kernel32", None)
    psapi = getattr(windll, "psapi", None)
    get_current_process = getattr(kernel32, "GetCurrentProcess", None)
    get_process_memory_info = getattr(psapi, "GetProcessMemoryInfo", None)
    if get_current_process is None or get_process_memory_info is None:
        return None
    get_current_process.restype = ctypes.c_void_p
    get_process_memory_info.argtypes = [
        ctypes.c_void_p,
        ctypes.POINTER(_ProcessMemoryCounters),
        ctypes.c_uint32,
    ]
    get_process_memory_info.restype = ctypes.c_bool

    counters = _ProcessMemoryCounters()
    counters.length = ctypes.sizeof(counters)
    if not get_process_memory_info(
        get_current_process(), ctypes.byref(counters), ctypes.sizeof(counters)
    ):
        return None
    return int(counters.working_set_size)


class _FileTime(ctypes.Structure):
    _fields_ = [("low", ctypes.c_uint32), ("high", ctypes.c_uint32)]


class _MemoryStatusEx(ctypes.Structure):
    _fields_ = [
        ("length", ctypes.c_uint32),
        ("memory_load", ctypes.c_uint32),
        ("total_physical", ctypes.c_uint64),
        ("available_physical", ctypes.c_uint64),
        ("total_page_file", ctypes.c_uint64),
        ("available_page_file", ctypes.c_uint64),
        ("total_virtual", ctypes.c_uint64),
        ("available_virtual", ctypes.c_uint64),
        ("available_extended_virtual", ctypes.c_uint64),
    ]


class _ProcessMemoryCounters(ctypes.Structure):
    _fields_ = [
        ("length", ctypes.c_uint32),
        ("page_fault_count", ctypes.c_uint32),
        ("peak_working_set_size", ctypes.c_size_t),
        ("working_set_size", ctypes.c_size_t),
        ("quota_peak_paged_pool_usage", ctypes.c_size_t),
        ("quota_paged_pool_usage", ctypes.c_size_t),
        ("quota_peak_non_paged_pool_usage", ctypes.c_size_t),
        ("quota_non_paged_pool_usage", ctypes.c_size_t),
        ("pagefile_usage", ctypes.c_size_t),
        ("peak_pagefile_usage", ctypes.c_size_t),
    ]


def _filetime_value(value: _FileTime) -> int:
    return (int(value.high) << 32) | int(value.low)


def _format_timestamp(value: datetime) -> str:
    normalized = (
        value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)
    )
    return normalized.isoformat(timespec="seconds").replace("+00:00", "Z")
