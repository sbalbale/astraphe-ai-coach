# Push Notifications

ASTRAPE supports real-time push notifications on iOS, Android, and web (PWA).

---

## How It Works

```
iOS / Android                     Web (Browser)
─────────────                     ─────────────
Capacitor PushNotifications   →   Web Push API + Service Worker
         ↓                                   ↓
    FCM token                       VAPID subscription JSON
         ↓                                   ↓
POST /v1/notifications/token    POST /v1/notifications/token
         ↓                                   ↓
    push_tokens table (Supabase)  push_tokens table (Supabase)
         ↓                                   ↓
    firebase-admin (FCM)             pywebpush (VAPID)
```

Notifications are currently triggered when:
- **Coach messages** — after the AI generates a reply (respects `coach` setting)
- *(Readiness / Workouts / Insights — hookable from any backend endpoint via `send_push_to_athlete`)*

---

## Setup

### 1. Firebase Project (iOS + Android)

1. Go to [console.firebase.google.com](https://console.firebase.google.com) and create a project.
2. Add an **iOS app** (`com.astrape.coach`) and download `GoogleService-Info.plist` → place in `mobile/ios/App/App/`.
3. Add an **Android app** (`com.astrape.coach`) and download `google-services.json` → place in `mobile/android/app/`.
4. Go to **Project Settings → Service Accounts → Generate new private key** — download the JSON file.
5. Minify the JSON to a single line and set it as `FCM_SERVICE_ACCOUNT_JSON` in your backend `.env`.

### 2. VAPID Keys (Web Push)

```bash
npx web-push generate-vapid-keys
```

Copy the output into your `.env` files:

**`backend/.env`**
```
VAPID_PUBLIC_KEY=<your-public-key>
VAPID_PRIVATE_KEY=<your-private-key>
VAPID_SUBJECT=mailto:your@email.com
```

**`mobile/.env`** (or `mobile/.env.local`)
```
VITE_VAPID_PUBLIC_KEY=<same-public-key>
```

### 3. Install Capacitor Plugin

```bash
cd mobile
pnpm install          # @capacitor/push-notifications is now in package.json
npx cap sync          # syncs plugin to native projects
```

### 4. iOS — Enable Push Capability

In Xcode:
1. Open `mobile/ios/App/App.xcworkspace`
2. Select the `App` target → **Signing & Capabilities**
3. Click **+ Capability** → add **Push Notifications**
4. Also add **Background Modes** → check **Remote notifications**

### 5. Run the DB Migration

```bash
supabase db push
# or apply manually:
psql $DATABASE_URL < supabase/migrations/20260519200000_push_tokens.sql
```

---

## Backend Environment Variables

| Variable | Required | Description |
|---|---|---|
| `FCM_SERVICE_ACCOUNT_JSON` | iOS/Android | Firebase service account JSON (single-line string) |
| `VAPID_PUBLIC_KEY` | Web | VAPID public key |
| `VAPID_PRIVATE_KEY` | Web | VAPID private key |
| `VAPID_SUBJECT` | Web | `mailto:` URI identifying the server |

All three are optional at runtime — if absent the push service degrades gracefully (returns 0 sends, no crash).

---

## API

### Register a token
```
POST /v1/notifications/token
Authorization: Bearer <jwt>

{ "token": "<fcm-or-vapid-subscription>", "platform": "ios" | "android" | "web" }
```

### Unregister a token
```
DELETE /v1/notifications/token
Authorization: Bearer <jwt>

{ "token": "<token>", "platform": "ios" | "android" | "web" }
```

### Send a test notification *(non-production only)*
```
POST /v1/notifications/test
Authorization: Bearer <jwt>
```

---

## Sending Notifications from Backend Code

```python
from app.services.push import send_push_to_athlete

sent = send_push_to_athlete(
    athlete_id=athlete_id,
    title="ASTRAPE",
    body="Your readiness score is ready.",
    db=db,
    data={"url": "/dashboard"},        # optional — navigates on tap
    notification_type="readiness",     # optional — checks notification_settings
)
```

`notification_type` maps to the athlete's `notification_settings` JSON column:
- `"readiness"` — Daily Readiness toggle
- `"coach"` — Coach Messages toggle
- `"workouts"` — Workout Reminders toggle
- `"insights"` — Weekly Insights toggle

---

## Notification Settings

Users control which types they receive at **Profile → Notifications**. Settings are stored in the `notification_settings` JSONB column on the `athletes` table. The page also handles permission requests — first time a user enables a toggle it calls `Notification.requestPermission()` and registers the token.

---

## Relevant Files

| File | Purpose |
|---|---|
| `mobile/src/lib/services/pushNotifications.ts` | Permission request, token registration, listener setup |
| `mobile/static/sw.js` | Web push service worker (shows notification, handles tap) |
| `mobile/src/routes/profile/notifications/+page.svelte` | Notification settings UI |
| `mobile/src/routes/+layout.svelte` | Initializes push after auth |
| `backend/app/services/push.py` | FCM + VAPID send functions |
| `backend/app/routers/notifications.py` | Token register/unregister endpoints |
| `backend/app/routers/coach.py` | Example trigger (after coach reply) |
| `supabase/migrations/20260519200000_push_tokens.sql` | `push_tokens` table + RLS |
