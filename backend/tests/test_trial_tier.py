from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from app import dependencies
from app.services import tiers

NOW = datetime(2026, 11, 20, tzinfo=timezone.utc)


def test_trial_within_end_date_stays_trial():
    meta = {"tier": "trial", "trial_ends_at": "2026-11-25T00:00:00Z"}
    assert tiers.effective_tier("trial", meta, now=NOW) == "trial"


def test_trial_past_end_date_is_free():
    meta = {"tier": "trial", "trial_ends_at": "2026-11-19T00:00:00Z"}
    assert tiers.effective_tier("trial", meta, now=NOW) == "free"


def test_trial_without_end_date_uses_signup_plus_14_days():
    assert tiers.effective_tier("trial", {}, created_at="2026-11-01T00:00:00Z", now=NOW) == "free"
    assert tiers.effective_tier("trial", {}, created_at="2026-11-10T00:00:00Z", now=NOW) == "trial"


def test_trial_with_no_known_end_is_kept():
    assert tiers.effective_tier("trial", {}, created_at=None, now=NOW) == "trial"


def test_other_tiers_untouched():
    assert tiers.effective_tier("premium", {"trial_ends_at": "2000-01-01T00:00:00Z"}, now=NOW) == "premium"
    assert tiers.effective_tier("free", {}, now=NOW) == "free"


def test_new_trial_ends_at_is_14_days_out():
    assert tiers.new_trial_ends_at(NOW) == (NOW + timedelta(days=14)).strftime("%Y-%m-%dT%H:%M:%SZ")


def test_persist_trial_expiry_writes_both_places():
    admin = MagicMock()
    tiers.persist_trial_expiry(admin, "u1")
    admin.auth.admin.update_user_by_id.assert_called_once_with("u1", {"app_metadata": {"tier": "free"}})
    admin.table.assert_called_with("athletes")


def test_apply_trial_expiry_downgrades_and_schedules_write_back():
    dependencies._trial_expiry_written.clear()
    user = SimpleNamespace(id="u-exp", created_at="2020-01-01T00:00:00Z")
    with patch("app.services.background.spawn") as spawn:
        tier = dependencies._apply_trial_expiry("trial", {"tier": "trial"}, user)
        again = dependencies._apply_trial_expiry("trial", {"tier": "trial"}, user)
    assert tier == "free" and again == "free"
    assert spawn.call_count == 1  # written back once per process
    spawn.call_args.args[0].close()


def test_trial_and_premium_get_premium_features():
    assert tiers.has_premium_access("premium")
    assert tiers.has_premium_access("trial")
    assert not tiers.has_premium_access("free")
    assert not tiers.has_premium_access(None)


def test_coach_allows_trial_and_blocks_free():
    import pytest
    from fastapi import HTTPException

    from app.routers import coach

    coach._require_premium(SimpleNamespace(tier="trial"))
    coach._require_premium(SimpleNamespace(tier="premium"))
    with pytest.raises(HTTPException) as exc:
        coach._require_premium(SimpleNamespace(tier="free"))
    assert exc.value.status_code == 403
