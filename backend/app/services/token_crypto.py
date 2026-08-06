"""Fernet helpers for encrypting OAuth/session token blobs at rest.

Applies to every provider's ``oauth_tokens.access_token`` / ``refresh_token``
(WHOOP, Strava, intervals.icu, Garmin) — not just one integration. Plaintext
legacy rows (no Fernet prefix) are accepted on decrypt so existing
connections keep working after the key is introduced or rotated.

Two decrypt entry points, deliberately different failure behavior:

- ``decrypt_token`` is the raw primitive — a value that fails to decrypt
  under the *current* key raises ``InvalidToken``. Callers using it directly
  must handle that themselves.
- ``decrypt_oauth_row`` (what every provider's read path actually calls)
  fails closed instead: an undecryptable field is set to ``None`` rather
  than raising or returning ciphertext, so a bad/rotated key can't
  propagate ciphertext into a caller that would use it as a bearer token —
  it's treated the same as "no token", which every caller already handles
  as "needs reconnect".
"""
from __future__ import annotations

import logging
from functools import lru_cache

from cryptography.fernet import Fernet, InvalidToken

from app.config import settings

logger = logging.getLogger(__name__)

# Fernet ciphertext is url-safe base64 and always starts with this prefix.
_FERNET_PREFIX = "gAAAAA"

# oauth_tokens columns that hold secrets and should be encrypted at rest.
_OAUTH_SECRET_FIELDS = ("access_token", "refresh_token")


@lru_cache(maxsize=1)
def _fernet() -> Fernet | None:
    raw = (settings.OAUTH_TOKEN_ENCRYPTION_KEY or "").strip()
    if not raw:
        return None
    try:
        return Fernet(raw.encode("utf-8") if isinstance(raw, str) else raw)
    except Exception as exc:
        logger.error("Invalid OAUTH_TOKEN_ENCRYPTION_KEY: %s", exc)
        return None


def encrypt_token(plaintext: str) -> str:
    """Encrypt ``plaintext`` when a key is configured; otherwise return as-is."""
    f = _fernet()
    if f is None:
        return plaintext
    return f.encrypt(plaintext.encode("utf-8")).decode("utf-8")


def decrypt_token(stored: str) -> str:
    """Decrypt a Fernet blob, or return plaintext legacy values unchanged."""
    if not stored:
        return stored
    f = _fernet()
    if f is None:
        return stored
    if not stored.startswith(_FERNET_PREFIX):
        return stored
    try:
        return f.decrypt(stored.encode("utf-8")).decode("utf-8")
    except InvalidToken:
        logger.warning("Fernet decrypt failed for stored token blob")
        raise


def encrypt_oauth_fields(payload: dict) -> dict:
    """
    Return a shallow copy of an ``oauth_tokens`` write payload with
    ``access_token``/``refresh_token`` encrypted, if present and non-empty.

    Safe to call on any ``oauth_tokens`` insert/update/upsert payload, even
    one that doesn't touch either field (e.g. an ``expires_at``-only update)
    — those pass through unchanged.
    """
    out = dict(payload)
    for field in _OAUTH_SECRET_FIELDS:
        value = out.get(field)
        if isinstance(value, str) and value:
            out[field] = encrypt_token(value)
    return out


def decrypt_oauth_row(row: dict | None) -> dict | None:
    """
    Return a shallow copy of an ``oauth_tokens`` row (or list-style dict) with
    ``access_token``/``refresh_token`` decrypted, if present.

    A field that fails to decrypt under the current key is set to ``None``
    rather than raising or returning ciphertext — callers already treat a
    missing token as "not connected / needs reconnect", which is the correct
    behavior for an undecryptable value too.
    """
    if row is None:
        return None
    out = dict(row)
    for field in _OAUTH_SECRET_FIELDS:
        value = out.get(field)
        if isinstance(value, str) and value:
            try:
                out[field] = decrypt_token(value)
            except InvalidToken:
                out[field] = None
    return out
