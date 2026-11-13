# Push Notifications

ASTRAPHE sends web push (VAPID) to browsers and installed PWAs, and has a Capacitor/FCM path for native apps. The repo has an iOS Capacitor project, but native iOS push is not wired end to end (see [iOS](#ios)). There is no Android project.

## How It Works

```text
Web (browser tab or installed PWA)
  -> mobile/src/service-worker.ts registered at /service-worker.js
  -> pushManager.subscribe (VITE_VAPID_PUBLIC_KEY)
  -> POST /v1/notifications/token  {token: JSON subscription, platform: "web"}
  -> push_tokens
  -> backend sends with pywebpush

Capacitor native
  -> @capacitor/push-notifications register()
  -> 'registration' event token
  -> POST /v1/notifications/token  {token, platform: "ios" | "android"}
  -> push_tokens
  -> backend sends with firebase-admin (FCM)
```

All sends go through `send_push_to_athlete()` in `backend/app/services/push.py`, which sends to every token the athlete has registered and returns the number of successful sends.

## Client

`mobile/src/lib/services/pushNotifications.ts`:

- `initPushNotifications()` returns `'ok' | 'skipped' | 'unsupported' | 'not-configured' | 'no-service-worker' | 'failed'`. The root layout calls it once per session after the profile has loaded; the settings screen calls it when the athlete turns push on.
- Web rules: on iPhone/iPad, web push only works in the installed Home Screen app, so a normal iOS browser tab is skipped. On desktop and Android a normal tab can subscribe. Without `VITE_VAPID_PUBLIC_KEY` web push is off. Permission is requested automatically only in the installed app; in a browser tab it is requested from the settings screen button.
- Native: requests permission, replaces any previous listeners, posts the token on `registration`, and on notification tap navigates to the notification's target (`safeNotificationPath`).
- `unregisterPushToken()` deletes the device's token on sign-out (`authStore`).
- `hasWebPushSubscription()` is used by the settings screen to show whether this browser actually has a subscription.

`mobile/src/service-worker.ts` is push-only and caches nothing. It:

- shows the notification on `push`; when the payload has quick replies, adds up to two action buttons (or one reply plus "Open chat") where the platform supports actions;
- on `notificationclick`, focuses or opens the app at the target URL. A quick-reply action opens the coach thread with that reply (the chat page reads `?reply=`). Off-origin URLs fall back to `/dashboard`.

## Backend Environment

```env
FCM_SERVICE_ACCOUNT_JSON=
VAPID_PUBLIC_KEY=
VAPID_PRIVATE_KEY=
VAPID_SUBJECT=mailto:admin@astraphe.app
NOTIFICATION_SCHEDULER_ENABLED=true
```

Credentials are optional. If missing, that transport returns "not sent" and logs a warning; nothing raises. `FCM_SERVICE_ACCOUNT_JSON` is the full service-account JSON on one line. Generate VAPID keys with `npx web-push generate-vapid-keys`.

The scheduler (below) runs only when both `BACKGROUND_LOOPS_ENABLED` and `NOTIFICATION_SCHEDULER_ENABLED` are true (both default to true).

## Frontend Environment

```env
VITE_VAPID_PUBLIC_KEY=
```

Must match `VAPID_PUBLIC_KEY`. The Firebase Hosting workflows pass it from GitHub secrets.

## Database

- `push_tokens` (`supabase/migrations/20260519200000_push_tokens.sql`): `athlete_id`, `token` (FCM token or the JSON web push subscription), `platform` (`ios`, `android`, `web`), unique on `(athlete_id, token)`. Athlete-owned, protected by RLS.
- `notification_log` (`supabase/migrations/20261106090100_coach_notifications.sql`): one row per notification, unique on `(athlete_id, kind, dedupe_key)`, with `conversation_id` and `pushed`. Inserting the row is the "claim": whichever replica inserts it first sends, so several API replicas or a re-sync never send twice. Athletes can read their own rows; only the service role writes.
- The same migration adds coach-started threads: `coach_conversations.started_by` (`athlete` or `coach`), `trigger`, `context` (context card JSON), `unread`, and `coach_messages.quick_replies`.

## API

| Route | Purpose |
|---|---|
| `POST /v1/notifications/token` | Upsert `{token, platform}` for the current athlete. `platform` is `ios`, `android` or `web`; tokens over 8192 chars are rejected (422). |
| `DELETE /v1/notifications/token` | Remove a token (same body). |
| `POST /v1/notifications/test` | Settings "Check it works": sends a test push to the athlete's devices. Available in all environments, limited to one per 30 s (429 otherwise). Returns `{status: "sent" \| "no_devices", delivered_to}`. |
| `GET /v1/notifications/devices` | `{count, platforms}` for the settings screen. |

## Notification Settings

Users manage settings at **Profile -> Notifications**. They are stored in `athletes.notification_settings` (JSONB) and saved through `PATCH /v1/athlete/profile`; the profile model normalizes them with `notification_prefs.effective()`. Backend: `backend/app/services/notification_prefs.py`; frontend mirror: `mobile/src/lib/notificationSettings.ts`.

Shape (v2):

```json
{
  "v": 2,
  "types": {
    "debrief": {"on": true, "opt": "now", "push": true},
    "reply":   {"on": true, "push": true},
    "ready":   {"on": true, "push": true},
    "weekly":  {"on": true, "opt": "Sun", "push": true, "email": false},
    "sync":    {"on": true, "push": true, "email": false}
  },
  "quiet": {"on": true, "from": "22:00", "to": "07:00"},
  "texts": "active"
}
```

| Type | What | Option |
|---|---|---|
| `debrief` | Post-workout coach debrief | `now` (right away) or `evening` (19:00 digest) |
| `reply` | A coach chat reply finished after you left the thread | none |
| `ready` | Morning readiness, once last night's sleep is recorded | none |
| `weekly` | Weekly summary thread | `Sun` (18:00) or `Mon` (07:00) |
| `sync` | A connected app stopped sending data | none |

- Quiet hours may wrap midnight. Nothing is pushed during quiet hours.
- `email` is stored but never sent; the app does not send notification email.
- `texts` controls Photon coach texts (see [PHOTON_MESSAGING.md](./PHOTON_MESSAGING.md)); it is not shown in the app.
- The old flat booleans (`readiness`, `coach`, `workouts`, `insights`) are still read as a fallback: `readiness` -> `ready`, `coach` -> `debrief` + `reply`, `insights` -> `weekly`.
- `send_push_to_athlete(..., notification_type=...)` checks the type (v2 id or legacy name) and quiet hours before sending; a push without `notification_type` (test, readiness, sync alerts) skips those checks, so callers check first.

## Triggers

All local times use `athletes.timezone_offset_min`.

- **Coach reply** (`reply`): `backend/app/routers/coach.py` pushes "ASTRAPHE Coach" with a preview of the reply when the athlete is not watching the conversation (`coach_progress.is_watching`). Tapping opens `/chat?conversation=<id>`.
- **Post-workout debrief** (`debrief`): `coach_notifications.post_workout_debrief()` runs after a workout is processed (`services/processing.py`, and `services/garmin.py` after Garmin enrichment). It only fires for recent workouts (at least `PHOTON_MIN_WORKOUT_MINUTES` long, ended within `PHOTON_WORKOUT_MAX_AGE_HOURS`), claims the workout once, asks the coach for a short debrief, creates a coach-started thread with quick replies ("Felt good", "Legs were heavy", "Cut it short") and pushes it. If the push is held (evening digest or quiet hours), the thread still appears unread and the scheduler pushes it later. While `texts` is `active` and Photon is configured for that athlete, the same note is also texted.
- **Scheduler** (`backend/app/services/notification_scheduler.py`): `notification_loop` starts from `app/main.py` and ticks every 5 minutes in every replica, over athletes that have a push token. A tick does nothing for an athlete in quiet hours. Otherwise:
  - held debriefs: pushed in the 19:00-20:00 window for `evening`, or as soon as quiet hours end for `now` (one notification, summarizing several if needed);
  - morning readiness: between 04:00 and 12:00, the first tick that finds today's biometrics with sleep and a readiness score sends "Readiness N · label" plus today's planned session; opens `/readiness`;
  - weekly summary: Sunday 18:00 or Monday 07:00 (3-hour window), the coach writes 2-3 sentences on the last completed week (Sunday-Saturday) and next week's plan, in a new thread; up to 2 compose attempts per week;
  - sync problems: at 09:00, if a connected Garmin, WHOOP or Intervals.icu account has sent no workouts or daily data for 48 hours, "<provider> stopped sending data", opening `/profile/connections`. At most 3 alerts per outage (3 days, then 6 days apart).

### Adding a trigger

```python
from app.services.push import send_push_to_athlete

send_push_to_athlete(
    athlete_id=athlete_id,
    title="ASTRAPHE",
    body="...",            # markdown is converted to plain text
    db=db,
    data={"url": "/dashboard", "type": "ready"},
    notification_type="ready",  # checks the type and quiet hours
)
```

For coach-started threads use `coach_notifications.claim()`, `create_coach_thread()` and `push_thread()`. `send_push_to_athlete` never raises; still wrap calls on critical paths.

## Relevant Files

| File | Purpose |
|---|---|
| `mobile/src/lib/services/pushNotifications.ts` | Permission, registration, token upload/removal. |
| `mobile/src/service-worker.ts` | Push-only service worker. |
| `mobile/src/lib/utils/coachThreads.ts` | Notification targets and quick-reply actions. |
| `mobile/src/routes/+layout.svelte` | Push initialization after profile load. |
| `mobile/src/routes/profile/notifications/+page.svelte` | Settings UI. |
| `mobile/src/lib/notificationSettings.ts` | Frontend settings shape and defaults. |
| `backend/app/services/push.py` | FCM and VAPID send functions, `send_push_to_athlete`. |
| `backend/app/services/notification_prefs.py` | Settings shape, defaults, quiet hours. |
| `backend/app/services/coach_notifications.py` | Claims, coach-started threads, debriefs. |
| `backend/app/services/notification_scheduler.py` | Timed notifications. |
| `backend/app/routers/notifications.py` | Token, test and devices endpoints. |
| `backend/app/routers/coach.py` | Coach reply push. |

## iOS

Native iOS push is a scaffold. The Capacitor push plugin is installed, but the iOS project has no Firebase Messaging SDK, no `GoogleService-Info.plist`, no push entitlement, and `AppDelegate.swift` does not forward the APNs registration callbacks to Capacitor. The backend sends native tokens through FCM, which needs an FCM registration token. To finish it:

1. Create a Firebase project and add iOS app ID `com.astraphe.coach`.
2. Add `GoogleService-Info.plist` to `mobile/ios/App/App/` and the Firebase Messaging SDK, so the token posted to the backend is an FCM token.
3. Forward `didRegisterForRemoteNotificationsWithDeviceToken` / `didFailToRegisterForRemoteNotificationsWithError` in `AppDelegate.swift` as the Capacitor push docs describe.
4. In Xcode, enable Push Notifications and the Remote notifications background mode.
5. Set `FCM_SERVICE_ACCOUNT_JSON` on the backend.
6. Run `pnpm install`, `pnpm run build`, and `npx cap sync ios` from `mobile/`.

## Not Implemented

- Removing tokens that FCM or the push service report as gone (404/410); failed sends are only logged.
- Badge count management (FCM sends always set `badge: 1`).
- Notification email.
