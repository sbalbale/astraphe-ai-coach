from unittest.mock import MagicMock, patch

import app.routers.coach as coach_router


def test_ai_turns_use_service_role_and_user_turns_use_session(monkeypatch):
    monkeypatch.undo()  # drop the conftest override for this test
    user_db, admin_db = MagicMock(), MagicMock()
    with patch("app.dependencies.get_admin_db", return_value=admin_db), patch.object(
        coach_router, "_touch_conversation"
    ), patch.object(coach_router, "_maybe_set_conversation_title"):
        coach_router._insert_message(user_db, "a1", "c1", "ai", "reply")
        coach_router._insert_message(user_db, "a1", "c1", "user", "question")
    admin_db.table.assert_called_once_with("coach_messages")
    assert admin_db.table.return_value.insert.call_args.args[0]["role"] == "ai"
    user_inserts = [c for c in user_db.table.call_args_list if c.args == ("coach_messages",)]
    assert len(user_inserts) == 1
