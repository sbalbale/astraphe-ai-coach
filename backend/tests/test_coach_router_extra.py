from __future__ import annotations

from unittest.mock import AsyncMock, patch

from app.dependencies import UserConfig, get_user_config, get_user_db
from app.main import app
from app.routers import coach as coach_router


# ---------------------------------------------------------------------------
# Pure helpers
# ---------------------------------------------------------------------------


def test_generate_conversation_title_empty_message_with_images():
    assert coach_router._generate_conversation_title(None, image_urls=["a.png"]) == "Images"


def test_generate_conversation_title_empty_message_no_images():
    assert coach_router._generate_conversation_title("   ") == "New chat"


def test_generate_conversation_title_truncates_long_message():
    msg = " ".join(f"word{i}" for i in range(20))
    title = coach_router._generate_conversation_title(msg)
    assert title.endswith("…")
    assert len(title) <= 60


def test_generate_conversation_title_collapses_newlines():
    title = coach_router._generate_conversation_title("Line one\nLine two")
    assert "\n" not in title


def test_require_premium_raises_for_non_premium_tier():
    from fastapi import HTTPException

    config = UserConfig(
        user_id="u1", tier="free", gemini_model="m", gemini_analysis_model="m2",
        rate_limit_rpm=5, rate_limit_rph=20, is_admin=False,
    )
    try:
        coach_router._require_premium(config)
        assert False, "expected HTTPException"
    except HTTPException as e:
        assert e.status_code == 403


# ---------------------------------------------------------------------------
# Conversations
# ---------------------------------------------------------------------------


def test_list_conversations_returns_rows(coach_client, fake_db, test_athlete_id):
    fake_db._table_seeds["coach_conversations"] = [
        {"id": "c1", "title": "Chat 1", "created_at": "t", "updated_at": "t"}
    ]
    res = coach_client.get("/v1/coach/conversations")
    assert res.status_code == 200
    assert res.json()["conversations"][0]["id"] == "c1"


def test_create_conversation_returns_new_id(coach_client, fake_db, test_athlete_id):
    res = coach_client.post("/v1/coach/conversations", json={"title": "New chat"})
    assert res.status_code == 200
    body = res.json()
    assert body["conversation"]["id"] == "fake-conversation-id"
    assert body["conversation"]["title"] == "New chat"


def test_delete_conversation_success(coach_client, fake_db, test_athlete_id):
    res = coach_client.delete("/v1/coach/conversations/c1")
    assert res.status_code == 200
    assert res.json() == {"status": "success"}


# ---------------------------------------------------------------------------
# Memories
# ---------------------------------------------------------------------------


def test_list_memories_returns_rows(coach_client, fake_db, test_athlete_id):
    with patch("app.services.memory.list_coach_memories", return_value=[{"id": "m1"}]):
        res = coach_client.get("/v1/coach/memories")
    assert res.status_code == 200
    assert res.json()["memories"] == [{"id": "m1"}]


def test_update_memory_requires_fields(coach_client, fake_db, test_athlete_id):
    res = coach_client.patch("/v1/coach/memories/m1", json={})
    assert res.status_code == 400


def test_update_memory_success(coach_client, fake_db, test_athlete_id):
    fake_db._table_seeds["coach_memories"] = [{"id": "m1", "content": "old"}]
    res = coach_client.patch("/v1/coach/memories/m1", json={"content": "new fact"})
    assert res.status_code == 200
    assert res.json()["status"] == "success"


def test_delete_memory_success(coach_client, fake_db, test_athlete_id):
    fake_db._table_seeds["coach_memories"] = [{"id": "m1"}]
    res = coach_client.delete("/v1/coach/memories/m1")
    assert res.status_code == 200
    assert res.json()["status"] == "success"


# ---------------------------------------------------------------------------
# Upload document
# ---------------------------------------------------------------------------


def test_upload_document_rejects_unsupported_extension(coach_client, fake_db, test_athlete_id):
    res = coach_client.post(
        "/v1/coach/upload-document",
        files={"file": ("notes.txt", b"hello", "text/plain")},
    )
    assert res.status_code == 415


def test_upload_document_rejects_oversized_file(coach_client, fake_db, test_athlete_id):
    big = b"x" * (coach_router._MAX_DOC_BYTES + 1)
    res = coach_client.post(
        "/v1/coach/upload-document",
        files={"file": ("big.csv", big, "text/csv")},
    )
    assert res.status_code == 413


def test_upload_document_422_on_parse_failure(coach_client, fake_db, test_athlete_id):
    with patch("app.services.file_parser.parse_document", side_effect=RuntimeError("bad file")):
        res = coach_client.post(
            "/v1/coach/upload-document",
            files={"file": ("data.csv", b"a,b\n1,2", "text/csv")},
        )
    assert res.status_code == 422


def test_upload_document_422_when_no_text_extracted(coach_client, fake_db, test_athlete_id):
    with patch("app.services.file_parser.parse_document", return_value="   "):
        res = coach_client.post(
            "/v1/coach/upload-document",
            files={"file": ("data.csv", b"a,b\n1,2", "text/csv")},
        )
    assert res.status_code == 422


def test_upload_document_success(coach_client, fake_db, test_athlete_id):
    with patch("app.services.file_parser.parse_document", return_value="a | b\n1 | 2"):
        res = coach_client.post(
            "/v1/coach/upload-document",
            files={"file": ("data.csv", b"a,b\n1,2", "text/csv")},
        )
    assert res.status_code == 200
    body = res.json()
    assert body["filename"] == "data.csv"
    assert "a | b" in body["content"]


# ---------------------------------------------------------------------------
# /initialize
# ---------------------------------------------------------------------------


def test_initialize_coach_success(coach_client, fake_db, test_athlete_id):
    # initialize_coach re-imports these locally inside the function body, so the
    # patch target must be the source module (app.services.ai_coach/memory), not
    # the coach_router-level name bound at module import time.
    with patch(
        "app.services.ai_coach.build_initialization_message", lambda *a, **k: ("Welcome back", True)
    ), patch("app.services.memory.retrieve_relevant_memories", return_value=[{"content": "Race in June"}]):
        res = coach_client.post("/v1/coach/initialize", json={})

    assert res.status_code == 200
    body = res.json()
    assert body["status"] == "success"
    assert body["message"] == "Welcome back"
    assert body["memories"] == ["Race in June"]


def test_initialize_coach_falls_back_on_error(coach_client, fake_db, test_athlete_id):
    with patch(
        "app.services.ai_coach.build_initialization_message", side_effect=RuntimeError("gemini down")
    ):
        res = coach_client.post("/v1/coach/initialize", json={})

    assert res.status_code == 200
    body = res.json()
    assert body["status"] == "partial_success"
    assert body["message"] is None


# ---------------------------------------------------------------------------
# Premium gate applies across the router
# ---------------------------------------------------------------------------


def test_conversations_endpoint_403_for_non_premium(client, fake_db):
    free_config = UserConfig(
        user_id="u1", tier="free", gemini_model="m", gemini_analysis_model="m2",
        rate_limit_rpm=5, rate_limit_rph=20, is_admin=False,
    )
    app.dependency_overrides[get_user_config] = lambda: free_config
    app.dependency_overrides[get_user_db] = lambda: fake_db
    try:
        res = client.get("/v1/coach/conversations")
    finally:
        app.dependency_overrides.pop(get_user_config, None)
        app.dependency_overrides.pop(get_user_db, None)

    assert res.status_code == 403
