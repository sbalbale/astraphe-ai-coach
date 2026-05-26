# Push Notifications

ASTRAPE supports web push and a Capacitor native push scaffold. The current repo includes an iOS Capacitor project; Android setup is not present.

## How It Works

```text
Web PWA
  -> Web Push API + mobile/src/service-worker.ts
  -> VAPID subscription JSON
  -> POST /v1/notifications/token
  -> push_tokens table
  -> pywebpush

Capacitor iOS
  -> @capacitor/push-notifications
  -> FCM/APNs token
  -> POST /v1/notifications/token
  -> push_tokens table
  -> firebase-admin
```

Push registration is initialized from `mobile/src/routes/+layout.svelte` after auth/profile load. Web push only registers when the app is running in an installed standalone PWA context and notification permission is granted.

## Backend Environment

```env
FCM_SERVICE_ACCOUNT_JSON=
VAPID_PUBLIC_KEY=
VAPID_PRIVATE_KEY=
VAPID_SUBJECT=mailto:admin@astrape.app
```

All are optional at runtime. If missing, the push service degrades without crashing and sends zero notifications for that transport.

## Frontend Environment

```env
VITE_VAPID_PUBLIC_KEY=
```

This must match `VAPID_PUBLIC_KEY`.

## Database

Push tokens are stored in `push_tokens`, created by:

```text
supabase/migrations/20260519200000_push_tokens.sql
```

The table is athlete-owned and protected by RLS.

## API

### `POST /v1/notifications/token`

Registers a token or subscription.

```json
{
  "token": "<fcm-token-or-vapid-subscription-json>",
  "platform": "ios"
}
```

`platform` may be `ios`, `android`, or `web`. Android is accepted by the backend shape but this repo does not currently include an Android native project.

### `DELETE /v1/notifications/token`

Unregisters a token/subscription.

```json
{
  "token": "<fcm-token-or-vapid-subscription-json>",
  "platform": "web"
}
```

### `POST /v1/notifications/test`

Sends a test notification in non-production environments only.

## Notification Settings

Users manage notification toggles at **Profile -> Notifications**. Settings live in the `athletes.notification_settings` JSONB column and are saved through `PATCH /v1/athlete/profile`.

Supported notification types:

- `readiness`
- `coach`
- `workouts`
- `insights`

`send_push_to_athlete(..., notification_type=...)` checks these settings before sending.

## Current Triggers

The primary implemented trigger is coach reply notification support after a backend coach response. Other categories are available through `send_push_to_athlete` and the settings UI, but should be wired explicitly from the relevant backend workflow.

## Relevant Files

| File | Purpose |
|---|---|
| `mobile/src/lib/services/pushNotifications.ts` | Web/native permission and token registration logic. |
| `mobile/src/service-worker.ts` | Web push service worker. |
| `mobile/src/routes/+layout.svelte` | Auth/profile-gated push initialization. |
| `mobile/src/routes/profile/notifications/+page.svelte` | Settings UI. |
| `backend/app/services/push.py` | FCM and VAPID send functions. |
| `backend/app/routers/notifications.py` | Token and test endpoints. |
| `backend/app/routers/coach.py` | Example coach-trigger integration point. |
| `supabase/migrations/20260519200000_push_tokens.sql` | Token table and RLS. |

## iOS Setup

1. Create a Firebase project.
2. Add iOS app ID `com.astrape.coach`.
3. Place `GoogleService-Info.plist` in `mobile/ios/App/App/`.
4. Generate a Firebase service account key and set `FCM_SERVICE_ACCOUNT_JSON`.
5. In Xcode, enable Push Notifications and Remote notifications background mode.
6. Run `pnpm install`, `pnpm run build`, and `npx cap sync ios` from `mobile/`.

Android setup should be documented when an Android project is added to the repo.
