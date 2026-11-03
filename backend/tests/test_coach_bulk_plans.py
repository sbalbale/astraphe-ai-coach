"""Importing a multi-week plan: photos reach the model, batch scheduling, step budget, wrap-up."""
from __future__ import annotations

from unittest.mock import MagicMock, patch

from app.services import ai_coach, coach_tools


# --- photos -------------------------------------------------------------------------

SIGNED = "https://api.example.com/storage/v1/object/sign/coach-uploads/coach/u1/c1/123-ab.jpg?token=xyz"


def test_coach_upload_path_only_accepts_our_bucket():
    assert ai_coach._coach_upload_path(SIGNED) == "coach/u1/c1/123-ab.jpg"
    assert ai_coach._coach_upload_path("https://evil.example.com/a.jpg") is None
    assert ai_coach._coach_upload_path(
        "https://x/storage/v1/object/sign/coach-uploads/coach/u1/../u2/a.jpg"
    ) is None
    assert ai_coach._coach_upload_path("https://x/storage/v1/object/sign/other-bucket/coach/u1/a.jpg") is None


def test_load_image_parts_fetches_signed_urls_from_our_own_supabase():
    resp = MagicMock(content=b"\xff\xd8jpeg")
    with patch.object(ai_coach.httpx, "get", return_value=resp) as get, patch.object(
        ai_coach.settings, "SUPABASE_URL", "http://internal-supabase:8000"
    ):
        parts = ai_coach._load_image_parts(MagicMock(), [SIGNED, "https://elsewhere/x.png"])
    # Host comes from settings, not from the stored URL; only the sign path + token is reused.
    get.assert_called_once()
    assert get.call_args[0][0] == "http://internal-supabase:8000/storage/v1/object/sign/coach-uploads/coach/u1/c1/123-ab.jpg?token=xyz"
    assert len(parts) == 1
    assert parts[0].inline_data.mime_type == "image/jpeg"


def test_load_image_parts_without_a_token_uses_the_users_client():
    db = MagicMock()
    db.storage.from_.return_value.download.return_value = b"png"
    url = "https://x/storage/v1/object/authenticated/coach-uploads/coach/u1/c1/a.png"
    assert len(ai_coach._load_image_parts(db, [url])) == 1
    db.storage.from_.return_value.download.assert_called_once_with("coach/u1/c1/a.png")


def test_load_image_parts_skips_failures_and_huge_files():
    big = MagicMock(content=b"x" * (ai_coach._MAX_IMAGE_BYTES + 1))
    with patch.object(ai_coach.httpx, "get", side_effect=[RuntimeError("404"), big]):
        assert ai_coach._load_image_parts(MagicMock(), [SIGNED, SIGNED]) == []


def test_history_sends_photos_for_the_newest_user_messages_only():
    history = [
        {"role": "user", "content": "old", "image_urls": ["a"]},
        {"role": "user", "content": "mid", "image_urls": ["b"]},
        {"role": "ai", "content": "<response>ok</response>"},
        {"role": "user", "content": "here is my plan", "image_urls": ["c", "d"]},
    ]
    seen: list[list[str]] = []

    def parts(urls):
        seen.append(urls)
        return [ai_coach.types.Part.from_text(text=f"IMG:{u}") for u in urls]

    contents = ai_coach._history_to_gemini_contents(history, image_parts=parts)
    assert seen == [["b"], ["c", "d"]]  # 2 newest user messages with photos
    assert [p.text for p in contents[-1].parts] == ["here is my plan", "IMG:c", "IMG:d"]
    assert len(contents[0].parts) == 1  # "old" sent as text only


# --- batch scheduling ------------------------------------------------------------------

def test_schedule_workouts_schedules_each_and_reports_failures():
    calls = []

    def fake(item, *, athlete_id, db):
        calls.append(item)
        if item.get("date") == "bad":
            return {"error": "invalid date"}
        return {"planned_date": item["date"], "title": item.get("title") or "x", "training_plan_id": f"id-{item['date']}"}

    with patch.object(coach_tools, "handle_schedule_workout", side_effect=fake):
        res = coach_tools.handle_schedule_workouts(
            {"workouts": [{"date": "2026-11-04", "title": "Steady state"}, {"date": "bad"}, "nope"]},
            athlete_id="a",
            db=MagicMock(),
        )
    assert res["scheduled_count"] == 1
    assert res["scheduled"][0] == {"date": "2026-11-04", "title": "Steady state", "training_plan_id": "id-2026-11-04"}
    assert [f.get("index") for f in res["failed"]] == [1, 2]


def test_schedule_workouts_caps_one_call():
    with patch.object(coach_tools, "handle_schedule_workout", return_value={"planned_date": "2026-11-04", "title": "t", "training_plan_id": "i"}):
        res = coach_tools.handle_schedule_workouts(
            {"workouts": [{"date": "2026-11-04"}] * (coach_tools.SCHEDULE_MANY_MAX + 5)}, athlete_id="a", db=MagicMock()
        )
    assert res["scheduled_count"] == coach_tools.SCHEDULE_MANY_MAX
    assert "5 more" in res["not_scheduled"]


def test_schedule_workouts_is_a_registered_tool():
    names = {d.name for t in coach_tools.TOOLS for d in (t.function_declarations or [])}
    assert "schedule_workouts" in names
    assert "schedule_workouts" in coach_tools.TOOL_HANDLERS
    assert "title" in coach_tools._schedule_decl.parameters.properties


# --- step budget ---------------------------------------------------------------------

def test_bulk_plan_requests_get_more_tool_rounds():
    assert ai_coach._agentic_max_tool_hops("put the full two months into the plan within the app") == 14
    assert ai_coach._agentic_max_tool_hops("hi", has_images=True) == 14
    assert ai_coach._agentic_max_tool_hops("[ATTACHED DOCUMENT: plan.docx]\n...") == 14
    assert ai_coach._agentic_max_tool_hops("schedule a ride tomorrow") == 8


def test_wrap_up_asks_once_more_without_tools():
    seen = {}

    def fake_generate(*, model, contents, config):
        seen["tools"] = config.tools
        seen["last"] = contents[-1].parts[0].text
        resp = MagicMock()
        return resp

    with patch.object(ai_coach._client.models, "generate_content", side_effect=fake_generate), patch.object(
        ai_coach, "_extract_non_thought_text_from_response", return_value="<response>Scheduled 3 weeks; 5 left.</response>"
    ), patch.object(ai_coach.gemini_quota, "wait_for_slot"):
        text = ai_coach._wrap_up_after_tool_budget([], "sys", ["m"])
    assert not seen["tools"]
    assert "Do not call tools" in seen["last"]
    assert "Scheduled 3 weeks" in text
