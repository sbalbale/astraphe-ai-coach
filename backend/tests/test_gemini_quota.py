from __future__ import annotations

import pytest

from app.config import settings
from app.services import gemini_quota


@pytest.fixture(autouse=True)
def _reset_quota_state(monkeypatch):
    """Every test gets a clean call-history and starts as LLM_PROVIDER=gemini
    (the only mode wait_for_slot actually enforces anything in)."""
    monkeypatch.setattr(settings, "LLM_PROVIDER", "gemini")
    gemini_quota._call_times.clear()
    yield
    gemini_quota._call_times.clear()


def _fake_clock(monkeypatch, start: float = 1_000.0):
    """Returns a mutable [now] and patches time.monotonic()/time.sleep() so
    wait_for_slot()'s blocking loop is fully deterministic — sleep() advances
    the fake clock by the requested amount instead of actually waiting."""
    now = [start]
    monkeypatch.setattr(gemini_quota.time, "monotonic", lambda: now[0])

    def fake_sleep(seconds: float) -> None:
        now[0] += seconds

    monkeypatch.setattr(gemini_quota.time, "sleep", fake_sleep)
    return now


def test_allows_calls_up_to_the_model_rpm_limit_without_blocking(monkeypatch):
    now = _fake_clock(monkeypatch)
    model = "gemma-4-26b-a4b-it"
    limit = gemini_quota._rpm_limit(model)
    assert limit > 0

    for _ in range(limit):
        gemini_quota.wait_for_slot(model, max_wait_sec=5.0)

    # None of the allowed calls should have needed to wait — clock unchanged.
    assert now[0] == 1_000.0
    assert len(gemini_quota._call_times[model]) == limit


def test_blocks_and_then_succeeds_once_the_window_advances_past_the_call_that_ages_out(monkeypatch):
    now = _fake_clock(monkeypatch)
    model = "gemma-4-26b-a4b-it"
    limit = gemini_quota._rpm_limit(model)

    for _ in range(limit):
        gemini_quota.wait_for_slot(model, max_wait_sec=5.0)

    # One more call is over budget — fake_sleep advances the clock each
    # iteration, so this resolves once the oldest call ages out of the 60s
    # window rather than raising, given a generous max_wait_sec.
    gemini_quota.wait_for_slot(model, max_wait_sec=gemini_quota._WINDOW_SEC + 5.0)
    assert now[0] >= 1_000.0 + gemini_quota._WINDOW_SEC


def test_raises_quota_exceeded_when_the_wait_would_exceed_max_wait_sec(monkeypatch):
    _fake_clock(monkeypatch)
    model = "gemma-4-26b-a4b-it"
    limit = gemini_quota._rpm_limit(model)

    for _ in range(limit):
        gemini_quota.wait_for_slot(model, max_wait_sec=5.0)

    with pytest.raises(gemini_quota.GeminiQuotaExceededError) as exc_info:
        gemini_quota.wait_for_slot(model, max_wait_sec=0.0)

    err = exc_info.value
    assert err.model == model
    assert err.retry_after_sec > 0
    # ai_coach.py's _should_fallback_chat_model() matches on this exact
    # substring to decide whether to try a fallback model — see
    # GeminiQuotaExceededError's docstring.
    assert "quota exceeded" in str(err).lower()


def test_old_timestamps_expire_after_the_60s_window(monkeypatch):
    now = _fake_clock(monkeypatch)
    model = "gemma-4-26b-a4b-it"
    limit = gemini_quota._rpm_limit(model)

    for _ in range(limit):
        gemini_quota.wait_for_slot(model, max_wait_sec=5.0)

    # Jump the clock forward past the window without going through sleep()
    # (simulates real wall-clock time passing between requests, not this
    # process waiting) — the old timestamps must no longer count.
    now[0] += gemini_quota._WINDOW_SEC + 1.0
    gemini_quota.wait_for_slot(model, max_wait_sec=0.0)  # must not raise
    assert len(gemini_quota._call_times[model]) == 1


def test_unknown_model_falls_back_to_default_rpm():
    assert gemini_quota._rpm_limit("some-model-not-in-the-table") == gemini_quota._DEFAULT_RPM


def test_empty_model_name_is_a_noop(monkeypatch):
    now = _fake_clock(monkeypatch)
    gemini_quota.wait_for_slot("", max_wait_sec=0.0)  # must not raise or record anything
    assert now[0] == 1_000.0
    assert "" not in gemini_quota._call_times


def test_noop_when_llm_provider_is_not_gemini(monkeypatch):
    monkeypatch.setattr(settings, "LLM_PROVIDER", "openai")
    # A local model name that isn't in _MODEL_RPM would otherwise fall back
    # to _DEFAULT_RPM and start blocking — must not happen for LLM_PROVIDER=openai.
    for _ in range(50):
        gemini_quota.wait_for_slot("gemma4-26b-a4b-qat-128k", max_wait_sec=0.01)
    assert not gemini_quota._call_times
