"""import_plan: one structured request reads the plan; code checks it and saves it."""
from __future__ import annotations

from datetime import date, datetime, timezone
from unittest.mock import MagicMock, patch

import pytest

from app.services import plan_import as pi

NOV1, NOV30 = date(2026, 11, 1), date(2026, 11, 30)


@pytest.fixture(autouse=True)
def _reset_state():
    pi._exhausted_until.clear()
    pi._athlete_imports.clear()
    yield
    pi._exhausted_until.clear()
    pi._athlete_imports.clear()


def _session(d, wd, title, sport="row", mins=60, focus="Endurance", blocks=None):
    return {"date": d, "weekday": wd, "title": title, "sport": sport, "duration_minutes": mins,
            "focus_zone": focus, "blocks": blocks or []}


def test_intervals_become_work_and_recovery_blocks_with_zones():
    blocks = [
        {"name": "Warmup", "minutes": 15, "zone": 2, "repeat": 1},
        {"name": "8 x 1:30", "minutes": 1.5, "zone": 5, "repeat": 8, "recovery_minutes": 1, "recovery_zone": 1},
        {"name": "Cooldown", "minutes": 10, "zone": 1, "repeat": 1},
    ]
    structure, total, filled = pi.build_structure(blocks, "VO2Max")
    work = [b for b in structure if b["name"].startswith("Work")]
    rest = [b for b in structure if b["name"].startswith("Recovery")]
    assert len(work) == 8 and all(b["duration_minutes"] == 1.5 and b["target_hr_zone"] == 5 for b in work)
    assert len(rest) == 7 and all(b["duration_minutes"] == 1 and b["target_hr_zone"] == 1 for b in rest)
    assert total == 15 + 8 * 1.5 + 7 + 10
    assert filled == 0


def test_missing_zone_is_filled_from_the_focus():
    structure, _, filled = pi.build_structure([{"name": "Main", "minutes": 40, "repeat": 1}], "Threshold")
    assert structure[0]["target_hr_zone"] == 4 and filled == 1


def test_checks_reject_wrong_weekday_out_of_range_and_duplicates():
    raw = [
        _session("2026-11-02", "Monday", "Cat 1", "bike", 90),
        _session("2026-11-03", "Wednesday", "Team ST", "strength"),  # Nov 3 is a Tuesday
        _session("2026-12-02", "Wednesday", "Cat 1", "bike", 90),  # outside the range
        _session("2026-11-02", "Monday", "cat 1", "bike", 90),  # listed twice
    ]
    ok, skipped, _ = pi.check_sessions(raw, NOV1, NOV30)
    assert [(s["date"], s["title"]) for s in ok] == [("2026-11-02", "Cat 1")]
    reasons = {s["reason"] for s in skipped}
    assert any("is a Tuesday" in r for r in reasons)
    assert "outside the import range" in reasons and "listed twice" in reasons


def test_strength_has_no_blocks_and_recovery_focus():
    blocks = [{"name": "Squat", "minutes": 20, "zone": 3, "repeat": 1}]
    ok, _, _ = pi.check_sessions([_session("2026-11-02", "Mon", "Team ST", "strength", 60, "Tempo", blocks)], NOV1, NOV30)
    assert ok[0]["structure"] == [] and ok[0]["focus_zone"] == "Recovery"


def test_notes_get_a_real_multiline_table():
    md = pi.notes_markdown("Smooth.", [{"name": "8 x 1:30", "minutes": 1.5, "zone": 5, "repeat": 8, "recovery_minutes": 1}], "VO2Max")
    lines = md.split("\n")
    assert lines[0] == "Smooth." and lines[2].startswith("| Phase |")
    assert "| 8 x 1:30 | 8 x 1:30 / 1 min easy | Z5 |" in md


def test_sources_come_from_the_conversation():
    history = [
        {"role": "user", "content": "here", "attachments": [{"name": "Plan.docx", "content": "WEEK 1 ..."}], "image_urls": []},
        {"role": "ai", "content": "ok"},
        {"role": "user", "content": "now december", "image_urls": []},
    ]
    text, images = pi.plan_sources(history, "now december", None)
    assert "Plan.docx" in text and "WEEK 1" in text and images == []
    assert pi.plan_sources(history, "x", "other.xlsx")[0] == ""


def _resp(parsed):
    r = MagicMock()
    r.parsed = parsed
    return r


def test_daily_quota_falls_through_to_the_next_model_and_is_remembered():
    calls = []

    def gen(*, model, contents, config):
        calls.append(model)
        if model == "gemini-3.8-flash":
            raise RuntimeError("429 RESOURCE_EXHAUSTED: GenerateRequestsPerDayPerProjectPerModel quota per day")
        return _resp({"sessions": []})

    client = MagicMock()
    client.models.generate_content.side_effect = gen
    with patch.object(pi, "_import_client", return_value=client), patch.object(pi.gemini_quota, "wait_for_slot"), \
            patch.object(pi.settings, "GEMINI_IMPORT_MODELS", "gemini-3.8-flash,gemini-3.6-flash"):
        now = datetime(2026, 11, 3, 23, 0, tzinfo=timezone.utc)
        parsed, model, _ = pi.call_import_model(["x"], now=now)
        assert model == "gemini-3.6-flash" and parsed == {"sessions": []}
        pi.call_import_model(["x"], now=now)
    assert calls == ["gemini-3.8-flash", "gemini-3.6-flash", "gemini-3.6-flash"]


class _DB:
    """Records the replace range and the inserts."""

    def __init__(self):
        self.deleted_range = None
        self.ops = []

    def table(self, _):
        q = MagicMock()
        state = {}
        q.delete.side_effect = lambda: (state.update(op="delete"), q)[1]
        q.eq.return_value = q
        q.in_.return_value = q
        q.gte.side_effect = lambda c, v: (state.update(gte=v), q)[1]
        q.lte.side_effect = lambda c, v: (state.update(lte=v), q)[1]

        def execute():
            if state.get("op") == "delete":
                self.deleted_range = (state["gte"], state["lte"])
                return MagicMock(data=[{"id": "a"}, {"id": "b"}])
            return MagicMock(data=[])

        q.execute.side_effect = execute
        return q


def _run(parsed, db=None, args=None):
    db = db or _DB()
    history = [{"role": "user", "content": "put it in", "attachments": [{"name": "p.docx", "content": "plan"}]}]
    saved = []

    def fake_schedule(item, *, athlete_id, db):
        saved.append(item)
        return {"planned_date": item["date"], "title": item["title"]}

    with patch.object(pi, "call_import_model", return_value=(parsed, "gemini-3.8-flash", [])), \
            patch.object(pi, "handle_schedule_workout", side_effect=fake_schedule):
        res = pi.run_import(args or {"start_date": "2026-11-01", "end_date": "2026-12-31", "rules": "cat 1 = bike"},
                            athlete_id="ath", db=db, history=history, current_message="put it in")
    return res, db, saved


def test_import_replaces_only_the_dates_it_covers_and_reports_by_weekday():
    parsed = {"sessions": [
        _session("2026-11-02", "Monday", "Cat 1", "bike", 90),
        _session("2026-11-02", "Monday", "Team ST", "strength"),
        _session("2026-11-28", "Saturday", "Speed 8 x 1:30", "row", 60, "VO2Max",
                 [{"name": "8 x 1:30", "minutes": 1.5, "zone": 5, "repeat": 8, "recovery_minutes": 1}]),
    ], "unclear": ["Nov 26: Thanksgiving, nothing listed"]}
    res, db, saved = _run(parsed)
    assert res["status"] == "imported" and res["saved_count"] == 3
    # Only Nov 2..Nov 28 is replaced: December (not in this answer) keeps its sessions.
    assert db.deleted_range == ("2026-11-02", "2026-11-28")
    assert res["by_weekday"]["Monday"] == "Cat 1 x1, Team ST x1"
    assert res["by_weekday"]["Wednesday"] == "nothing"
    assert res["unclear"] == ["Nov 26: Thanksgiving, nothing listed"]
    speed = next(s for s in saved if s["title"].startswith("Speed"))
    assert sum(1 for b in speed["structure"] if b["name"].startswith("Work")) == 8


def test_nothing_is_deleted_when_the_reader_fails():
    db = _DB()
    with patch.object(pi, "call_import_model", return_value=(None, None, ["gemini-3.8-flash: 429"])):
        res = pi.run_import({"start_date": "2026-11-01", "end_date": "2026-11-30", "rules": ""}, athlete_id="ath", db=db,
                            history=[{"role": "user", "attachments": [{"name": "p", "content": "plan"}]}], current_message="")
    assert res["error"] == "plan_reader_unavailable" and db.deleted_range is None


def test_no_plan_attached_and_range_limits():
    res = pi.run_import({"start_date": "2026-11-01", "end_date": "2026-11-30"}, athlete_id="a", db=_DB(), history=[], current_message="hi")
    assert res["error"] == "no_plan_attached"
    res = pi.run_import({"start_date": "2026-11-01", "end_date": "2027-02-01"}, athlete_id="a", db=_DB(), history=[], current_message="")
    assert "62 days" in res["error"]


def test_per_athlete_daily_cap():
    parsed = {"sessions": [_session("2026-11-02", "Monday", "Cat 1", "bike", 90)]}
    with patch.object(pi.settings, "PLAN_IMPORTS_PER_DAY", 2):
        assert _run(parsed)[0]["status"] == "imported"
        assert _run(parsed)[0]["status"] == "imported"
        assert _run(parsed)[0]["error"] == "daily_import_limit"


def test_team_st_is_strength_even_when_the_reader_says_row():
    ok, _, _ = pi.check_sessions([_session("2026-11-02", "Monday", "Team ST (Ferris)", "row", 60)], NOV1, NOV30)
    assert ok[0]["sport"] == "strength" and ok[0]["structure"] == []
    ok, _, _ = pi.check_sessions([_session("2026-11-02", "Monday", "Steady state", "row", 60)], NOV1, NOV30)
    assert ok[0]["sport"] == "row"


def test_a_busy_model_gets_one_retry_and_strong_models_think_low():
    calls = []

    def gen(*, model, contents, config):
        calls.append((model, config.thinking_config.thinking_level if config.thinking_config else None))
        if len(calls) == 1:
            raise RuntimeError("503 UNAVAILABLE. This model is currently experiencing high demand.")
        return _resp({"sessions": []})

    client = MagicMock()
    client.models.generate_content.side_effect = gen
    with patch.object(pi, "_import_client", return_value=client), patch.object(pi.gemini_quota, "wait_for_slot"), \
            patch.object(pi, "_BUSY_RETRY_SEC", (0, 0)), patch.object(pi.settings, "GEMINI_IMPORT_MODELS", "gemini-3.8-flash"):
        _, model, _ = pi.call_import_model(["x"])
    assert model == "gemini-3.8-flash"
    assert [c[0] for c in calls] == ["gemini-3.8-flash", "gemini-3.8-flash"]
    assert str(calls[0][1]).endswith("LOW")


def test_the_chat_model_is_not_a_fallback_by_default():
    with patch.object(pi.settings, "GEMINI_IMPORT_MODELS", "gemini-3.8-flash,gemini-3.6-flash"), \
            patch.object(pi.settings, "GEMINI_MODEL", "gemini-3.5-flash-lite"):
        assert pi.import_models() == ["gemini-3.8-flash", "gemini-3.6-flash"]
        with patch.object(pi.settings, "PLAN_IMPORT_CHAT_FALLBACK", True):
            assert pi.import_models()[-1] == "gemini-3.5-flash-lite"


def test_busy_models_get_three_tries_then_nothing_changes():
    client = MagicMock()
    client.models.generate_content.side_effect = RuntimeError("503 UNAVAILABLE high demand")
    with patch.object(pi, "_import_client", return_value=client), patch.object(pi.gemini_quota, "wait_for_slot"), \
            patch.object(pi, "_BUSY_RETRY_SEC", (0, 0)), patch.object(pi.settings, "GEMINI_IMPORT_MODELS", "a,b"), \
            patch.object(pi.settings, "PLAN_IMPORT_CHAT_FALLBACK", False):
        parsed, model, errors = pi.call_import_model(["x"])
    assert parsed is None and model is None
    assert client.models.generate_content.call_count == 6


def test_merged_am_pm_sessions_are_flagged():
    parsed = {"sessions": [_session("2026-11-02", "Monday", "AM - Cat 1 cross-train PM - Team ST - 4:20 Ferris", "bike", 90)]}
    res, _, _ = _run(parsed)
    assert res["unclear"][0].startswith("1 sessions still combine an AM and a PM")


def test_a_session_with_blocks_is_as_long_as_its_blocks():
    s = _session("2026-11-04", "Wednesday", "Cat 1 cross-train", "bike", 90, "Endurance",
                 [{"name": "Steady", "minutes": 60, "zone": 2, "repeat": 1}])
    ok, _, _ = pi.check_sessions([s], NOV1, NOV30)
    assert ok[0]["duration_minutes"] == 60
