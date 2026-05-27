"""Structured performance logging for hot paths (streams, coach)."""

from __future__ import annotations

import json
import logging
import time
from contextlib import contextmanager
from typing import Any, Iterator

logger = logging.getLogger(__name__)


def payload_bytes(data: Any) -> int:
    try:
        return len(json.dumps(data, default=str).encode("utf-8"))
    except Exception:
        return 0


@contextmanager
def perf_span(name: str, **fields: Any) -> Iterator[dict[str, Any]]:
    """Log duration_ms and optional fields on exit."""
    start = time.perf_counter()
    extra = dict(fields)
    try:
        yield extra
    finally:
        extra["duration_ms"] = round((time.perf_counter() - start) * 1000, 1)
        logger.info("[perf] %s %s", name, extra)
