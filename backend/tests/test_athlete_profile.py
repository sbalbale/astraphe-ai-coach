"""The coach's update_profile tool (app.services.athlete_profile.update_profile_from_coach),
and the web_search tool reaching the self-hosted chat model."""

from __future__ import annotations

from datetime import date
from types import SimpleNamespace

import pytest

from app.services import athlete_profile, coach_tools


class _Query:
    def __init__(self, db, table):
        self.db, self.table, self.op, self.payload = db, table, "select", None

    def select(self, *_a, **_k):
        return self

    def update(self, payload):
        self.op, self.payload = "update", payload
        return self

    def eq(self, *_a, **_k):
        return self

    def maybe_single(self):
        return self

    def single(self):
        return self

    def execute(self):
        assert self.table == "athletes"
        if self.op == "update":
            self.db.updates.append(self.payload)
            self.db.row.update(self.payload)
            return SimpleNamespace(data=[dict(self.db.row)])
        return SimpleNamespace(data=dict(self.db.row))


class _Db:
    def __init__(self, **row):
        self.row = {
            "id": "a1",
            "ftp_watts": 250,
            "threshold_pace": "4:30",
            "measurement_units": "metric",
            "threshold_hr": 165,
            "max_hr": 190,
            "resting_hr": 48,
            "hr_zone_method": "lthr",
            "notification_settings": None,
            **row,
        }
        self.updates: list[dict] = []

    def table(self, name):
        return _Query(self, name)


@pytest.fixture
def side_effects(monkeypatch):
    """Record anchor history / re-scoring / weight / cache calls instead of running them."""
    calls: dict[str, list] = {"anchor": [], "rescore": [], "weight": [], "caches": []}
    import app.dependencies as deps
    import app.services.time_utils as tu
    from app.services import anchor_history

    monkeypatch.setattr(
        anchor_history, "record_change", lambda db, aid, vals, day: calls["anchor"].append((vals["ftp_watts"], day))
    )
    monkeypatch.setattr(deps, "get_admin_db", lambda: object())
    monkeypatch.setattr(tu, "athlete_local_date", lambda db, aid: date(2026, 11, 9))
    monkeypatch.setattr(athlete_profile, "_rescore_from", lambda aid, since: calls["rescore"].append(since))
    monkeypatch.setattr(
        athlete_profile.threading,
        "Thread",
        lambda target, args, daemon: SimpleNamespace(start=lambda: target(*args)),
    )
    monkeypatch.setattr(athlete_profile, "record_manual_weight_sync", lambda db, aid, kg: calls["weight"].append(kg))
    monkeypatch.setattr(athlete_profile, "_invalidate_profile_caches_sync", lambda aid: calls["caches"].append(aid))
    return calls


def test_ftp_change_records_history_rescores_and_reports_old_to_new(side_effects):
    db = _Db()
    out = athlete_profile.update_profile_from_coach(db, "a1", {"ftp_watts": 265})
    assert out["status"] == "updated"
    assert out["changed"] == {"ftp_watts": {"from": 250, "to": 265}}
    assert "re-scored" in out["note"]
    assert side_effects["anchor"] == [(265, date(2026, 11, 9))]
    assert side_effects["rescore"] == [date(2026, 11, 9)]
    assert side_effects["caches"] == ["a1"]


def test_hr_change_marks_it_manual_and_returns_new_zones(side_effects):
    db = _Db()
    out = athlete_profile.update_profile_from_coach(db, "a1", {"threshold_hr": 170, "max_hr": 195})
    assert db.updates[0]["threshold_hr_source"] == "manual"
    assert db.updates[0]["max_hr_source"] == "manual"
    assert set(out["changed"]) == {"threshold_hr", "max_hr"}
    assert out["hr_zones"] and all("min_bpm" in z for z in out["hr_zones"])
    assert side_effects["anchor"] == [] and side_effects["rescore"] == []  # HR isn't a dated anchor


def test_weight_is_also_recorded_as_todays_reading(side_effects):
    db = _Db(weight_kg=80.0)
    out = athlete_profile.update_profile_from_coach(db, "a1", {"weight_kg": 78.5})
    assert out["changed"] == {"weight_kg": {"from": 80.0, "to": 78.5}}
    assert side_effects["weight"] == [78.5]


def test_out_of_range_value_is_rejected_without_writing(side_effects):
    db = _Db()
    out = athlete_profile.update_profile_from_coach(db, "a1", {"ftp_watts": 2000})
    assert out["error"].startswith("invalid_value") and "ftp_watts" in out["error"]
    assert db.updates == []


def test_bad_units_are_rejected(side_effects):
    db = _Db()
    out = athlete_profile.update_profile_from_coach(db, "a1", {"measurement_units": "furlongs"})
    assert "measurement_units" in out["error"]
    assert db.updates == []


def test_fields_the_coach_may_not_change_are_ignored(side_effects):
    db = _Db()
    out = athlete_profile.update_profile_from_coach(db, "a1", {"display_name": "Bob", "date_of_birth": "1990-01-01"})
    assert out["error"].startswith("nothing_to_change")
    assert db.updates == []


def test_notification_change_keeps_the_other_settings(side_effects):
    saved = {"v": 2, "types": {"weekly": {"on": True, "opt": "Sun", "push": True}, "ready": {"on": False}}}
    db = _Db(notification_settings=saved)
    out = athlete_profile.update_profile_from_coach(
        db, "a1", {"notifications": {"weekly": {"opt": "Mon"}}, "quiet_hours": {"from": "21:30"}}
    )
    stored = db.updates[0]["notification_settings"]
    assert stored["types"]["weekly"]["opt"] == "Mon"
    assert stored["types"]["ready"]["on"] is False  # untouched
    assert stored["quiet"]["from"] == "21:30" and stored["quiet"]["to"] == "07:00"
    assert out["status"] == "updated"


def test_same_value_reports_unchanged(side_effects):
    db = _Db()
    out = athlete_profile.update_profile_from_coach(db, "a1", {"ftp_watts": 250})
    assert out == {"status": "unchanged", "changed": {}}
    assert side_effects["rescore"] == []


def test_normalize_profile_update_matches_settings_screen_rules():
    assert athlete_profile.normalize_profile_update({"time_format": "24-hour"})["time_format"] == "24h"
    assert athlete_profile.normalize_profile_update({"hr_zone_method": "max_hr_percent"})["hr_zone_method"] == "max_hr"
    assert athlete_profile.normalize_profile_update({"max_hr": None})["max_hr_source"] is None
    with pytest.raises(athlete_profile.ProfileValueError):
        athlete_profile.normalize_profile_update({"gender": "x"})


def test_update_profile_tool_is_offered():
    names = {d.name for t in coach_tools.TOOLS for d in (getattr(t, "function_declarations", None) or [])}
    assert "update_profile" in names
    assert "update_profile" in coach_tools.TOOL_HANDLERS


def _fn_decl_names(tools) -> set[str]:
    return {d.name for t in tools for d in (getattr(t, "function_declarations", None) or [])}


def _has_google_search(tools) -> bool:
    return any(getattr(t, "google_search", None) is not None for t in tools)


def test_self_hosted_chat_model_alone_gets_web_search(monkeypatch):
    """The chat model on the OpenAI-compatible endpoint can't use Google Search (the request
    translation drops it), so it must get web_search even with no Gemini 3 fallback."""
    from app.services import llm_provider

    monkeypatch.setattr(coach_tools.settings, "GEMINI_FREE_TIER", False)
    monkeypatch.setattr(coach_tools.settings, "SEARXNG_URL", "http://searxng:8888")
    monkeypatch.setattr(llm_provider, "is_chat_openai_model", lambda m: m == "qwen-chat")
    tools = coach_tools.tools_for_models(["qwen-chat"])
    assert not _has_google_search(tools)
    assert "web_search" in _fn_decl_names(tools)
    # Production's pairing: the chat model with a Gemini 3 fallback on the free tier.
    monkeypatch.setattr(coach_tools.settings, "GEMINI_FREE_TIER", True)
    assert "web_search" in _fn_decl_names(coach_tools.tools_for_models(["qwen-chat", "gemini-3.1-flash-lite"]))
