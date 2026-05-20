# Push Notification System — AI Context

## Architecture

Three delivery paths, all converging on the same `send_push_to_athlete` function:

```
Native (Capacitor)          Web Browser                  Backend Trigger
──────────────────          ───────────────              ────────────────
PushNotifications.register  navigator.serviceWorker      send_push_to_athlete()
       ↓                    + pushManager.subscribe             ↓
   FCM token                  VAPID subscription JSON    fetch tokens from DB
       ↓                            ↓                          ↓
POST /v1/notifications/token → push_tokens table         FCM or VAPID send
```

## Database Schema

Table: `push_tokens`
```sql
id         uuid PK
athlete_id uuid FK → athletes(id) ON DELETE CASCADE
token      text NOT NULL     -- FCM token (iOS/Android) or JSON.stringify(PushSubscription) (web)
platform   text CHECK IN ('ios','android','web')
created_at timestamptz
updated_at timestamptz
UNIQUE(athlete_id, token)
```

RLS: athletes can only CRUD their own rows (via `user_id = auth.uid()` join).

## Backend Files

### `backend/app/services/push.py`
- `_init_firebase()` — lazy-initializes Firebase Admin SDK from `settings.FCM_SERVICE_ACCOUNT_JSON`
- `_send_fcm(token, title, body, data)` → bool — sends via Firebase Cloud Messaging
- `_send_web_push(subscription_json, title, body, data)` → bool — sends via pywebpush VAPID
- `send_push_to_athlete(athlete_id, title, body, db, data?, notification_type?)` → int (count sent)
  - If `notification_type` given, checks `athletes.notification_settings[notification_type]` first
  - Fetches all tokens for athlete, sends to each
  - Returns 0 silently if no tokens or credentials missing (never raises)

### `backend/app/routers/notifications.py`
- `POST /v1/notifications/token` — upsert a push token (body: `{token, platform}`)
- `DELETE /v1/notifications/token` — delete a push token
- `POST /v1/notifications/test` — dev-only, sends test push to caller's tokens

### Config (`backend/app/config.py`)
- `FCM_SERVICE_ACCOUNT_JSON: Optional[str]` — full service account JSON as single-line string
- `VAPID_PUBLIC_KEY: Optional[str]`
- `VAPID_PRIVATE_KEY: Optional[str]`
- `VAPID_SUBJECT: str` — defaults to `"mailto:admin@astrape.app"`

### Coach trigger (`backend/app/routers/coach.py`)
After `_insert_message(... role="ai" ...)` in `chat_with_coach`, calls `send_push_to_athlete` with `notification_type="coach"`. Wrapped in try/except so push failure never breaks the coach response.

## Mobile Files

### `mobile/src/lib/services/pushNotifications.ts`
- `requestPushPermission()` → bool — checks/requests OS permission, no side effects
- `initPushNotifications()` → void — full setup (permission + register + listeners)
  - Native path: `PushNotifications.register()` → on `registration` event → `POST /v1/notifications/token`
  - Web path: `serviceWorker.register('/sw.js')` → `pushManager.subscribe()` → `POST /v1/notifications/token`
- Uses `import.meta.env.VITE_VAPID_PUBLIC_KEY` for web push subscribe; returns early if absent

### `mobile/static/sw.js`
Service worker. Handles:
- `push` event → `registration.showNotification()`
- `notificationclick` event → focuses existing window or opens `data.url` (default `/dashboard`)

### `mobile/src/routes/+layout.svelte`
Calls `initPushNotifications()` once per session (guarded by `pushInitialized` flag) inside the reactive `$effect` after `authStore.user` is confirmed and `athleteStore.initialLoadDone` is true.

### `mobile/src/routes/profile/notifications/+page.svelte`
- Detects `Notification.permission` on mount, shows amber banner if `"denied"`
- On any toggle from off→on, calls `requestPushPermission()` + `initPushNotifications()`
- Saves `notification_settings` to `athletes` table via `athleteStore.updateProfile()`

## notification_settings keys

Stored as JSONB in `athletes.notification_settings`:
```json
{ "readiness": true, "coach": true, "workouts": false, "insights": true }
```
Backend `send_push_to_athlete(..., notification_type="coach")` checks this before sending.

## Adding a New Notification Trigger

1. Import and call `send_push_to_athlete` from any backend router:
```python
from app.services.push import send_push_to_athlete
send_push_to_athlete(
    athlete_id=athlete_id,
    title="ASTRAPE",
    body="Your readiness score is ready.",
    db=db,
    data={"url": "/dashboard"},
    notification_type="readiness",  # checked against notification_settings
)
```
2. Wrap in try/except if the calling code is on a critical path.

## Credentials Required

| Env var | Platform | Where to get |
|---|---|---|
| `FCM_SERVICE_ACCOUNT_JSON` | iOS/Android | Firebase Console → Project Settings → Service Accounts |
| `VAPID_PUBLIC_KEY` | Web | `npx web-push generate-vapid-keys` |
| `VAPID_PRIVATE_KEY` | Web | same command |
| `VITE_VAPID_PUBLIC_KEY` | Mobile web | same public key, in mobile `.env` |

All credentials are optional — the push service degrades gracefully to returning 0 sends without crashing.

## Native Project Setup (one-time, manual)

iOS:
- `GoogleService-Info.plist` → `mobile/ios/App/App/`
- Xcode: enable Push Notifications + Background Modes (Remote notifications) capabilities
- Run `npx cap sync` after `pnpm install` in `mobile/`

Android:
- `google-services.json` → `mobile/android/app/`
- Run `npx cap sync`

## What Is NOT Implemented

- Scheduled notifications (readiness score, workout reminders, weekly insights) — the `send_push_to_athlete` function exists and is callable from any backend job/endpoint, but no scheduler is wired up yet
- Token cleanup on 410 Gone responses from FCM/VAPID
- Multi-device badge count management
