"""
Push notification delivery service.

Supports two delivery paths:
  - FCM (firebase-admin)  →  iOS (APNs bridge) and Android
  - VAPID web push (pywebpush)  →  browser / PWA

Both are optional at runtime: if the relevant credentials are absent the
send functions return False and log a warning rather than raising.
"""

import json
import logging
from typing import Optional

logger = logging.getLogger(__name__)

_firebase_ready = False


def _init_firebase() -> bool:
    global _firebase_ready
    if _firebase_ready:
        return True
    try:
        import firebase_admin
        from firebase_admin import credentials
        from app.config import settings

        if not settings.FCM_SERVICE_ACCOUNT_JSON:
            return False
        if firebase_admin._apps:
            _firebase_ready = True
            return True
        cred = credentials.Certificate(json.loads(settings.FCM_SERVICE_ACCOUNT_JSON))
        firebase_admin.initialize_app(cred)
        _firebase_ready = True
        return True
    except Exception as exc:
        logger.warning("Firebase init failed: %s", exc)
        return False


def _send_fcm(token: str, title: str, body: str, data: dict) -> bool:
    if not _init_firebase():
        return False
    try:
        from firebase_admin import messaging

        message = messaging.Message(
            notification=messaging.Notification(title=title, body=body),
            data={k: str(v) for k, v in (data or {}).items()},
            token=token,
            apns=messaging.APNSConfig(
                payload=messaging.APNSPayload(
                    aps=messaging.Aps(sound="default", badge=1)
                )
            ),
        )
        messaging.send(message)
        return True
    except Exception as exc:
        logger.warning("FCM send failed (token=...%s): %s", token[-6:], exc)
        return False


def _send_web_push(subscription_json: str, title: str, body: str, data: dict) -> bool:
    from app.config import settings

    if not settings.VAPID_PRIVATE_KEY or not settings.VAPID_PUBLIC_KEY:
        return False
    try:
        from pywebpush import webpush, WebPushException  # type: ignore

        subscription = json.loads(subscription_json)
        webpush(
            subscription_info=subscription,
            data=json.dumps({"title": title, "body": body, "data": data or {}}),
            vapid_private_key=settings.VAPID_PRIVATE_KEY,
            vapid_claims={"sub": settings.VAPID_SUBJECT},
        )
        return True
    except Exception as exc:
        logger.warning("Web push failed: %s", exc)
        return False


def send_push_to_athlete(
    athlete_id: str,
    title: str,
    body: str,
    db,
    data: Optional[dict] = None,
    notification_type: Optional[str] = None,
) -> int:
    """
    Send a push notification to every registered token for an athlete.

    notification_type, if given, is checked against the athlete's
    notification_settings before sending (e.g. 'coach', 'readiness',
    'workouts', 'insights').  A missing key defaults to True (opt-in).

    Returns the count of successful sends (0 means nothing was sent,
    which is not an error when the user has no tokens registered).
    """
    try:
        if notification_type:
            profile_res = (
                db.table("athletes")
                .select("notification_settings")
                .eq("id", athlete_id)
                .maybe_single()
                .execute()
            )
            ns = (profile_res.data or {}).get("notification_settings") or {}
            if not ns.get(notification_type, True):
                return 0

        tokens_res = (
            db.table("push_tokens")
            .select("token,platform")
            .eq("athlete_id", athlete_id)
            .execute()
        )
        tokens = tokens_res.data or []
        if not tokens:
            return 0

        sent = 0
        for row in tokens:
            token, platform = row["token"], row["platform"]
            if platform in ("ios", "android"):
                ok = _send_fcm(token, title, body, data or {})
            elif platform == "web":
                ok = _send_web_push(token, title, body, data or {})
            else:
                ok = False
            if ok:
                sent += 1

        return sent
    except Exception as exc:
        logger.error("send_push_to_athlete failed for %s: %s", athlete_id, exc)
        return 0
