import httpx
from app.config import settings


async def sync_marketing_contact(email: str, subscribed: bool) -> None:
    """
    Add or unsubscribe a contact in the Resend "Astrape Marketing" segment.
    Uses upsert semantics — safe to call on every toggle regardless of prior state.
    Failures are logged but never surfaced to the caller so a Resend outage
    cannot block a profile save.
    """
    if not settings.RESEND_API_KEY or not settings.RESEND_AUDIENCE_ID:
        return

    url = f"https://api.resend.com/audiences/{settings.RESEND_AUDIENCE_ID}/contacts"
    headers = {
        "Authorization": f"Bearer {settings.RESEND_API_KEY}",
        "Content-Type": "application/json",
    }
    body = {"email": email, "unsubscribed": not subscribed}

    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            r = await client.post(url, json=body, headers=headers)
            r.raise_for_status()
    except Exception as exc:
        print(f"[resend] Failed to sync contact {email} (subscribed={subscribed}): {exc}")
