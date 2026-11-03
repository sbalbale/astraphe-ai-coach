"""Account tiers and the new-user trial."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

TRIAL_DAYS = 14


def _parse_ts(value: Any) -> datetime | None:
    if isinstance(value, datetime):
        dt = value
    elif isinstance(value, str) and value.strip():
        try:
            dt = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
        except ValueError:
            return None
    else:
        return None
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def trial_ends_at(app_meta: dict | None, created_at: Any = None) -> datetime | None:
    """When a trial ends: app_metadata.trial_ends_at, else TRIAL_DAYS after signup."""
    explicit = _parse_ts((app_meta or {}).get("trial_ends_at"))
    if explicit is not None:
        return explicit
    created = _parse_ts(created_at)
    return created + timedelta(days=TRIAL_DAYS) if created else None


def effective_tier(tier: str, app_meta: dict | None, created_at: Any = None, now: datetime | None = None) -> str:
    """A trial past its end date is free. A trial with no known end is kept."""
    if tier != "trial":
        return tier
    ends = trial_ends_at(app_meta, created_at)
    if ends is not None and (now or datetime.now(timezone.utc)) >= ends:
        return "free"
    return tier


def new_trial_ends_at(now: datetime | None = None) -> str:
    end = (now or datetime.now(timezone.utc)) + timedelta(days=TRIAL_DAYS)
    return end.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def persist_trial_expiry(admin_db: Any, user_id: str) -> None:
    """Write the downgrade back (auth app_metadata and athletes.tier), so the app's
    session and admin views show free too. Idempotent; errors are the caller's to log."""
    admin_db.auth.admin.update_user_by_id(user_id, {"app_metadata": {"tier": "free"}})
    admin_db.table("athletes").update({"tier": "free"}).eq("user_id", user_id).execute()


PREMIUM_ACCESS_TIERS = frozenset({"trial", "premium"})


def has_premium_access(tier: str | None) -> bool:
    """Premium features (coach, plan, AI analysis) are open to premium and to an active trial.
    Pass the effective tier, so an expired trial is already free."""
    return (tier or "") in PREMIUM_ACCESS_TIERS
