from __future__ import annotations

import asyncio
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

from app.dependencies import get_admin_db
from app.main import app
from app.routers import admin as admin_router


def _run_async(coro):
    return asyncio.run(coro)


# ---------------------------------------------------------------------------
# get_admin_user dependency
# ---------------------------------------------------------------------------


def _creds(token="tok"):
    return SimpleNamespace(credentials=token)


def test_get_admin_user_returns_user_id_when_admin():
    fake_db = MagicMock()
    fake_db.auth.get_user.return_value = SimpleNamespace(
        user=SimpleNamespace(id="user-1", app_metadata={"is_admin": True})
    )

    result = _run_async(admin_router.get_admin_user(credentials=_creds(), db=fake_db))
    assert result == {"user_id": "user-1"}


def test_get_admin_user_rejects_non_admin():
    fake_db = MagicMock()
    fake_db.auth.get_user.return_value = SimpleNamespace(
        user=SimpleNamespace(id="user-1", app_metadata={"is_admin": False})
    )

    with pytest.raises(HTTPException) as exc_info:
        _run_async(admin_router.get_admin_user(credentials=_creds(), db=fake_db))
    assert exc_info.value.status_code == 403


def test_get_admin_user_wraps_auth_failure_as_401():
    fake_db = MagicMock()
    fake_db.auth.get_user.side_effect = RuntimeError("bad token")

    with pytest.raises(HTTPException) as exc_info:
        _run_async(admin_router.get_admin_user(credentials=_creds(), db=fake_db))
    assert exc_info.value.status_code == 401


# ---------------------------------------------------------------------------
# _format_user
# ---------------------------------------------------------------------------


def test_format_user_uses_tier_defaults_when_unset():
    u = SimpleNamespace(
        id="user-1",
        email="a@example.com",
        created_at="2026-01-01",
        app_metadata={},
        user_metadata={"full_name": "Ada"},
    )
    formatted = admin_router._format_user(u)
    assert formatted["config"]["tier"] == "free"
    assert formatted["config"]["rate_limit_rpm"] == 5
    assert formatted["display_name"] == "Ada"


def test_format_user_falls_back_to_name_field():
    u = SimpleNamespace(
        id="user-1", email=None, created_at="", app_metadata={"tier": "premium"}, user_metadata={"name": "Bo"}
    )
    formatted = admin_router._format_user(u)
    assert formatted["display_name"] == "Bo"
    assert formatted["config"]["rate_limit_rpm"] == 40


# ---------------------------------------------------------------------------
# Router-level tests via TestClient
# ---------------------------------------------------------------------------


def _override(admin_db, admin_ok: bool = True):
    if admin_ok:
        app.dependency_overrides[admin_router.get_admin_user] = lambda: {"user_id": "admin-1"}
    app.dependency_overrides[get_admin_db] = lambda: admin_db


def _teardown():
    app.dependency_overrides = {}


def test_list_users_returns_formatted_list():
    fake_db = MagicMock()
    fake_db.auth.admin.list_users.return_value = [
        SimpleNamespace(id="u1", email="a@x.com", created_at="", app_metadata={}, user_metadata={})
    ]
    _override(fake_db)
    try:
        with TestClient(app) as client:
            res = client.get("/v1/admin/users")
    finally:
        _teardown()

    assert res.status_code == 200
    body = res.json()
    assert body["status"] == "success"
    assert len(body["users"]) == 1


def test_list_users_clamps_per_page():
    fake_db = MagicMock()
    fake_db.auth.admin.list_users.return_value = []
    _override(fake_db)
    try:
        with TestClient(app) as client:
            res = client.get("/v1/admin/users", params={"per_page": 999})
    finally:
        _teardown()

    assert res.status_code == 200
    assert res.json()["per_page"] == 100


def test_list_users_returns_500_on_provider_error():
    fake_db = MagicMock()
    fake_db.auth.admin.list_users.side_effect = RuntimeError("supabase down")
    _override(fake_db)
    try:
        with TestClient(app) as client:
            res = client.get("/v1/admin/users")
    finally:
        _teardown()

    assert res.status_code == 500


def test_get_user_returns_404_when_missing():
    fake_db = MagicMock()
    fake_db.auth.admin.get_user_by_id.return_value = SimpleNamespace(user=None)
    _override(fake_db)
    try:
        with TestClient(app) as client:
            res = client.get("/v1/admin/users/missing-id")
    finally:
        _teardown()

    assert res.status_code == 404


def test_get_user_returns_formatted_user():
    fake_db = MagicMock()
    fake_user = SimpleNamespace(id="u1", email="a@x.com", created_at="", app_metadata={}, user_metadata={})
    fake_db.auth.admin.get_user_by_id.return_value = SimpleNamespace(user=fake_user)
    _override(fake_db)
    try:
        with TestClient(app) as client:
            res = client.get("/v1/admin/users/u1")
    finally:
        _teardown()

    assert res.status_code == 200
    assert res.json()["user"]["user_id"] == "u1"


def test_update_user_config_requires_at_least_one_field():
    _override(MagicMock())
    try:
        with TestClient(app) as client:
            res = client.patch("/v1/admin/users/u1", json={})
    finally:
        _teardown()

    assert res.status_code == 400


def test_update_user_config_rejects_invalid_tier():
    _override(MagicMock())
    try:
        with TestClient(app) as client:
            res = client.patch("/v1/admin/users/u1", json={"tier": "not-a-tier"})
    finally:
        _teardown()

    assert res.status_code == 422


def test_update_user_config_rejects_non_positive_rate_limit():
    _override(MagicMock())
    try:
        with TestClient(app) as client:
            res = client.patch("/v1/admin/users/u1", json={"rate_limit_rpm": 0})
    finally:
        _teardown()

    assert res.status_code == 422


def test_update_user_config_clears_model_override_with_empty_string():
    fake_db = MagicMock()
    fake_user = SimpleNamespace(id="u1", email="a@x.com", created_at="", app_metadata={}, user_metadata={})
    fake_db.auth.admin.update_user_by_id.return_value = SimpleNamespace(user=fake_user)
    _override(fake_db)
    try:
        with TestClient(app) as client:
            res = client.patch("/v1/admin/users/u1", json={"gemini_model": "  "})
    finally:
        _teardown()

    assert res.status_code == 200
    args, _ = fake_db.auth.admin.update_user_by_id.call_args
    assert args[1] == {"app_metadata": {"gemini_model": None}}


def test_update_user_config_applies_all_provided_fields():
    fake_db = MagicMock()
    fake_user = SimpleNamespace(id="u1", email="a@x.com", created_at="", app_metadata={}, user_metadata={})
    fake_db.auth.admin.update_user_by_id.return_value = SimpleNamespace(user=fake_user)
    _override(fake_db)
    try:
        with TestClient(app) as client:
            res = client.patch(
                "/v1/admin/users/u1",
                json={
                    "tier": "premium",
                    "gemini_model": "gemini-pro",
                    "gemini_analysis_model": "gemini-flash",
                    "rate_limit_rpm": 100,
                    "rate_limit_rph": 500,
                    "is_admin": True,
                },
            )
    finally:
        _teardown()

    assert res.status_code == 200
    args, _ = fake_db.auth.admin.update_user_by_id.call_args
    assert args[1]["app_metadata"] == {
        "tier": "premium",
        "gemini_model": "gemini-pro",
        "gemini_analysis_model": "gemini-flash",
        "rate_limit_rpm": 100,
        "rate_limit_rph": 500,
        "is_admin": True,
    }


def test_update_user_config_returns_500_on_provider_error():
    fake_db = MagicMock()
    fake_db.auth.admin.update_user_by_id.side_effect = RuntimeError("boom")
    _override(fake_db)
    try:
        with TestClient(app) as client:
            res = client.patch("/v1/admin/users/u1", json={"tier": "premium"})
    finally:
        _teardown()

    assert res.status_code == 500


def test_clear_user_config_field_rejects_non_clearable_field():
    _override(MagicMock())
    try:
        with TestClient(app) as client:
            res = client.delete("/v1/admin/users/u1/config/is_admin")
    finally:
        _teardown()

    assert res.status_code == 400


def test_clear_user_config_field_clears_valid_field():
    fake_db = MagicMock()
    _override(fake_db)
    try:
        with TestClient(app) as client:
            res = client.delete("/v1/admin/users/u1/config/gemini_model")
    finally:
        _teardown()

    assert res.status_code == 200
    assert res.json() == {"status": "success", "cleared": "gemini_model", "user_id": "u1"}


def test_clear_user_config_field_returns_500_on_provider_error():
    fake_db = MagicMock()
    fake_db.auth.admin.update_user_by_id.side_effect = RuntimeError("boom")
    _override(fake_db)
    try:
        with TestClient(app) as client:
            res = client.delete("/v1/admin/users/u1/config/gemini_model")
    finally:
        _teardown()

    assert res.status_code == 500


class _MemoriesQuery:
    def __init__(self, rows, fail_updated_at=False):
        self._rows = rows
        self._fail_updated_at = fail_updated_at
        self._used_updated_at = False
        self._deleted_ids: list[str] | None = None

    def select(self, cols, *_a, **_k):
        self._used_updated_at = "updated_at" in cols
        return self

    def eq(self, *_a, **_k):
        return self

    def order(self, *_a, **_k):
        return self

    def limit(self, *_a, **_k):
        return self

    def delete(self):
        return self

    def in_(self, _field, ids):
        self._deleted_ids = list(ids)
        return self

    def execute(self):
        if self._used_updated_at and self._fail_updated_at:
            raise RuntimeError("no updated_at column")
        if self._deleted_ids is not None:
            return SimpleNamespace(data=None)
        return SimpleNamespace(data=self._rows)


class _MemoriesDb:
    def __init__(self, rows, fail_updated_at=False):
        self.query = _MemoriesQuery(rows, fail_updated_at=fail_updated_at)

    def table(self, name):
        assert name == "coach_memories"
        return self.query


def test_merge_duplicates_requires_athlete_id():
    _override(MagicMock())
    try:
        with TestClient(app) as client:
            res = client.post(
                "/v1/admin/coach-memories/merge-duplicates",
                json={"athlete_id": "  "},
            )
    finally:
        _teardown()

    assert res.status_code == 400


def test_merge_duplicates_no_duplicates_found():
    db = _MemoriesDb(rows=[{"id": "1", "content": "unique note", "created_at": "t"}])
    _override(db)
    try:
        with TestClient(app) as client:
            res = client.post(
                "/v1/admin/coach-memories/merge-duplicates",
                json={"athlete_id": "athlete-1"},
            )
    finally:
        _teardown()

    assert res.status_code == 200
    body = res.json()
    assert body["duplicate_groups"] == 0
    assert body["deleted"] == 0


def test_merge_duplicates_dry_run_reports_without_deleting():
    rows = [
        {"id": "1", "content": "Same note", "updated_at": "2026-05-20T10:00:00Z"},
        {"id": "2", "content": "same   note", "updated_at": "2026-05-19T10:00:00Z"},
        {"id": "3", "content": "", "updated_at": "2026-05-18T10:00:00Z"},
    ]
    db = _MemoriesDb(rows=rows)
    _override(db)
    try:
        with TestClient(app) as client:
            res = client.post(
                "/v1/admin/coach-memories/merge-duplicates",
                json={"athlete_id": "athlete-1", "dry_run": True},
            )
    finally:
        _teardown()

    assert res.status_code == 200
    body = res.json()
    assert body["duplicate_groups"] == 1
    assert body["would_delete"] == 1
    assert body["deleted"] == 0
    assert body["groups"][0]["keep_id"] == "1"
    assert body["groups"][0]["drop_ids"] == ["2"]


def test_merge_duplicates_falls_back_when_updated_at_missing():
    rows = [
        {"id": "1", "content": "dup", "created_at": "2026-05-20T10:00:00Z"},
        {"id": "2", "content": "dup", "created_at": "2026-05-19T10:00:00Z"},
    ]
    db = _MemoriesDb(rows=rows, fail_updated_at=True)
    _override(db)
    try:
        with TestClient(app) as client:
            res = client.post(
                "/v1/admin/coach-memories/merge-duplicates",
                json={"athlete_id": "athlete-1"},
            )
    finally:
        _teardown()

    assert res.status_code == 200
    assert res.json()["duplicate_groups"] == 1


def test_merge_duplicates_actually_deletes_when_not_dry_run():
    rows = [
        {"id": "1", "content": "dup", "updated_at": "2026-05-20T10:00:00Z"},
        {"id": "2", "content": "dup", "updated_at": "2026-05-19T10:00:00Z"},
    ]
    db = _MemoriesDb(rows=rows)
    _override(db)
    try:
        with TestClient(app) as client:
            res = client.post(
                "/v1/admin/coach-memories/merge-duplicates",
                json={"athlete_id": "athlete-1", "dry_run": False},
            )
    finally:
        _teardown()

    assert res.status_code == 200
    body = res.json()
    assert body["deleted"] == 1
    assert db.query._deleted_ids == ["2"]
