"""
Signed, expiring, single-use OAuth `state` for provider connect flows (WHOOP, Strava).

The state used to be the raw athlete id, so anyone could craft an authorize link
that attached *their* provider account to someone else's athlete, or the victim's
provider account to the attacker's athlete (login CSRF). The state is now:

    base64url(json{a: athlete_id, p: provider, r: web_return, e: expiry, n: nonce}) "." base64url(hmac)

signed with a server secret. The callback verifies signature, provider and expiry,
then burns the nonce in Redis (when Redis is available) so a state can't be reused.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import logging
import secrets
import time
from dataclasses import dataclass

from app.config import settings
from app.core.redis import get_redis

logger = logging.getLogger(__name__)

STATE_TTL_SEC = 600


class OAuthStateError(Exception):
    """The state is missing, malformed, forged, expired, reused or for another provider."""


@dataclass(frozen=True)
class OAuthState:
    athlete_id: str
    provider: str
    web_return: str | None
    nonce: str


def _b64e(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode("ascii")


def _b64d(text: str) -> bytes:
    return base64.urlsafe_b64decode(text + "=" * (-len(text) % 4))


def _signing_key() -> bytes:
    secret = (
        settings.OAUTH_STATE_SECRET
        or settings.OAUTH_TOKEN_ENCRYPTION_KEY
        or settings.SUPABASE_SERVICE_ROLE_KEY
        or ""
    ).strip()
    if not secret:
        raise OAuthStateError("OAuth state signing secret is not configured")
    # Derive a purpose-specific key so the raw secret is never used directly as an HMAC key.
    return hmac.new(secret.encode("utf-8"), b"astraphe-oauth-state-v1", hashlib.sha256).digest()


def sign_state(athlete_id: str, provider: str, web_return: str | None = None, *, now: float | None = None) -> str:
    payload = {
        "a": athlete_id,
        "p": provider,
        "r": web_return,
        "e": int((now if now is not None else time.time()) + STATE_TTL_SEC),
        "n": secrets.token_urlsafe(16),
    }
    body = _b64e(json.dumps(payload, separators=(",", ":")).encode("utf-8"))
    sig = _b64e(hmac.new(_signing_key(), body.encode("ascii"), hashlib.sha256).digest())
    return f"{body}.{sig}"


def verify_state(state: str | None, provider: str, *, now: float | None = None) -> OAuthState:
    if not state or "." not in state or len(state) > 2048:
        raise OAuthStateError("missing or malformed state")
    body, _, sig = state.rpartition(".")
    expected = _b64e(hmac.new(_signing_key(), body.encode("ascii"), hashlib.sha256).digest())
    if not hmac.compare_digest(sig, expected):
        raise OAuthStateError("bad state signature")
    try:
        data = json.loads(_b64d(body))
    except Exception as exc:
        raise OAuthStateError("undecodable state") from exc
    if data.get("p") != provider:
        raise OAuthStateError("state was issued for another provider")
    if int(data.get("e") or 0) < (now if now is not None else time.time()):
        raise OAuthStateError("state expired")
    athlete_id = data.get("a")
    if not isinstance(athlete_id, str) or not athlete_id:
        raise OAuthStateError("state has no athlete")
    return OAuthState(athlete_id=athlete_id, provider=provider, web_return=data.get("r"), nonce=str(data.get("n") or ""))


async def consume_nonce(nonce: str) -> bool:
    """
    Mark the nonce used. Returns False if it was already used. Without Redis the
    expiry alone bounds replay (10 minutes), so this degrades to allowing it.
    """
    redis = get_redis()
    if redis is None or not nonce:
        return True
    try:
        return bool(await redis.set(f"oauth_state_used:{nonce}", "1", nx=True, ex=STATE_TTL_SEC + 60))
    except Exception as exc:  # Redis down: don't block connecting, expiry still applies
        logger.warning("oauth state nonce check skipped (redis error): %s", exc)
        return True
