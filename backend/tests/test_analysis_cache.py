from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from app.services import analysis_cache


def test_sanitize_error_for_model_handles_none():
    assert analysis_cache.sanitize_error_for_model(None) == "unknown"


def test_sanitize_error_for_model_collapses_newlines():
    err = ValueError("line1\nline2\rline3")
    assert analysis_cache.sanitize_error_for_model(err) == "line1 line2 line3"


def test_sanitize_error_for_model_truncates_long_messages():
    err = "x" * 500
    result = analysis_cache.sanitize_error_for_model(err)
    assert len(result) == analysis_cache._MAX_MODEL_ERROR_LEN + 1  # + ellipsis char
    assert result.endswith("…")


def test_sanitize_error_for_model_returns_unknown_for_blank():
    assert analysis_cache.sanitize_error_for_model("   ") == "unknown"


def test_format_analysis_failure_model_without_error():
    result = analysis_cache.format_analysis_failure_model("gemini-pro", "fallback")
    assert result == "gemini-pro:fallback"


def test_format_analysis_failure_model_with_error():
    result = analysis_cache.format_analysis_failure_model(
        "gemini-pro", "error_fallback", error="429 Resource exhausted"
    )
    assert result == "gemini-pro:error_fallback:429 Resource exhausted"


def test_format_analysis_failure_model_defaults_to_settings_when_no_model(monkeypatch):
    monkeypatch.setattr(analysis_cache.settings, "GEMINI_ANALYSIS_MODEL", "default-model")
    result = analysis_cache.format_analysis_failure_model("", "fallback")
    assert result == "default-model:fallback"


def test_is_retryable_failed_analysis_true_cases():
    assert analysis_cache.is_retryable_failed_analysis("gemini-pro:error_fallback:oops") is True
    assert analysis_cache.is_retryable_failed_analysis("gemini-pro:empty_fallback") is True


def test_is_retryable_failed_analysis_false_cases():
    assert analysis_cache.is_retryable_failed_analysis(None) is False
    assert analysis_cache.is_retryable_failed_analysis("fallback") is False
    assert analysis_cache.is_retryable_failed_analysis("gemini-pro") is False


def test_analysis_cache_is_valid_requires_content_and_matching_fingerprint():
    assert analysis_cache.analysis_cache_is_valid(None, "fp") is False
    assert analysis_cache.analysis_cache_is_valid({"content": ""}, "fp") is False
    assert (
        analysis_cache.analysis_cache_is_valid({"content": "x", "fingerprint": "other"}, "fp")
        is False
    )


def test_analysis_cache_is_valid_rejects_retryable_failure():
    cached = {"content": "x", "fingerprint": "fp", "model": "gemini:error_fallback:oops"}
    assert analysis_cache.analysis_cache_is_valid(cached, "fp") is False


def test_analysis_cache_is_valid_true_for_fresh_content():
    cached = {"content": "x", "fingerprint": "fp", "model": "gemini-pro"}
    assert analysis_cache.analysis_cache_is_valid(cached, "fp") is True


def test_canonical_json_is_stable_key_order():
    a = analysis_cache.canonical_json({"b": 1, "a": 2})
    b = analysis_cache.canonical_json({"a": 2, "b": 1})
    assert a == b == '{"a":2,"b":1}'


def test_snap_floats_for_fingerprint_rounds_nested_floats():
    obj = {"a": 12.30000000001, "b": [1.000000001, "x", None], "c": True}
    result = analysis_cache._snap_floats_for_fingerprint(obj)
    assert result == {"a": 12.3, "b": [1.0, "x", None], "c": True}


def test_fingerprint_context_is_deterministic():
    a = analysis_cache.fingerprint_context({"x": 1.0000001, "y": [1, 2]})
    b = analysis_cache.fingerprint_context({"y": [1, 2], "x": 1.0000002})
    assert a == b
    assert len(a) == 64  # sha256 hex digest


def test_clamp_to_two_sentences_returns_empty_for_blank():
    assert analysis_cache.clamp_to_two_sentences("") == ""
    assert analysis_cache.clamp_to_two_sentences("   ") == ""


def test_clamp_to_two_sentences_strips_bullets_and_limits_sentences():
    # Leading bullets are only stripped per-line, so each point needs its own line.
    text = "- First point.\n* Second point!\n1) Third point?"
    result = analysis_cache.clamp_to_two_sentences(text)
    assert result == "First point. Second point!"


def test_clamp_to_two_sentences_passthrough_when_short():
    assert analysis_cache.clamp_to_two_sentences("Just one sentence.") == "Just one sentence."


def test_get_cached_analysis_returns_data_when_present():
    fake_query = MagicMock()
    fake_query.execute.return_value = SimpleNamespace(data={"content": "x"})
    fake_db = MagicMock()
    fake_db.table.return_value.select.return_value.eq.return_value.eq.return_value.eq.return_value.maybe_single.return_value = fake_query

    result = analysis_cache.get_cached_analysis(fake_db, "athlete-1", "weekly", "scope-1")
    assert result == {"content": "x"}


def test_get_cached_analysis_returns_none_on_exception():
    fake_db = MagicMock()
    fake_db.table.side_effect = RuntimeError("db down")

    assert analysis_cache.get_cached_analysis(fake_db, "athlete-1", "weekly", "scope-1") is None


def test_upsert_analysis_calls_upsert_with_expected_conflict_target():
    fake_db = MagicMock()

    analysis_cache.upsert_analysis(
        fake_db, "athlete-1", "weekly", "scope-1", "fp", "content", "model-x"
    )

    fake_db.table.assert_called_once_with("athlete_analyses")
    _, kwargs = fake_db.table.return_value.upsert.call_args
    assert kwargs["on_conflict"] == "athlete_id,analysis_type,scope_key"


def test_upsert_analysis_swallows_errors():
    fake_db = MagicMock()
    fake_db.table.side_effect = RuntimeError("db down")

    analysis_cache.upsert_analysis(
        fake_db, "athlete-1", "weekly", "scope-1", "fp", "content", "model-x"
    )  # should not raise


def test_generate_gemini_analysis_returns_text_on_success():
    fake_response = SimpleNamespace(text="Great week overall.")
    with patch.object(
        analysis_cache._client.models, "generate_content", return_value=fake_response
    ) as mock_generate:
        text, model = analysis_cache.generate_gemini_analysis("prompt", "gemini-pro")

    assert text == "Great week overall."
    assert model == "gemini-pro"
    mock_generate.assert_called_once()


def test_generate_gemini_analysis_falls_back_on_404(monkeypatch):
    monkeypatch.setattr(analysis_cache.settings, "GEMINI_ANALYSIS_MODEL", "fallback-model")
    fake_response = SimpleNamespace(text="fallback text")

    calls = []

    def _fake_generate(model, contents):
        calls.append(model)
        if model == "bad-model":
            raise RuntimeError("404 NOT_FOUND")
        return fake_response

    with patch.object(analysis_cache._client.models, "generate_content", side_effect=_fake_generate):
        text, model = analysis_cache.generate_gemini_analysis("prompt", "bad-model")

    assert text == "fallback text"
    assert model == "fallback-model"
    assert calls == ["bad-model", "fallback-model"]


def test_generate_gemini_analysis_reraises_non_404_errors():
    with patch.object(
        analysis_cache._client.models, "generate_content", side_effect=RuntimeError("500 boom")
    ):
        with pytest.raises(RuntimeError, match="500 boom"):
            analysis_cache.generate_gemini_analysis("prompt", "gemini-pro")


def test_generate_gemini_analysis_raises_last_error_when_all_candidates_404(monkeypatch):
    monkeypatch.setattr(analysis_cache.settings, "GEMINI_ANALYSIS_MODEL", "fallback-model")
    with patch.object(
        analysis_cache._client.models, "generate_content", side_effect=RuntimeError("404 NOT_FOUND")
    ):
        with pytest.raises(RuntimeError, match="404 NOT_FOUND"):
            analysis_cache.generate_gemini_analysis("prompt", "bad-model")


def test_generate_gemini_analysis_no_duplicate_candidate_when_requested_equals_fallback(monkeypatch):
    monkeypatch.setattr(analysis_cache.settings, "GEMINI_ANALYSIS_MODEL", "gemini-pro")
    calls = []

    def _fake_generate(model, contents):
        calls.append(model)
        return SimpleNamespace(text="ok")

    with patch.object(analysis_cache._client.models, "generate_content", side_effect=_fake_generate):
        analysis_cache.generate_gemini_analysis("prompt", "gemini-pro")

    assert calls == ["gemini-pro"]  # fallback not appended since it equals the requested model


def test_snap_floats_for_fingerprint_passthrough_for_unrecognized_type():
    class _Custom:
        pass

    obj = _Custom()
    assert analysis_cache._snap_floats_for_fingerprint(obj) is obj


def test_clamp_to_two_sentences_strips_lone_bullet_marker_with_no_trailing_text():
    # A bullet marker alone (no separating space survives the outer .strip())
    # is left as-is by the per-line regex, which requires trailing whitespace.
    assert analysis_cache.clamp_to_two_sentences("-") == "-"
