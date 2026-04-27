# Deployment

## Infrastructure Overview

```
┌─────────────────────────────────────────────────────┐
│                  Google Cloud Platform              │
│                                                     │
│  Cloud Run          Cloud Build       Artifact      │
│  (apex-api)    ←    (CI/CD)     ←    Registry       │
│                                                     │
│  Cloud Tasks        Secret Manager   Cloud Logging  │
│  (TSS recompute)    (API keys)       (structured)   │
└────────────────────────────┬────────────────────────┘
                             │
┌────────────────────────────▼────────────────────────┐
│                     Supabase                        │
│  PostgreSQL + pgvector      Auth                    │
│  Realtime subscriptions     Storage (fit files)     │
└─────────────────────────────────────────────────────┘
```

---

## 1. Google Cloud Setup

```bash
# Authenticate
gcloud auth login
gcloud auth application-default login

# Create project
gcloud projects create apex-coach-prod --name="APEX Coach"
gcloud config set project apex-coach-prod

# Enable required APIs
gcloud services enable \
  run.googleapis.com \
  cloudbuild.googleapis.com \
  artifactregistry.googleapis.com \
  secretmanager.googleapis.com \
  cloudtasks.googleapis.com \
  logging.googleapis.com

# Create Artifact Registry repository
gcloud artifacts repositories create apex-images \
  --repository-format=docker \
  --location=us-central1 \
  --description="APEX API container images"
```

---

## 2. Secrets Management

All sensitive configuration is stored in Google Secret Manager. The Cloud Run service accesses secrets via Workload Identity — no API keys in environment variables or config files.

```bash
# Store each secret
gcloud secrets create supabase-url --replication-policy="automatic"
echo -n "https://your-project.supabase.co" | \
  gcloud secrets versions add supabase-url --data-file=-

gcloud secrets create supabase-service-role-key --replication-policy="automatic"
echo -n "eyJhbGci..." | \
  gcloud secrets versions add supabase-service-role-key --data-file=-

gcloud secrets create gemini-api-key --replication-policy="automatic"
echo -n "AIzaSy..." | \
  gcloud secrets versions add gemini-api-key --data-file=-

gcloud secrets create garmin-consumer-secret --replication-policy="automatic"
echo -n "your_secret" | \
  gcloud secrets versions add garmin-consumer-secret --data-file=-

gcloud secrets create whoop-client-secret --replication-policy="automatic"
echo -n "your_secret" | \
  gcloud secrets versions add whoop-client-secret --data-file=-

# Grant Cloud Run service account access
PROJECT_NUMBER=$(gcloud projects describe apex-coach-prod --format='value(projectNumber)')
SA="serviceAccount:${PROJECT_NUMBER}-compute@developer.gserviceaccount.com"

for secret in supabase-url supabase-service-role-key gemini-api-key \
              garmin-consumer-secret whoop-client-secret; do
  gcloud secrets add-iam-policy-binding $secret \
    --member="$SA" \
    --role="roles/secretmanager.secretAccessor"
done
```

---

## 3. Dockerfile

```dockerfile
FROM python:3.12-slim AS builder

WORKDIR /app

# Install build dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

# Install Python dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir --user -r requirements.txt

# ─── Production image ────────────────────────────────────
FROM python:3.12-slim

WORKDIR /app

# Copy installed packages from builder
COPY --from=builder /root/.local /root/.local

# Copy application code
COPY app/ ./app/

# Ensure scripts in .local are usable
ENV PATH=/root/.local/bin:$PATH

# Cloud Run uses PORT env var
ENV PORT=8080
EXPOSE 8080

# Non-root user for security
RUN useradd --create-home appuser
USER appuser

CMD ["uvicorn", "app.main:app", \
     "--host", "0.0.0.0", \
     "--port", "8080", \
     "--workers", "1", \
     "--loop", "uvloop", \
     "--http", "httptools"]
```

---

## 4. Cloud Build CI/CD Pipeline

**`cloudbuild.yaml`** (runs on every push to `main`):

```yaml
steps:
  # Step 1: Run tests
  - name: python:3.12
    id: test
    entrypoint: bash
    args:
      - -c
      - |
        pip install -r backend/requirements.txt
        cd backend
        pytest tests/ -v --tb=short
    env:
      - 'PYTHONPATH=/workspace/backend'

  # Step 2: Build container image
  - name: gcr.io/cloud-builders/docker
    id: build
    args:
      - build
      - -t
      - us-central1-docker.pkg.dev/$PROJECT_ID/apex-images/apex-api:$COMMIT_SHA
      - -t
      - us-central1-docker.pkg.dev/$PROJECT_ID/apex-images/apex-api:latest
      - -f
      - backend/Dockerfile
      - backend/
    waitFor: [test]

  # Step 3: Push to Artifact Registry
  - name: gcr.io/cloud-builders/docker
    id: push
    args:
      - push
      - --all-tags
      - us-central1-docker.pkg.dev/$PROJECT_ID/apex-images/apex-api
    waitFor: [build]

  # Step 4: Deploy to Cloud Run
  - name: gcr.io/google.com/cloudsdktool/cloud-sdk
    id: deploy
    entrypoint: gcloud
    args:
      - run
      - deploy
      - apex-api
      - --image=us-central1-docker.pkg.dev/$PROJECT_ID/apex-images/apex-api:$COMMIT_SHA
      - --region=us-central1
      - --platform=managed
      - --no-allow-unauthenticated
      - --min-instances=0
      - --max-instances=10
      - --concurrency=80
      - --cpu=2
      - --memory=1Gi
      - --timeout=300
      - --set-secrets=SUPABASE_URL=supabase-url:latest
      - --set-secrets=SUPABASE_SERVICE_ROLE_KEY=supabase-service-role-key:latest
      - --set-secrets=GEMINI_API_KEY=gemini-api-key:latest
      - --set-secrets=GARMIN_CONSUMER_SECRET=garmin-consumer-secret:latest
      - --set-secrets=WHOOP_CLIENT_SECRET=whoop-client-secret:latest
    waitFor: [push]

options:
  logging: CLOUD_LOGGING_ONLY
  machineType: E2_HIGHCPU_8

timeout: 1200s
```

---

## 5. First Deployment

```bash
# Build and push manually for first deploy
cd backend
docker build -t us-central1-docker.pkg.dev/apex-coach-prod/apex-images/apex-api:v1.0.0 .

# Authenticate Docker with Artifact Registry
gcloud auth configure-docker us-central1-docker.pkg.dev

# Push
docker push us-central1-docker.pkg.dev/apex-coach-prod/apex-images/apex-api:v1.0.0

# Deploy
gcloud run deploy apex-api \
  --image=us-central1-docker.pkg.dev/apex-coach-prod/apex-images/apex-api:v1.0.0 \
  --region=us-central1 \
  --platform=managed \
  --no-allow-unauthenticated \
  --min-instances=0 \
  --max-instances=10 \
  --set-secrets=SUPABASE_URL=supabase-url:latest,SUPABASE_SERVICE_ROLE_KEY=supabase-service-role-key:latest,GEMINI_API_KEY=gemini-api-key:latest

# Get the service URL
gcloud run services describe apex-api \
  --region=us-central1 \
  --format='value(status.url)'
```

---

## 6. Supabase Production Setup

```bash
# Link to production project
supabase link --project-ref your-project-ref

# Push migrations to production
supabase db push

# Verify pgvector extension
supabase db execute "SELECT extname, extversion FROM pg_extension WHERE extname = 'vector';"
```

**Required Supabase configuration in the dashboard:**

1. **Auth → URL Configuration:** Set Site URL to `https://apex-coach.app` and add redirect URLs for the mobile deep link `apex://auth/callback`
2. **Database → Extensions:** Verify `vector` extension is enabled
3. **API → JWT Settings:** Note the JWT secret for backend verification
4. **Realtime → Replication:** Enable replication for `tss_history` and `biometrics` tables

---

## 7. Mobile App Deployment

### iOS (App Store)

```bash
cd mobile

# Production build
npm run build:production

# Sync to Xcode
npx cap sync ios
npx cap open ios
```

In Xcode:
1. Set Bundle ID: `app.apex-coach.ios`
2. Configure signing with your Apple Developer certificate
3. Set the production API URL in `capacitor.config.ts`
4. Archive → Distribute → TestFlight or App Store

**App Store Review Notes:**
- HealthKit usage strings must match actual data access
- Background fetch usage must be demonstrated in the review notes
- The app must function in airplane mode for App Store compliance (show cached data gracefully)

### Android (Play Store)

```bash
npm run build:production
npx cap sync android
npx cap open android
```

In Android Studio: Generate Signed Bundle → Upload to Play Console

---

## 8. Monitoring

### Structured Logging

The FastAPI app logs all requests and errors as structured JSON to Cloud Logging:

```python
import structlog

log = structlog.get_logger()

# In each route handler:
log.info(
    "coach_query",
    athlete_id=athlete_id,
    message_length=len(message),
    conversation_id=conversation_id,
)
```

### Key Alerts to Configure in Cloud Monitoring

| Alert | Condition | Notification |
|---|---|---|
| API error rate | 5xx rate > 5% over 5 min | PagerDuty |
| Cold start latency | p95 > 5s | Email |
| Gemini API quota | Usage > 80% of daily limit | Email |
| DB connection pool | Wait time > 100ms | Email |
| Coach message latency | p95 > 3s | Slack |

```bash
# Create latency alert example
gcloud monitoring policies create \
  --policy-from-file=monitoring/coach-latency-alert.json
```

---

## 9. Cost Estimates

At 500 daily active athletes (realistic Year 1 target):

| Service | Usage | Monthly Cost |
|---|---|---|
| Cloud Run | ~2M requests/month, avg 200ms | ~$12 |
| Artifact Registry | ~5 images stored | ~$1 |
| Cloud Build | ~60 builds/month | ~$3 |
| Supabase (Pro) | 8GB database, 50GB storage | $25 |
| Gemini 1.5 Pro | ~30k messages/month × ~2k tokens | ~$18 |
| **Total** | | **~$59/month** |

At 10,000 DAU:

| Service | Monthly Cost |
|---|---|
| Cloud Run | ~$180 |
| Supabase (Team) | $599 |
| Gemini 1.5 Pro | ~$360 |
| **Total** | **~$1,150/month** |
