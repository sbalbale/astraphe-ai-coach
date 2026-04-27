# Setup Guide

## Prerequisites

| Tool | Minimum Version | Install |
|---|---|---|
| Node.js | 20.x LTS | https://nodejs.org |
| Python | 3.12 | https://python.org |
| Docker | 24.x | https://docker.com |
| Supabase CLI | latest | `npm i -g supabase` |
| Google Cloud CLI | latest | https://cloud.google.com/sdk |

---

## 1. Clone and Configure

```bash
git clone https://github.com/seanbalbale/apex-coach.git
cd apex-coach
cp .env.example .env
```

**Edit `.env`:**

```bash
# Supabase
SUPABASE_URL=https://your-project-id.supabase.co
SUPABASE_ANON_KEY=eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9...
SUPABASE_SERVICE_ROLE_KEY=eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9...

# Gemini
GEMINI_API_KEY=AIzaSy...

# Garmin (from Garmin Developer Portal)
GARMIN_CONSUMER_KEY=your_garmin_consumer_key
GARMIN_CONSUMER_SECRET=your_garmin_consumer_secret
GARMIN_WEBHOOK_SECRET=your_garmin_webhook_hmac_secret

# WHOOP (from WHOOP Developer Portal)
WHOOP_CLIENT_ID=your_whoop_client_id
WHOOP_CLIENT_SECRET=your_whoop_client_secret
WHOOP_WEBHOOK_SECRET=your_whoop_webhook_hmac_secret

# App configuration
APP_ENV=development
APP_BASE_URL=http://localhost:8000
MOBILE_DEEP_LINK_SCHEME=apex
```

---

## 2. Supabase Local Setup

```bash
# Start local Supabase stack (PostgreSQL, Auth, Storage, Realtime)
supabase start

# Apply migrations
supabase db push

# Seed development data (creates a test athlete with 90 days of mock data)
supabase db seed

# Verify
supabase status
```

After `supabase start`, you'll see output like:
```
API URL: http://localhost:54321
Studio URL: http://localhost:54323
DB URL: postgresql://postgres:postgres@localhost:54322/postgres
```

Update your `.env` with the local URLs:
```bash
SUPABASE_URL=http://localhost:54321
```

---

## 3. Python Backend Setup

```bash
cd backend

# Create virtual environment
python -m venv .venv
source .venv/bin/activate  # Windows: .venv\Scripts\activate

# Install dependencies
pip install -r requirements.txt

# Verify environment
python -c "import fastapi, numpy, google.generativeai; print('Dependencies OK')"

# Run development server
uvicorn app.main:app --reload --port 8000
```

The FastAPI dev server runs at `http://localhost:8000`. The auto-generated OpenAPI docs are available at `http://localhost:8000/docs`.

**Backend project structure:**

```
backend/
├── app/
│   ├── main.py              # FastAPI app + router registration
│   ├── config.py            # Settings (pydantic-settings)
│   ├── dependencies.py      # Auth middleware, DB client injection
│   ├── routers/
│   │   ├── athlete.py
│   │   ├── workouts.py
│   │   ├── biometrics.py
│   │   ├── coach.py
│   │   ├── sync.py
│   │   └── plan.py
│   ├── services/
│   │   ├── algorithms.py    # TSS, CTL, ATL, TSB, Recovery
│   │   ├── ai_coach.py      # Gemini integration + RAG
│   │   ├── garmin.py        # Garmin API + OAuth
│   │   └── whoop.py         # WHOOP API + OAuth
│   └── models/
│       ├── athlete.py
│       ├── workout.py
│       └── biometrics.py
├── migrations/              # Supabase migration SQL files
├── seeds/                   # Development seed data
├── tests/
├── Dockerfile
└── requirements.txt
```

---

## 4. Mobile Frontend Setup

```bash
cd mobile

# Install Node dependencies
npm install

# Sync Capacitor plugins
npx cap sync

# Run web development server
npm run dev
```

The Svelte dev server runs at `http://localhost:5173`.

**To run on an iOS simulator:**
```bash
npm run build
npx cap sync ios
npx cap open ios
# Then press ▶ in Xcode
```

**To run on an Android emulator:**
```bash
npm run build
npx cap sync android
npx cap open android
# Then press ▶ in Android Studio
```

**Mobile project structure:**

```
mobile/
├── src/
│   ├── routes/
│   │   ├── +layout.svelte    # Root layout with nav
│   │   ├── +page.svelte      # Dashboard (redirects to /dashboard)
│   │   ├── dashboard/
│   │   ├── training/
│   │   ├── plan/
│   │   ├── zones/
│   │   ├── recovery/
│   │   ├── sleep/
│   │   ├── strain/
│   │   ├── coach/
│   │   ├── connect/
│   │   └── profile/
│   ├── lib/
│   │   ├── api.ts            # Typed API client
│   │   ├── auth.ts           # Supabase auth helpers
│   │   ├── healthkit.ts      # HealthKit Capacitor plugin wrapper
│   │   ├── stores/           # Svelte 5 rune-based state
│   │   └── components/       # Shared UI components
│   └── app.html
├── capacitor.config.ts
├── svelte.config.js
└── package.json
```

---

## 5. HealthKit Configuration (iOS)

HealthKit requires Info.plist permission strings and a background entitlement.

**In `ios/App/App/Info.plist`:**
```xml
<key>NSHealthShareUsageDescription</key>
<string>APEX reads your Apple Health data to analyze training load, recovery, and readiness.</string>
<key>NSHealthUpdateUsageDescription</key>
<string>APEX can write workout summaries to Apple Health.</string>
```

**In `ios/App/App/App.entitlements`:**
```xml
<key>com.apple.developer.healthkit</key>
<true/>
<key>com.apple.developer.healthkit.background-delivery</key>
<true/>
```

**Background runner configuration (`background-runner-config.json`):**
```json
{
  "HEALTHKIT_SYNC": {
    "identifier": "app.apex-coach.healthkit-sync",
    "interval": 3600,
    "runner": "runner.js",
    "event": "healthkitSync",
    "permissions": {
      "healthKit": {
        "read": [
          "HKWorkoutTypeIdentifier",
          "HKQuantityTypeIdentifierHeartRate",
          "HKQuantityTypeIdentifierHeartRateVariabilitySDNN",
          "HKQuantityTypeIdentifierRestingHeartRate",
          "HKCategoryTypeIdentifierSleepAnalysis",
          "HKQuantityTypeIdentifierOxygenSaturation",
          "HKQuantityTypeIdentifierBodyTemperature"
        ]
      }
    }
  }
}
```

---

## 6. Running Tests

```bash
# Backend unit tests
cd backend
pytest tests/ -v

# Backend tests with coverage report
pytest tests/ --cov=app --cov-report=html

# Key test suites
pytest tests/test_algorithms.py -v      # TSS/CTL/ATL formula tests
pytest tests/test_coach.py -v           # Gemini integration (mocked)
pytest tests/test_webhooks.py -v        # Garmin/WHOOP webhook tests

# Mobile tests
cd mobile
npm run test
```

---

## 7. Garmin API Access

**Important:** Garmin strictly gates their Connect API for enterprise use. You must complete this process before production deployment.

1. Register at https://developer.garmin.com
2. Complete the Health API application form
3. Wait for Garmin's review (typically 2–6 weeks)
4. After approval, you receive OAuth 1.0a consumer credentials
5. Add credentials to `.env`

During development, use Garmin's **sandbox environment** with test device simulators. The webhook endpoint must be publicly reachable — use `ngrok` or Cloudflare Tunnel for local development:

```bash
# Expose local API to the internet for webhook testing
ngrok http 8000
# Copy the https URL, set GARMIN_WEBHOOK_URL in Garmin developer portal
```

---

## 8. Verifying the Full Stack

With all services running, verify end-to-end functionality:

```bash
# 1. Check API health
curl http://localhost:8000/health
# Expected: {"status": "ok", "version": "1.0.0"}

# 2. Create a test athlete (using Supabase seed JWT)
curl -X GET http://localhost:8000/v1/athlete/state \
  -H "Authorization: Bearer $(supabase gen jwt --uid test-user-id)"

# 3. Ingest a test workout
curl -X POST http://localhost:8000/v1/workouts \
  -H "Authorization: Bearer <jwt>" \
  -H "Content-Type: application/json" \
  -d '{
    "source": "manual",
    "sport": "run",
    "started_at": "2026-04-26T12:00:00Z",
    "ended_at": "2026-04-26T12:45:00Z",
    "distance_m": 9000,
    "avg_hr": 135
  }'

# 4. Ask the coach
curl -X POST http://localhost:8000/v1/coach/message \
  -H "Authorization: Bearer <jwt>" \
  -H "Content-Type: application/json" \
  --no-buffer \
  -d '{"message": "How is my fitness trending?"}'
```
