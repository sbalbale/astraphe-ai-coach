# Tech Stack

## Decision Summary

Every technology choice in APEX was made against three criteria: mobile performance, free-tier economics at launch, and mathematical precision for physiological computation. This document explains each major decision.

---

## Frontend

### Svelte 5 + Capacitor

**Why Svelte 5 over React Native:**

React Native imposes a JavaScript bridge between the UI thread and the native layer. For a data-dense coaching dashboard with real-time chart updates, this bridge introduces non-trivial latency and makes fine-grained animation control difficult. Svelte 5's rune-based reactivity system compiles to vanilla DOM operations with no virtual DOM diffing overhead — the resulting JavaScript bundle is typically 30–60% smaller than an equivalent React application.

Capacitor wraps the compiled Svelte app in a native WebView and provides typed TypeScript bindings to native device APIs. Unlike Expo/React Native, Capacitor has no opinions about your JavaScript framework — it simply exposes native plugins. This means APEX gains full access to HealthKit, background execution, push notifications, and biometric auth without any framework-imposed constraints.

**Key packages:**

| Package | Version | Purpose |
|---|---|---|
| `svelte` | 5.x | Reactive UI framework |
| `@sveltejs/kit` | 2.x | Routing, SSR scaffold |
| `@capacitor/core` | 6.x | Native bridge runtime |
| `@capacitor/ios` | 6.x | iOS target |
| `@capacitor/android` | 6.x | Android target |
| `@capacitor/background-runner` | latest | HealthKit background sync |
| `layerchart` | latest | D3-backed SVG chart library |
| `d3` | 7.x | Scale, axis, and path utilities |

### LayerChart (D3-backed SVG Visualization)

LayerChart provides composable, declarative chart primitives that render as SVG elements, giving direct DOM access for custom animations. The Spectral glassmorphism aesthetic requires gradient fills on chart areas, custom axis tick styling, and animated line draws — none of which are achievable without direct SVG control. LayerChart's architecture (each chart is composed of `Layer*` Svelte components) maps naturally to APEX's data model where multiple metrics overlay on shared axes (e.g., CTL and ATL on the same timeline chart).

---

## Backend

### Python 3.12 + FastAPI

Python is the only serious choice for the computation layer. NumPy's vectorized array operations are the idiomatic way to compute exponential weighted moving averages over large TSS history arrays, and the scientific Python ecosystem (SciPy, Pandas) provides audited implementations of every statistical method APEX needs. FastAPI's async request handling, automatic OpenAPI schema generation, and Pydantic v2 model validation make it the modern standard for Python APIs.

**Key packages:**

| Package | Version | Purpose |
|---|---|---|
| `fastapi` | 0.111+ | Async API framework |
| `pydantic` | 2.x | Request/response validation |
| `numpy` | 1.26+ | Vectorized metric computation |
| `pandas` | 2.x | Time-series data manipulation |
| `httpx` | latest | Async HTTP client (Garmin, WHOOP, Gemini) |
| `supabase-py` | 2.x | Supabase client |
| `google-generativeai` | latest | Gemini API SDK |
| `python-jose` | latest | JWT validation |
| `cryptography` | latest | OAuth token encryption |

### Google Cloud Run

Cloud Run is the correct deployment target for a stateless FastAPI container at this scale. It charges only for actual request processing time (per 100ms), scales to zero between uses (critical for a startup with variable traffic), and cold starts a Python FastAPI container in under 2 seconds. The alternative — a persistent VM or Kubernetes cluster — would cost 5–10x more per month with no performance benefit at sub-10k DAU scale.

**Cloud Run configuration:**

```yaml
# cloud-run-service.yaml
apiVersion: serving.knative.dev/v1
kind: Service
metadata:
  name: apex-api
spec:
  template:
    spec:
      containerConcurrency: 80
      timeoutSeconds: 300
      containers:
        - image: gcr.io/PROJECT_ID/apex-api:latest
          resources:
            limits:
              cpu: "2"
              memory: 1Gi
          env:
            - name: SUPABASE_URL
              valueFrom:
                secretKeyRef:
                  name: apex-secrets
                  key: supabase-url
```

---

## AI Layer

### Google Gemini 1.5 Pro

Gemini 1.5 Pro is the AI backbone of the APEX coaching agent. The choice of Gemini over alternatives (OpenAI GPT-4, Anthropic Claude) was made on three grounds:

**1. Structured output and function calling.**
Gemini 1.5 Pro's function calling API allows APEX to define a schema for `get_athlete_state`, `get_recent_workouts`, and `get_sleep_summary` as callable tools. The model can autonomously decide to fetch fresher data mid-conversation rather than relying solely on the context injected at the start of a session. This creates a genuinely agentic experience where the coach can say "let me check your most recent HRV before answering."

**2. Long context window (1M tokens).**
A single Gemini 1.5 Pro call can hold an entire season of training logs, all prior coaching conversations, and rich physiological context simultaneously. This eliminates the need for aggressive context truncation and makes multi-month retrospective analysis ("why did I overtrain in February?") tractable in a single inference pass.

**3. Google Cloud ecosystem integration.**
Running on Google Cloud Run means Gemini API calls stay within Google's network, reducing latency and simplifying IAM-based authentication (no API key management required in production — use Workload Identity instead).

**Model configuration:**

```python
import google.generativeai as genai

genai.configure(api_key=settings.GEMINI_API_KEY)

model = genai.GenerativeModel(
    model_name="gemini-1.5-pro",
    generation_config=genai.GenerationConfig(
        temperature=0.4,      # Low: coaching advice should be consistent
        top_p=0.85,
        max_output_tokens=512,  # Coaches are concise
    ),
    system_instruction=APEX_SYSTEM_PROMPT,
)
```

---

## Data Layer

### Supabase PostgreSQL + pgvector

Supabase provides three things APEX needs from a single managed service: a relational PostgreSQL database, Row Level Security for multi-tenant data isolation, and the pgvector extension for embedding-based similarity search.

**Why pgvector instead of a dedicated vector database (Pinecone, Weaviate):**
At APEX's launch scale, storing coaching memory embeddings alongside relational athlete data in the same PostgreSQL instance is operationally simpler, cheaper (no additional service), and fast enough. A pgvector HNSW index on 100k embedding vectors returns nearest-neighbor results in under 10ms — more than adequate for a conversational RAG pipeline where the user's perceived latency is dominated by the Gemini inference call (300–800ms), not the retrieval step.

**pgvector index:**
```sql
CREATE INDEX ON coach_memories
USING hnsw (embedding vector_cosine_ops)
WITH (m = 16, ef_construction = 64);
```

---

## External APIs

### Apple HealthKit (via Capacitor Background Runner)

HealthKit data is accessed entirely on-device. The Capacitor Background Runner plugin executes a JavaScript worker that queries HealthKit for new samples since the last sync timestamp, serializes them, and POSTs the batch to the APEX API. This approach ensures App Store compliance (data never leaves the device to a third-party service directly), respects iOS Background App Refresh constraints, and avoids any Apple enterprise developer program requirements.

### Garmin Connect API

Garmin's Connect IQ API is enterprise-gated. A formal commercial application must be submitted to Garmin's developer program before production access is granted. During development, the APEX backend uses Garmin's webhook push notifications to receive workout summaries when they sync from the device. This is push-based (Garmin calls APEX) rather than poll-based (APEX calls Garmin), which is critical for low-latency data freshness.

**Required Garmin API scopes:**
- `activity_export` — GPS and workout file access
- `daily_summary` — Steps, floors, daily HR stats
- `health_snapshot` — HRV, SpO2, respiration
- `sleep` — Sleep stage data

### WHOOP API

WHOOP uses standard OAuth 2.0 with a refresh token flow. APEX stores the access and refresh tokens encrypted in Supabase Vault and refreshes them proactively 5 minutes before expiry. WHOOP's key data contributions to APEX are recovery score, strain score, and detailed sleep stage breakdowns (WHOOP's sleep staging is generally considered more granular than Apple's for HRV-based recovery assessment).
