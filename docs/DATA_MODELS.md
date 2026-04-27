# Data Models

## Database: Supabase PostgreSQL

All tables enforce Row Level Security. The policy pattern is uniform: `athlete_id = auth.uid()`. No cross-athlete data access is possible at the database layer regardless of what the API layer requests.

---

## Schema

### `athletes`

The root entity. One row per registered user.

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
  
  CONSTRAINT athletes_user_id_unique UNIQUE (user_id)
);

ALTER TABLE athletes ENABLE ROW LEVEL SECURITY;
CREATE POLICY "athletes_self_access" ON athletes
  FOR ALL USING (user_id = auth.uid());
```

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
  
  -- Computed load
  tss             NUMERIC(6,2),       -- Training Stress Score
  if_value        NUMERIC(4,3),       -- Intensity Factor (NP / FTP)
  
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
  
  -- Computed
  recovery_score       SMALLINT,      -- 0–100 ASTRAPE composite score
  
  CONSTRAINT biometrics_athlete_date_unique UNIQUE (athlete_id, date)
);

CREATE INDEX biometrics_athlete_date ON biometrics (athlete_id, date DESC);

ALTER TABLE biometrics ENABLE ROW LEVEL SECURITY;
CREATE POLICY "biometrics_athlete_access" ON biometrics
  FOR ALL USING (
    athlete_id IN (SELECT id FROM athletes WHERE user_id = auth.uid())
  );
```

### `tss_history`

A materialized daily TSS ledger. This is the source of truth for all CTL/ATL calculations. It is separate from `workouts` because (a) a single day may have multiple workouts, and (b) rest days must be explicitly represented as TSS=0 to correctly decay the exponential moving averages.

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

### `training_plans`

Structured training blocks. Each row is one planned workout session.

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

### `coach_memories`

Long-term memory store for the ASTRAPE AI agent. Each row is a semantically meaningful chunk of coaching history, stored alongside its vector embedding for similarity search.

```sql
CREATE EXTENSION IF NOT EXISTS vector;

CREATE TABLE coach_memories (
  id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  athlete_id      UUID NOT NULL REFERENCES athletes(id) ON DELETE CASCADE,
  
  -- Content
  memory_type     TEXT NOT NULL CHECK (memory_type IN (
                    'coaching_insight',   -- key advice given
                    'athlete_preference', -- stated preferences
                    'performance_note',   -- observed patterns
                    'goal'                -- stated goals
                  )),
  content         TEXT NOT NULL,
  
  -- Context snapshot at time of memory creation
  context_ctl     NUMERIC(6,2),
  context_tsb     NUMERIC(7,2),
  context_date    DATE,
  
  -- Vector embedding (text-embedding-004, 768 dimensions)
  embedding       vector(768),
  
  created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX coach_memories_embedding_idx ON coach_memories
  USING hnsw (embedding vector_cosine_ops)
  WITH (m = 16, ef_construction = 64);

ALTER TABLE coach_memories ENABLE ROW LEVEL SECURITY;
CREATE POLICY "coach_memories_athlete_access" ON coach_memories
  FOR ALL USING (
    athlete_id IN (SELECT id FROM athletes WHERE user_id = auth.uid())
  );
```

---

## Pydantic API Models

These are the Python-layer types used by FastAPI for request validation and response serialization.

```python
# models/athlete.py
from pydantic import BaseModel
from datetime import date
from typing import Optional

class AthleteState(BaseModel):
    """Current computed state for an athlete. Returned by GET /athlete/state"""
    athlete_id: str
    display_name: str
    date: date
    
    # Load metrics
    ctl: float          # Fitness
    atl: float          # Fatigue
    tsb: float          # Form
    
    # Today's biometrics
    hrv_rmssd: Optional[float]
    hrv_delta_7d: Optional[float]   # Change vs 7d average
    resting_hr: Optional[int]
    sleep_hours: Optional[float]
    sleep_score: Optional[int]
    recovery_score: Optional[int]
    
    # Computed readiness
    readiness_score: int            # 0–100
    readiness_label: str            # "Optimal" | "Good" | "Moderate" | "Fatigued"
    readiness_recommendation: str   # One-sentence coaching note


class WorkoutIngestion(BaseModel):
    """Payload for POST /workouts"""
    source: str
    external_id: Optional[str]
    sport: str
    started_at: str             # ISO 8601
    ended_at: str
    distance_m: Optional[float]
    avg_hr: Optional[int]
    max_hr: Optional[int]
    avg_power_w: Optional[int]
    norm_power_w: Optional[int]
    avg_pace_sec_km: Optional[int]
    fit_file_b64: Optional[str]     # Base64-encoded .fit file


class CoachMessage(BaseModel):
    """Payload for POST /coach/message"""
    conversation_id: Optional[str]
    message: str
    context_override: Optional[dict]    # For testing with custom athlete state
```

---

## Training Zones Schema

Training zones are stored per-athlete, per-sport as a JSONB column on the `athletes` table.

```json
{
  "run": {
    "anchor": "max_hr",
    "anchor_value": 185,
    "zones": [
      { "number": 1, "name": "Recovery",   "lo_pct": 62, "hi_pct": 70 },
      { "number": 2, "name": "Aerobic",    "lo_pct": 70, "hi_pct": 80 },
      { "number": 3, "name": "Tempo",      "lo_pct": 80, "hi_pct": 87 },
      { "number": 4, "name": "Threshold",  "lo_pct": 87, "hi_pct": 93 },
      { "number": 5, "name": "VO2max",     "lo_pct": 93, "hi_pct": 100 }
    ]
  },
  "bike": {
    "anchor": "ftp",
    "anchor_value": 280,
    "zones": [
      { "number": 1, "name": "Active Recovery", "lo_pct": 0,  "hi_pct": 55 },
      { "number": 2, "name": "Endurance",        "lo_pct": 56, "hi_pct": 75 },
      { "number": 3, "name": "Tempo",            "lo_pct": 76, "hi_pct": 90 },
      { "number": 4, "name": "Lactate",          "lo_pct": 91, "hi_pct": 105 },
      { "number": 5, "name": "VO2max",           "lo_pct": 106,"hi_pct": 120 }
    ]
  }
}
```


