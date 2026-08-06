"""
In-process request-per-minute guardrail for Gemini's free-tier quotas.

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

import threading
import time
from collections import deque

from app.config import settings

_WINDOW_SEC = 60.0

# Conservative defaults — ~90% of Google's stated free-tier RPM (checked
# 2026-08-06 in AI Studio's quota panel) so a couple of concurrent requests
# don't tip the *real* account limit over, since this tracker only sees
# requests this process makes, not other traffic against the same key.
# These are a starting point, not synced live from Google — revisit if the
# free tier's numbers change.
_DEFAULT_RPM = 10
_MODEL_RPM: dict[str, int] = {
    "gemini-3.1-flash-lite": 13,
    "gemini-3.5-flash-lite": 13,
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
        with _lock:
            now = time.monotonic()
            dq = _call_times.setdefault(model, deque())
            while dq and now - dq[0] >= _WINDOW_SEC:
                dq.popleft()
            if len(dq) < limit:
                dq.append(now)
                return
            wait_needed = _WINDOW_SEC - (now - dq[0])
        if now + wait_needed > deadline:
            raise GeminiQuotaExceededError(model, wait_needed)
        time.sleep(max(0.05, min(wait_needed, 1.0)))
