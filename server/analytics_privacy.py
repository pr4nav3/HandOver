"""Small, dependency-free privacy guard for analytics metadata.

The learn loop deliberately emits metadata only. This guard makes that boundary fail closed if a future caller
accidentally passes a frame, token, stable device identifier, or an arbitrary object to an event sink.
"""

from __future__ import annotations

import math
from typing import Any, Mapping

FORBIDDEN_KEYS = {
    "authorization", "audio", "bytes", "camera_name", "clip", "data", "device_id", "device_name",
    "frame", "image", "ip", "ip_address", "jpeg", "name", "token", "video",
}
MAX_DEPTH = 6
MAX_ITEMS = 100
MAX_STRING = 4_096
_DROP = object()


def scrub_fields(fields: Mapping[str, Any]) -> tuple[dict[str, Any], int]:
    """Return JSON-safe analytics fields and how many values were dropped.

    Field names are matched exactly (so safe counters such as ``frame_seq`` remain useful). Nested containers are
    bounded to keep an accidental large object from turning one metadata event into meaningful work.
    """
    dropped = 0

    def clean(value: Any, depth: int) -> Any:
        nonlocal dropped
        if isinstance(value, (bytes, bytearray, memoryview)) or depth > MAX_DEPTH:
            dropped += 1
            return _DROP
        if value is None or isinstance(value, (bool, int)):
            return value
        if isinstance(value, float):
            if math.isfinite(value):
                return value
            dropped += 1
            return _DROP
        if isinstance(value, str):
            return value[:MAX_STRING]
        if isinstance(value, Mapping):
            out = {}
            for i, (key, item) in enumerate(value.items()):
                if i >= MAX_ITEMS:
                    dropped += 1
                    break
                name = str(key)
                if name.lower() in FORBIDDEN_KEYS:
                    dropped += 1
                    continue
                safe = clean(item, depth + 1)
                if safe is not _DROP:
                    out[name] = safe
            return out
        if isinstance(value, (list, tuple)):
            out = []
            for i, item in enumerate(value):
                if i >= MAX_ITEMS:
                    dropped += 1
                    break
                safe = clean(item, depth + 1)
                if safe is not _DROP:
                    out.append(safe)
            return out
        dropped += 1
        return _DROP

    out: dict[str, Any] = {}
    for i, (key, value) in enumerate(fields.items()):
        if i >= MAX_ITEMS:
            dropped += 1
            break
        name = str(key)
        if name.lower() in FORBIDDEN_KEYS:
            dropped += 1
            continue
        safe = clean(value, 0)
        if safe is not _DROP:
            out[name] = safe
    if dropped:
        out["privacy_dropped_fields"] = dropped
    return out, dropped
