"""Photon (iMessage) channel client.

Photon only exposes a persistent gRPC stream (spectrum-ts, TypeScript-only), so the
backend never talks to Photon directly. photon-bridge/ (a single-replica Node
service) holds the stream; this module is the backend's HTTP side of that bridge:
authenticating inbound posts from it and asking it to send outbound texts.
"""
from __future__ import annotations

import hmac
import logging
import re
from typing import Optional

import httpx

from app.config import settings

logger = logging.getLogger(__name__)

_E164_RE = re.compile(r"^\+\d{6,15}$")
SEND_TIMEOUT_SEC = 20.0
# iMessage handles long bubbles, but a text-message coach reply this long is a bug.
MAX_OUTBOUND_CHARS = 1500


def is_configured() -> bool:
    return bool(
        settings.PHOTON_ATHLETE_ID
        and settings.PHOTON_ALLOWED_NUMBER
        and settings.PHOTON_BRIDGE_TOKEN
    )


def verify_bridge_token(provided: Optional[str]) -> bool:
    expected = settings.PHOTON_BRIDGE_TOKEN
    if not expected or not provided:
        return False
    return hmac.compare_digest(provided.encode(), expected.encode())


def normalize_number(raw: Optional[str]) -> Optional[str]:
    """Return an E.164 number, or None. Strips spaces/dashes/parens."""
    if not raw:
        return None
    cleaned = re.sub(r"[\s\-().]", "", str(raw))
    return cleaned if _E164_RE.match(cleaned) else None


def is_allowed_sender(raw: Optional[str]) -> bool:
    allowed = normalize_number(settings.PHOTON_ALLOWED_NUMBER)
    sender = normalize_number(raw)
    return bool(allowed and sender and sender == allowed)


async def send_text(text: str, to: Optional[str] = None) -> bool:
    """Ask the bridge to text `to` (default: the allow-listed number). Never raises."""
    target = normalize_number(to or settings.PHOTON_ALLOWED_NUMBER)
    body = (text or "").strip()
    if not target or not body or not settings.PHOTON_BRIDGE_TOKEN:
        return False
    if len(body) > MAX_OUTBOUND_CHARS:
        body = body[: MAX_OUTBOUND_CHARS - 1].rstrip() + "…"
    try:
        async with httpx.AsyncClient(timeout=SEND_TIMEOUT_SEC) as client:
            res = await client.post(
                f"{settings.PHOTON_BRIDGE_URL.rstrip('/')}/send",
                headers={"X-Photon-Bridge-Token": settings.PHOTON_BRIDGE_TOKEN},
                json={"to": target, "text": body},
            )
        if res.status_code >= 400:
            logger.warning("[photon] bridge /send failed: %s %s", res.status_code, res.text[:200])
            return False
        return True
    except Exception as exc:  # network errors must not break coach flows
        logger.warning("[photon] bridge /send error: %s", exc)
        return False
