"""
Request-per-minute guardrail for Gemini's free-tier quotas, shared by every API
replica through Redis (in-process when Redis is unavailable).

Google AI Studio's free tier caps requests-per-minute *per model*, and for
the models this app runs on it's tight — 30 RPM for the Gemma models used
for chat and insights, 15 for the Gemini Flash Lite models. A single coach
turn alone can burn several of those 30: the agentic loop's multi-hop tool
calling plus a separate title-generation call (generate_coach_conversation_title)
plus a separate memory-extraction call (extract_and_save_memories) all fire
against the *same* model within a few seconds of each other. Retrying after
a 429 (see ai_coach.py's is_transient handling) doesn't help within the same
60s window — the quota genuinely isn't there yet — so the actual fix is
spacing calls out to stay under the cap *before* calling the API, not
reacting after Google already said no.

This tracks calls per model name (not per feature/endpoint) since the quota
itself is per model — chat's fallback model and insights' primary model can
be the same underlying model, and they need to share one budget.

Deliberately RPM-only, not TPM/RPD: RPM is exact and free to track (a
timestamp), while TPM would need either an exact tokenizer call before every
request (another API round trip) or an estimate accurate enough not to be
misleading, and at this app's scale RPM is the tighter, more frequently-hit
constraint of the two anyway. RPD (14.4K/day for the Gemma models) isn't
remotely close to being the binding constraint at this app's scale.
"""
from __future__ import annotations

import logging
import threading
import time
from collections import deque

from app.config import settings

logger = logging.getLogger(__name__)

_WINDOW_SEC = 60.0

# Conservative defaults — ~90% of Google's stated free-tier RPM (checked
# 2026-08-06 in AI Studio's quota panel) so a couple of concurrent requests
# don't tip the *real* account limit over: the count covers every replica of this
# API (via Redis), not other traffic against the same key.
# These are a starting point, not synced live from Google — revisit if the
# free tier's numbers change.
_DEFAULT_RPM = 10
_MODEL_RPM: dict[str, int] = {
    "gemini-3.1-flash-lite": 13,
    "gemini-3.5-flash-lite": 13,
    # Plan import models: 5 RPM (and ~20/day) on the free tier.
    "gemini-3.8-flash": 4,
    "gemini-3-flash-preview": 4,
    "gemini-3.6-flash": 4,
    "gemma-4-31b-it": 27,
    "gemma-4-26b-a4b-it": 27,
    "gemini-embedding-2": 90,
}

_lock = threading.Lock()
_call_times: dict[str, deque[float]] = {}


class GeminiQuotaExceededError(Exception):
    """Raised by wait_for_slot() when a model's RPM budget won't free up in time."""

    def __init__(self, model: str, retry_after_sec: float):
        self.model = model
        self.retry_after_sec = max(0.0, retry_after_sec)
        # Deliberately phrased to contain "quota exceeded" — ai_coach.py's
        # existing _should_fallback_chat_model() string check already
        # matches that substring, so raising this slots straight into its
        # "try the next candidate model" path with no extra wiring there.
        super().__init__(
            f"Gemini quota exceeded for {model!r} (RPM); retry in "
            f"{self.retry_after_sec:.0f}s"
        )


def _rpm_limit(model: str) -> int:
    return _MODEL_RPM.get(model, _DEFAULT_RPM)


def wait_for_slot(model: str, max_wait_sec: float = 20.0) -> None:
    """
    Block (sleeping in short increments) until it's safe to call `model`
    without exceeding its tracked RPM budget, and record the call the moment
    a slot is granted. Raises GeminiQuotaExceededError instead of blocking
    past max_wait_sec — callers should treat that the same as a 429: fall
    back to another model if one's configured, or surface a clear
    rate-limited message rather than hang the request.

    Call this immediately before generate_content() — not "at some point
    before" — so the recorded timestamp reflects when the call actually
    happens, not when the caller started getting ready to make it.
    """
    if not model:
        return
    # This tracker only knows Google AI Studio's free-tier RPM numbers — a
    # self-hosted OpenAI-compatible endpoint (LLM_PROVIDER=openai) has no
    # such constraint, so don't throttle it against a Gemini-derived default.
    if (settings.LLM_PROVIDER or "gemini").strip().lower() != "gemini":
        return
    # Nor the coach chat's self-hosted model (CHAT_LLM_PROVIDER=openai).
    from app.services.llm_provider import is_chat_openai_model

    if is_chat_openai_model(model):
        return
    # Likewise, a paid/billed Gemini key has real quota — this guardrail is
    # a *guess* at limits that may not even apply. Reactive handling of an
    # actual 429/RESOURCE_EXHAUSTED (retry, fall back to
    # GEMINI_FALLBACK_MODEL — see ai_coach.py's is_transient handling)
    # stays on regardless; that's responding to a real error, not
    # preemptively assuming one.
    if not settings.GEMINI_FREE_TIER:
        return
    limit = _rpm_limit(model)
    deadline = time.monotonic() + max_wait_sec
    while True:
        wait_needed = _take_slot(model, limit)
        if wait_needed is None:
            return
        now = time.monotonic()
        if now + wait_needed > deadline:
            raise GeminiQuotaExceededError(model, wait_needed)
        time.sleep(max(0.05, min(wait_needed, 1.0)))


# Sliding window shared by every API replica: the quota is per Google API key, and
# per-process counting let two replicas spend twice the RPM between them (then 429s).
# Redis's own clock (TIME) keeps replicas' clocks out of it. Returns {1, 0} when the
# slot is taken, else {0, ms until the oldest call leaves the window}.
_SLOT_LUA = """
local key    = KEYS[1]
local window = tonumber(ARGV[1])
local limit  = tonumber(ARGV[2])
local member = ARGV[3]
local t = redis.call('TIME')
local now = tonumber(t[1]) * 1000 + math.floor(tonumber(t[2]) / 1000)
redis.call('ZREMRANGEBYSCORE', key, '-inf', now - window)
if redis.call('ZCARD', key) < limit then
    redis.call('ZADD', key, now, member)
    redis.call('PEXPIRE', key, window + 1000)
    return {1, 0}
end
local oldest = redis.call('ZRANGE', key, 0, 0, 'WITHSCORES')
return {0, window - (now - tonumber(oldest[2]))}
"""


def _take_slot(model: str, limit: int) -> float | None:
    """Record a call if the window has room (None), else the seconds to wait."""
    from app.core.redis import get_sync_redis

    r = get_sync_redis()
    if r is not None:
        try:
            import os

            ok, wait_ms = r.eval(
                _SLOT_LUA, 1, f"gemini_rpm:{model}", int(_WINDOW_SEC * 1000), limit, os.urandom(6).hex()
            )
            return None if int(ok) == 1 else max(0.0, float(wait_ms) / 1000.0)
        except Exception as exc:  # Redis down: this process's own count (the old behaviour)
            logger.warning("Gemini quota via Redis failed, counting in-process: %s", exc)
    with _lock:
        now = time.monotonic()
        dq = _call_times.setdefault(model, deque())
        while dq and now - dq[0] >= _WINDOW_SEC:
            dq.popleft()
        if len(dq) < limit:
            dq.append(now)
            return None
        return _WINDOW_SEC - (now - dq[0])
