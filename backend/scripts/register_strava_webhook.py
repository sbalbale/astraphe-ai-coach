"""Re-register Strava push subscription to match APP_BASE_URL in backend/.env."""
from __future__ import annotations

import re
import sys
from pathlib import Path

import httpx

env_path = Path(__file__).resolve().parents[1] / ".env"
text = env_path.read_text(encoding="utf-8")


def get(key: str, *, required: bool = True) -> str:
    m = re.search(rf'^{key}="([^"]*)"', text, re.M)
    if not m:
        m = re.search(rf"^{key}=([^\s#]+)", text, re.M)
    if not m:
        if required:
            print(f"Missing {key} in .env", file=sys.stderr)
            sys.exit(1)
        return ""
    return m.group(1).strip()


def main() -> None:
    cid = get("STRAVA_CLIENT_ID")
    secret = get("STRAVA_CLIENT_SECRET")
    verify = get("STRAVA_WEBHOOK_VERIFY_TOKEN")
    base = get("APP_BASE_URL").rstrip("/")
    callback = f"{base}/v1/sync/strava/webhook"
    with httpx.Client(timeout=30.0) as client:
        list_r = client.get(
            "https://www.strava.com/api/v3/push_subscriptions",
            params={"client_id": cid, "client_secret": secret},
        )
        list_r.raise_for_status()
        subs = list_r.json()
        print("Existing subscriptions:")
        for s in subs:
            print(f"  id={s['id']} callback={s['callback_url']}")

        for s in subs:
            sid = s["id"]
            if s.get("callback_url") == callback:
                print(f"\nAlready registered: {callback} (id={sid})")
                print(f"STRAVA_WEBHOOK_SUBSCRIPTION_ID={sid}")
                return
            del_r = client.delete(
                f"https://www.strava.com/api/v3/push_subscriptions/{sid}",
                params={"client_id": cid, "client_secret": secret},
            )
            print(f"\nDeleted subscription {sid}: {del_r.status_code}")

        # Strava verifies via GET hub.challenge — backend must be running and reachable.
        print(f"\nRegistering: {callback}")
        print("Ensure uvicorn is running and ngrok tunnels to :8000 before this succeeds.")
        post_r = client.post(
            "https://www.strava.com/api/v3/push_subscriptions",
            data={
                "client_id": cid,
                "client_secret": secret,
                "callback_url": callback,
                "verify_token": verify,
            },
        )
        if post_r.status_code >= 400:
            print(f"Register failed {post_r.status_code}: {post_r.text}", file=sys.stderr)
            sys.exit(1)
        new = post_r.json()
        new_id = new.get("id")
        print(f"Registered subscription id={new_id}")
        if new_id is not None:
            if re.search(r"^STRAVA_WEBHOOK_SUBSCRIPTION_ID=", text, re.M):
                text = re.sub(
                    r"^STRAVA_WEBHOOK_SUBSCRIPTION_ID=.*$",
                    f"STRAVA_WEBHOOK_SUBSCRIPTION_ID={new_id}",
                    text,
                    count=1,
                    flags=re.M,
                )
            else:
                text = text.rstrip() + f"\nSTRAVA_WEBHOOK_SUBSCRIPTION_ID={new_id}\n"
            env_path.write_text(text, encoding="utf-8")
            print(f"Updated {env_path.name}: STRAVA_WEBHOOK_SUBSCRIPTION_ID={new_id}")


if __name__ == "__main__":
    main()
