from __future__ import annotations

from datetime import date, timedelta
from unittest.mock import MagicMock, patch

import pytest
from fastapi import HTTPException

from app.routers import analysis


def test_parse_day_rejects_malformed_and_out_of_range():
    assert analysis._parse_day(None) == date.today()
    assert analysis._parse_day(date.today().isoformat()) == date.today()
    for bad in ("not-a-date", "2000-01-01", (date.today() + timedelta(days=5)).isoformat()):
        with pytest.raises(HTTPException) as exc:
            analysis._parse_day(bad)
        assert exc.value.status_code == 422


def test_over_budget_serves_fallback_without_calling_the_llm():
    budget = MagicMock()
    budget.take.return_value = False
    with patch.object(analysis, "get_cached_analysis", return_value=None), patch.object(
        analysis, "generate_gemini_analysis"
    ) as llm, patch.object(analysis, "upsert_analysis") as upsert, patch.object(
        analysis, "_fallback_content", return_value="rule-based text"
    ):
        out = analysis._get_or_compute(MagicMock(), "a", "premium", "recovery", "2026-11-02", {}, "m", budget=budget)
    llm.assert_not_called()
    upsert.assert_not_called()  # not cached, so a real analysis is generated later
    assert out["note"] == "rate_limited" and out["content"] == "rule-based text"


def test_cache_hits_do_not_spend_budget():
    budget = MagicMock()
    with patch.object(analysis, "get_cached_analysis", return_value={"content": "c", "fingerprint": "x"}), patch.object(
        analysis, "analysis_cache_is_valid", return_value=True
    ):
        analysis._get_or_compute(MagicMock(), "a", "premium", "recovery", "2026-11-02", {}, "m", budget=budget)
    budget.take.assert_not_called()
