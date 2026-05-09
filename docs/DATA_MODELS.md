# Data Models

## Database: Supabase PostgreSQL

All tables enforce Row Level Security. The policy pattern is uniform: `athlete_id IN (SELECT id FROM athletes WHERE user_id = auth.uid())`. No cross-athlete data access is possible at the database layer regardless of what the API layer requests.

---

## Schema

### `athletes`

The root entity. One row per registered user. Automatically created by the `on_auth_user_created` trigger on `auth.users`.

```sql
CREATE TABLE athletes (
  id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id         UUID NOT NULL REFERENCES auth.users(id) ON DELETE CASCADE,

  -- Identity
  display_name    TEXT NOT NULL,
  city            TEXT,
  country_code    CHAR(2),
  created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),

  -- Physiological anchors (updated via test or AI estimation)
  date_of_birth   DATE,
  weight_kg       NUMERIC(5,2),
  height_cm       NUMERIC(5,1),
  max_hr          SMALLINT,           -- bpm
  resting_hr      SMALLINT,           -- bpm (baseline, not daily reading)
  ftp_watts       SMALLINT,           -- Functional Threshold Power
  threshold_hr    SMALLINT,           -- Lactate threshold HR
  threshold_pace  NUMERIC(5,2),       -- min/km at threshold
  vo2max_est      NUMERIC(4,1),       -- ml/kg/min

  -- Training configuration
  sport_focus     TEXT[] DEFAULT '{"run","bike"}',
  weekly_tss_target SMALLINT DEFAULT 400,

  -- Subscription tier (source of truth; prefer over auth metadata)
  tier            TEXT NOT NULL DEFAULT 'free'
                  CHECK (tier IN ('free', 'trial', 'premium')),

  CONSTRAINT athletes_user_id_unique UNIQUE (user_id)
);

ALTER TABLE athletes ENABLE ROW LEVEL SECURITY;
CREATE POLICY "athletes_self_access" ON athletes
  FOR ALL USING (user_id = auth.uid());
```

> **Tier management:** The `tier` column is the authoritative source for feature gating. It replaces the earlier approach of reading from `auth.users` metadata. Premium gates are enforced server-side by `get_current_user_tier()` in `app/dependencies.py`. Use the migration `20260503_move_tier_to_athletes.sql` to backfill from metadata.

---

### `workouts`

Normalized representation of a completed training session, regardless of source device.

```sql
CREATE TABLE workouts (
  id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  athlete_id      UUID NOT NULL REFERENCES athletes(id) ON DELETE CASCADE,

  -- Source tracking
  source          TEXT NOT NULL CHECK (source IN ('garmin','whoop','healthkit','manual')),
  external_id     TEXT,               -- ID from the originating platform

  -- Classification
  sport           TEXT NOT NULL CHECK (sport IN ('run','bike','swim','strength','other')),
  title           TEXT,

  -- Timing
  started_at      TIMESTAMPTZ NOT NULL,
  ended_at        TIMESTAMPTZ NOT NULL,
  duration_secs   INTEGER NOT NULL GENERATED ALWAYS AS (
                    EXTRACT(EPOCH FROM (ended_at - started_at))::INTEGER
                  ) STORED,

  -- Volume
  distance_m      NUMERIC(10,2),
  elevation_gain_m NUMERIC(8,2),

  -- Intensity
  avg_hr          SMALLINT,
  max_hr          SMALLINT,
  avg_power_w     SMALLINT,
  norm_power_w    SMALLINT,           -- Normalized Power (cycling)
  avg_pace_sec_km SMALLINT,           -- seconds per km

  -- HR zone distributions (percentage per zone, 0–100)
  hr_zone_0_pct   NUMERIC(5,2),
  hr_zone_1_pct   NUMERIC(5,2),
  hr_zone_2_pct   NUMERIC(5,2),
  hr_zone_3_pct   NUMERIC(5,2),
  hr_zone_4_pct   NUMERIC(5,2),
  hr_zone_5_pct   NUMERIC(5,2),

  -- Computed load
  tss             NUMERIC(6,2),       -- Training Stress Score
  if_value        NUMERIC(4,3),       -- Intensity Factor (NP / FTP)
  strain_score    NUMERIC(5,2),       -- WHOOP/zone-weighted cardiovascular load (0–21)

  -- Raw data reference
  fit_file_url    TEXT,               -- GCS path to .fit file

  created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),

  CONSTRAINT workouts_external_id_unique UNIQUE (source, external_id)
);

CREATE INDEX workouts_athlete_started_at ON workouts (athlete_id, started_at DESC);

ALTER TABLE workouts ENABLE ROW LEVEL SECURITY;
CREATE POLICY "workouts_athlete_access" ON workouts
  FOR ALL USING (
    athlete_id IN (SELECT id FROM athletes WHERE user_id = auth.uid())
  );
```

---

### `biometrics`

One row per athlete per day. Stores aggregated daily physiological readings.

```sql
CREATE TABLE biometrics (
  id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  athlete_id      UUID NOT NULL REFERENCES athletes(id) ON DELETE CASCADE,
  date            DATE NOT NULL,

  -- Heart Rate Variability
  hrv_rmssd       NUMERIC(6,2),       -- milliseconds
  hrv_source      TEXT CHECK (hrv_source IN ('whoop','garmin','healthkit')),

  -- Resting Heart Rate
  resting_hr      SMALLINT,           -- bpm (lowest during sleep)

  -- Sleep
  sleep_duration_min   SMALLINT,
  sleep_score          SMALLINT,      -- 0–100
  sleep_deep_pct       NUMERIC(4,1),
  sleep_rem_pct        NUMERIC(4,1),
  sleep_light_pct      NUMERIC(4,1),
  sleep_awake_pct      NUMERIC(4,1),
  sleep_bedtime        TIMESTAMPTZ,
  sleep_wakeup         TIMESTAMPTZ,

  -- Body metrics
  skin_temp_deviation  NUMERIC(4,2),  -- °F deviation from baseline
  spo2_pct             NUMERIC(4,1),

  -- Computed scores
  recovery_score       SMALLINT,      -- 0–100 ASTRAPE composite score
  strain_score         NUMERIC(5,2),  -- Daily cardiovascular load (0–21)

  CONSTRAINT biometrics_athlete_date_unique UNIQUE (athlete_id, date)
);

CREATE INDEX biometrics_athlete_date ON biometrics (athlete_id, date DESC);

ALTER TABLE biometrics ENABLE ROW LEVEL SECURITY;
CREATE POLICY "biometrics_athlete_access" ON biometrics
  FOR ALL USING (
    athlete_id IN (SELECT id FROM athletes WHERE user_id = auth.uid())
  );
```

---

### `tss_history`

A materialized daily TSS ledger. Source of truth for all CTL/ATL calculations. Separate from `workouts` because (a) a single day may have multiple workouts and (b) rest days must be explicitly represented as `daily_tss = 0` to correctly decay the exponential moving averages.

```sql
CREATE TABLE tss_history (
  id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  athlete_id      UUID NOT NULL REFERENCES athletes(id) ON DELETE CASCADE,
  date            DATE NOT NULL,
  daily_tss       NUMERIC(7,2) NOT NULL DEFAULT 0,
  workout_ids     UUID[],             -- contributing workouts

  -- Cached computed values (updated after each new entry)
  ctl             NUMERIC(6,2),       -- Chronic Training Load (fitness)
  atl             NUMERIC(6,2),       -- Acute Training Load (fatigue)
  tsb             NUMERIC(7,2),       -- Training Stress Balance (form)

  CONSTRAINT tss_history_athlete_date_unique UNIQUE (athlete_id, date)
);

CREATE INDEX tss_history_athlete_date ON tss_history (athlete_id, date DESC);

ALTER TABLE tss_history ENABLE ROW LEVEL SECURITY;
CREATE POLICY "tss_history_athlete_access" ON tss_history
  FOR ALL USING (
    athlete_id IN (SELECT id FROM athletes WHERE user_id = auth.uid())
  );
```

---

### `training_plans`

Structured training blocks. Each row is one planned workout session. Can be created manually or generated by the AI coach.

```sql
CREATE TABLE training_plans (
  id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  athlete_id      UUID NOT NULL REFERENCES athletes(id) ON DELETE CASCADE,

  planned_date    DATE NOT NULL,
  sport           TEXT NOT NULL,
  title           TEXT NOT NULL,
  description     TEXT,
  duration_min    SMALLINT,
  target_tss      SMALLINT,
  target_zones    JSONB,              -- e.g., {"Z2": 60, "Z4": 20}
  primary_zone    TEXT,               -- e.g., "Endurance", "Threshold", "VO2max"
  structure       JSONB,              -- Array of interval blocks with label/duration_min/zone
  goal            TEXT,               -- AI-generated session goal narrative
  context         TEXT,               -- Additional AI coaching context / prescription notes

  status          TEXT NOT NULL DEFAULT 'planned'
                  CHECK (status IN ('planned','done','skipped','modified')),

  completed_workout_id UUID REFERENCES workouts(id),

  generated_by    TEXT DEFAULT 'astrape_ai',  -- 'astrape_ai' or 'manual'
  created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

ALTER TABLE training_plans ENABLE ROW LEVEL SECURITY;
CREATE POLICY "training_plans_athlete_access" ON training_plans
  FOR ALL USING (
    athlete_id IN (SELECT id FROM athletes WHERE user_id = auth.uid())
  );
```

---

### `oauth_tokens`

Encrypted storage for third-party API credentials.

```sql
CREATE TABLE oauth_tokens (
  id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  athlete_id      UUID NOT NULL REFERENCES athletes(id) ON DELETE CASCADE,
  provider        TEXT NOT NULL CHECK (provider IN ('garmin','whoop')),

  -- Stored encrypted via Supabase Vault
  access_token    TEXT NOT NULL,
  refresh_token   TEXT,
  expires_at      TIMESTAMPTZ,
  scope           TEXT[],

  created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),

  CONSTRAINT oauth_tokens_athlete_provider_unique UNIQUE (athlete_id, provider)
);

-- No RLS needed — this table is only accessed by the server-side API,
-- never by the client directly. API layer enforces athlete ownership.
```

---

### `coach_conversations`

Conversation threads for the AI coach. One row per chat session.

```sql
CREATE TABLE coach_conversations (
  id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  athlete_id      UUID NOT NULL REFERENCES athletes(id) ON DELETE CASCADE,
  title           TEXT,               -- Auto-generated from first user message (≤80 chars)
  created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

ALTER TABLE coach_conversations ENABLE ROW LEVEL SECURITY;
CREATE POLICY "coach_conversations_athlete_access" ON coach_conversations
  FOR ALL USING (
    athlete_id IN (SELECT id FROM athletes WHERE user_id = auth.uid())
  );
```

---

### `coach_messages`

Individual messages within a conversation thread.

```sql
CREATE TABLE coach_messages (
  id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  athlete_id      UUID NOT NULL REFERENCES athletes(id) ON DELETE CASCADE,
  conversation_id UUID NOT NULL REFERENCES coach_conversations(id) ON DELETE CASCADE,
  role            TEXT NOT NULL CHECK (role IN ('user','assistant')),
  content         TEXT NOT NULL,
  image_urls      TEXT[] DEFAULT '{}',
  created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX coach_messages_conversation ON coach_messages (conversation_id, created_at ASC);

ALTER TABLE coach_messages ENABLE ROW LEVEL SECURITY;
CREATE POLICY "coach_messages_athlete_access" ON coach_messages
  FOR ALL USING (
    athlete_id IN (SELECT id FROM athletes WHERE user_id = auth.uid())
  );
```

---

### `coach_memories`

Long-term memory store for the ASTRAPE AI agent. Each row is a semantically meaningful chunk of coaching history, stored alongside its vector embedding for similarity search.

```sql
CREATE TABLE coach_memories (
  id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  athlete_id      UUID NOT NULL REFERENCES athletes(id) ON DELETE CASCADE,
  content         TEXT NOT NULL,
  embedding       VECTOR(768),        -- text-embedding-004 output
  created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX ON coach_memories
  USING hnsw (embedding vector_cosine_ops)
  WITH (m = 16, ef_construction = 64);

ALTER TABLE coach_memories ENABLE ROW LEVEL SECURITY;
CREATE POLICY "coach_memories_athlete_access" ON coach_memories
  FOR ALL USING (
    athlete_id IN (SELECT id FROM athletes WHERE user_id = auth.uid())
  );
```

---

### `ai_analysis_cache`

Cached AI-generated insight strings, keyed by `(athlete_id, analysis_type, scope_key)`. A fingerprint of the input context prevents stale cache hits when underlying data changes.

```sql
CREATE TABLE ai_analysis_cache (
  id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  athlete_id      UUID NOT NULL REFERENCES athletes(id) ON DELETE CASCADE,
  analysis_type   TEXT NOT NULL,      -- 'recovery', 'sleep', 'strain', 'training_load', 'dashboard_summary', 'workout'
  scope_key       TEXT NOT NULL,      -- YYYY-MM-DD or workout_id
  fingerprint     TEXT NOT NULL,      -- SHA-256 of context dict
  content         TEXT NOT NULL,      -- The cached insight string
  model           TEXT,               -- Model that produced this insight
  created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),

  CONSTRAINT ai_analysis_cache_unique UNIQUE (athlete_id, analysis_type, scope_key)
);
```

---

## Pydantic Models (Key Request Bodies)

### `WorkoutPayload`

Used for both `POST /workouts` and `POST /training-plans`.

```python
class WorkoutPayload(BaseModel):
    source: str
    external_id: Optional[str] = None
    sport: str
    title: Optional[str] = None
    started_at: Optional[datetime] = None
    ended_at: Optional[datetime] = None
    date: Optional[str] = None          # For training plans (planned_date)
    duration_minutes: Optional[int] = None
    distance_m: Optional[float] = None
    avg_hr: Optional[int] = None
    max_hr: Optional[int] = None
    avg_power_w: Optional[int] = None
    norm_power_w: Optional[int] = None
    avg_pace_sec_km: Optional[int] = None
    hr_zone_0_pct: Optional[float] = None
    # ... hr_zone_1_pct through hr_zone_5_pct
    tss: Optional[float] = None
    strain_score: Optional[float] = None
    projected_tss: Optional[int] = None  # For training plans
    primary_zone: Optional[str] = None
    description: Optional[str] = None
    structure: list[IntervalBlock] = []
    completed: bool = False
```

### `DailyBiometrics`

Used for `POST /biometrics/daily`.

```python
class DailyBiometrics(BaseModel):
    date: date
    source: str
    external_id: Optional[str] = None
    hrv_rmssd: Optional[float] = None
    resting_hr: Optional[int] = None
    sleep_duration_min: Optional[int] = None
    sleep_score: Optional[int] = None
    sleep_deep_pct: Optional[float] = None
    sleep_rem_pct: Optional[float] = None
    sleep_light_pct: Optional[float] = None
    sleep_awake_pct: Optional[float] = None
    sleep_bedtime: Optional[str] = None
    sleep_wakeup: Optional[str] = None
    skin_temp_deviation: Optional[float] = None
    spo2_pct: Optional[float] = None
    recovery_score: Optional[int] = None
    strain_score: Optional[float] = None
    is_nap: bool = False
```
