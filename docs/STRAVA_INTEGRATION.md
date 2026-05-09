# Strava Integration Plan — Astrape AI
> Full breakdown: OAuth, data ingestion, streams, deduplication, HR zones, and all new visualizations.

---

## Overview

Strava is the richest source of per-second training data you'll have. Unlike WHOOP (recovery/strain at daily granularity) and Garmin (webhook push of summary workouts), Strava gives you **streams** — dense, time-series arrays at 1-second resolution for heart rate, power, cadence, GPS, grade, velocity, and more. It also provides structured **laps**, **splits**, and **segment efforts**. This plan treats Strava as the primary source of *intra-workout* granularity, while WHOOP remains the primary source of *recovery* context.

---

## Part 1: OAuth 2.0 & App Registration

### 1.1 Register Your App

1. Go to `https://www.strava.com/settings/api`
2. Create application — use `AstrapeAI` as the name, `astrapeai.com` as the website
3. Set Authorization Callback Domain to your Cloud Run URL: `your-service.run.app`
4. Note your `Client ID` and `Client Secret`

### 1.2 Required Scopes

Request these scopes during authorization:

| Scope | What It Unlocks |
|-------|----------------|
| `read` | Athlete profile, public activities |
| `activity:read` | All activities (excluding private) |
| `activity:read_all` | Private activities too (recommended) |
| `profile:read_all` | Zones, weight, equipment |

### 1.3 OAuth Flow (mirrors your existing WHOOP pattern)

```
1. Mobile opens WebView → GET /strava/auth/connect
2. Backend redirects to:
   https://www.strava.com/oauth/authorize
     ?client_id=YOUR_CLIENT_ID
     &response_type=code
     &redirect_uri=https://your-api.run.app/v1/sync/strava/callback
     &scope=activity:read_all,profile:read_all
3. User approves → Strava redirects to callback with ?code=...
4. Backend exchanges code for access_token + refresh_token
5. Store encrypted in Supabase Vault (same pattern as WHOOP)
6. Trigger historical backfill (last 90 days)
```

### 1.4 Token Refresh

Strava access tokens expire after **6 hours**. Add a refresh handler to `services/strava.py`:

```python
# Refresh if expires_at < now + 300s buffer
async def get_valid_token(athlete_id: str) -> str:
    token = await get_stored_token(athlete_id)
    if token.expires_at < time.time() + 300:
        token = await refresh_strava_token(token.refresh_token)
        await store_token(athlete_id, token)
    return token.access_token
```

---

## Part 2: Webhook Subscription

Strava push subscriptions fire on activity create/update/delete — exactly like your Garmin webhook setup.

### 2.1 Subscribe

```bash
POST https://www.strava.com/api/v3/push_subscriptions
  client_id=YOUR_ID
  client_secret=YOUR_SECRET
  callback_url=https://your-api.run.app/v1/sync/strava/webhook
  verify_token=YOUR_VERIFY_TOKEN
```

Strava will do a `GET` to your callback with `hub.challenge` — your endpoint must echo it back. This is a one-time registration, not per-user.

### 2.2 Webhook Payload Shape

```json
{
  "aspect_type": "create",
  "event_time": 1549560669,
  "object_id": 1234567890,        // activity_id
  "object_type": "activity",
  "owner_id": 134815,             // athlete's Strava ID
  "subscription_id": 12345
}
```

The webhook only tells you *something happened*. You must then call the API to get the actual data.

### 2.3 New Route: `POST /v1/sync/strava/webhook`

```python
@router.post("/strava/webhook")
async def strava_webhook(payload: StravaWebhookEvent):
    if payload.aspect_type == "create" and payload.object_type == "activity":
        await ingest_strava_activity(payload.owner_id, payload.object_id)
    elif payload.aspect_type == "delete":
        await soft_delete_activity(source="strava", external_id=str(payload.object_id))
    return {"status": "ok"}
```

---

## Part 3: The Strava API Endpoints You Need

### 3.1 Activity Detail
```
GET /activities/{id}
```
Returns the full `DetailedActivity` object. **Store the entire raw JSON blob** in `source_ids` or a dedicated `raw_payload` JSONB column — don't filter fields at ingest time. You can always derive computed columns later; you can never recover data you didn't save. Key fields to index/surface:
- `average_heartrate`, `max_heartrate`
- `average_watts`, `max_watts`, `weighted_average_watts` (≈ Normalized Power)
- `kilojoules` (total work done)
- `average_cadence`
- `splits_metric` (per-500m for rowing, per-km for running) ← **secondary breakdown, fallback if no laps**
- `splits_standard` (per-mile splits, store for completeness)
- `laps` (auto-lapped every 500m by Garmin + Apple Watch) ← **primary for rowing interval analysis**
- `has_heartrate`, `device_watts` (flags to check before requesting streams)
- `suffer_score` (Strava's training load score — useful cross-check)
- `sport_type` (crucial for deduplication logic)
- `perceived_exertion`, `hide_from_home`, `gear_id`, `device_name`
- `segment_efforts[]` (store full array — useful for progress tracking later)

### 3.2 Activity Streams ← The Gold
```
GET /activities/{id}/streams?keys=time,heartrate,watts,cadence,velocity_smooth,altitude,distance,latlng,grade_smooth&key_by_type=true
```

All available stream types:

| Stream Key | Unit | Notes |
|---|---|---|
| `time` | seconds | Elapsed seconds from start. Master index. |
| `heartrate` | bpm | 1s resolution. Source of secondary HR. |
| `watts` | W | Power meter data (cycling). |
| `cadence` | rpm/spm | Cycling RPM or running SPM. |
| `velocity_smooth` | m/s | Smoothed speed. |
| `distance` | m | Cumulative distance from start. |
| `altitude` | m | GPS elevation. |
| `latlng` | [lat, lng] | GPS coordinates per second. |
| `grade_smooth` | % | Road gradient. |
| `temp` | °C | Ambient temperature (Garmin/Edge devices). |
| `moving` | bool | Whether athlete was moving at that second. |

> **Key insight**: When `key_by_type=true`, each stream type is its own object with a `data` array. All arrays share the same index, so `heartrate.data[42]` corresponds to `time.data[42]`. Gaps (paused recording) appear as jumps in the `time` array — handle these explicitly.

### 3.3 Laps
```
GET /activities/{id}/laps
```
Returns an array of lap objects. Each lap has:
- `lap_index`, `start_index`, `end_index` (maps to stream indices!)
- `elapsed_time`, `moving_time`, `distance`
- `average_speed`, `max_speed`
- `average_heartrate`, `max_heartrate`
- `average_watts`, `average_cadence`
- `total_elevation_gain`

For rowing: each piece/interval will typically be a separate lap.

### 3.4 Athlete Zones
```
GET /athlete/zones
```
Returns the athlete's configured HR and power zones from their Strava settings. Use these if set; otherwise calculate dynamically (see Part 5).

### 3.5 Segment Efforts (optional, Phase 2)
```
GET /activities/{id} → segments[] inside DetailedActivity
```
Strava segments are community-defined GPS routes. Useful for comparing performance on known routes over time — a good "progress" feature later.

---

## Part 4: Cross-Source Data Deduplication

This is the hardest part. A single rowing workout will arrive from:
- **Strava** (GPS + HR + power streams, triggered by webhook)
- **WHOOP** (strain/recovery context, possibly the same session)
- **Garmin** (summary workout via webhook push)
- **HealthKit** (workout summary from Apple Watch)

### 4.1 Canonical Workout Record

Create one canonical `workouts` record per real-world training session. All sources contribute to it — they don't each create their own.

**New `workouts` table fields needed:**

```sql
ALTER TABLE workouts ADD COLUMN strava_activity_id BIGINT UNIQUE;
ALTER TABLE workouts ADD COLUMN strava_streams_fetched BOOLEAN DEFAULT FALSE;
ALTER TABLE workouts ADD COLUMN primary_source TEXT; -- 'strava' | 'garmin' | 'whoop' | 'healthkit'
ALTER TABLE workouts ADD COLUMN source_ids JSONB DEFAULT '{}';
-- e.g. {"strava": "123456", "garmin": "garmin_push_123", "whoop": "abc-uuid"}
ALTER TABLE workouts ADD COLUMN raw_strava_payload JSONB; -- full DetailedActivity JSON, unfiltered

-- New table for raw stream data (separate from workouts due to size)
CREATE TABLE activity_streams (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  workout_id UUID REFERENCES workouts(id) ON DELETE CASCADE,
  athlete_id UUID REFERENCES athletes(id),
  time_series JSONB,      -- {time: [], heartrate: [], watts: [], ...}
  resolution_seconds INT DEFAULT 1,
  created_at TIMESTAMPTZ DEFAULT NOW()
);

-- New table for lap data
CREATE TABLE activity_laps (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  workout_id UUID REFERENCES workouts(id) ON DELETE CASCADE,
  lap_index INT,
  start_index INT,
  end_index INT,
  elapsed_time INT,
  moving_time INT,
  distance FLOAT,
  average_heartrate FLOAT,
  max_heartrate FLOAT,
  average_watts FLOAT,
  average_cadence FLOAT,
  average_speed FLOAT,
  total_elevation_gain FLOAT,
  lap_data JSONB  -- full raw lap object
);
```

### 4.2 Deduplication Algorithm

The challenge: timestamps won't match perfectly across sources (Garmin records start when you press Go; WHOOP records from skin contact detection; Strava gets the file upload timestamp).

**Rule: match within a ±10 minute window by sport type**

```python
DEDUP_WINDOW_SECONDS = 600  # 10 minutes

async def find_or_create_canonical_workout(
    athlete_id: str,
    source: str,
    sport_type: str,
    start_time: datetime,
    duration_seconds: int
) -> Workout:
    
    # Search for existing workout within window
    existing = await db.query("""
        SELECT * FROM workouts
        WHERE athlete_id = $1
          AND sport_category = $2
          AND ABS(EXTRACT(EPOCH FROM (start_time - $3))) < $4
          AND ABS(elapsed_time - $5) < $5 * 0.2  -- within 20% of duration
        LIMIT 1
    """, athlete_id, normalize_sport(sport_type), start_time, 
        DEDUP_WINDOW_SECONDS, duration_seconds)
    
    if existing:
        # Merge: update source_ids, elevate primary_source by priority
        return await merge_into_existing(existing, source, ...)
    else:
        return await create_new_workout(source, ...)
```

**Source Priority Hierarchy** (which source "wins" for each field):

| Field | Winner | Why |
|---|---|---|
| `elapsed_time`, `distance` | Strava > Garmin > HealthKit | GPS accuracy |
| `average_heartrate` | Strava streams > Garmin > WHOOP | See note below |
| `average_watts` | Strava (device_watts) > Garmin | Direct meter data |
| `strain`, `recovery` | WHOOP only | Proprietary algo |
| `hrv_4t` | WHOOP only | Proprietary algo |
| `tss` | Calculated from best source | See algorithms.py |
| `gps_polyline` | Strava > Garmin (pending API) | WHOOP has no GPS |
| `laps` | Strava > Garmin (pending API) | Garmin + Apple Watch auto-lap every 500m for rowing |
| `splits` | Strava `splits_metric` | Secondary/fallback — per-500m if no laps present |

> **HR source priority rationale**: For *during-activity* HR, Strava > Garmin > WHOOP. The device recording the Strava activity (Garmin watch, Wahoo, etc.) is typically a chest strap or wrist optical — both are optimized for exercise capture and validated against each other at point of recording. WHOOP's optical sensor on wrist or bicep is excellent for resting/recovery HR and HRV but isn't the primary recording device during a structured workout — it's capturing incidentally. Garmin chest straps (HRM-Pro, HRM-Dual) are ECG-accurate and the gold standard for activity HR, but since Strava gets the same data file from the Garmin device, Strava streams *are* the Garmin data — just delivered via a different pipe.
>
> **When Garmin API access arrives**: Garmin's webhook push includes GPS, splits, data directly. Once integrated, the priority will be: Strava streams (if available) = Garmin direct (same source device, different pipe) > WHOOP. Use whichever arrived first and flag as duplicate.

### 4.3 Stream Alignment When Times Don't Match

When you have HR from WHOOP (daily summary) and per-second HR from Strava streams for the same workout:

1. **Prefer Strava streams** for the workout detail view — they're 1s resolution
2. **Use WHOOP aggregate HR** as a validation crosscheck: if `WHOOP.avg_hr` and `mean(strava_hr_stream)` differ by >10 bpm, flag it and prefer WHOOP (WHOOP optical HR is often more accurate for non-exercise capture)
3. **For TSS calculation**: use Strava's `weighted_average_watts` if `device_watts=true`; otherwise fall back to pace-HR model

### 4.4 Sport Type Normalization Map

```python
SPORT_CANONICAL = {
    # Rowing
    "Rowing": "rowing",
    "VirtualRow": "rowing",
    "rowing": "rowing",
    # Running
    "Run": "run", "TrailRun": "run", "VirtualRun": "run",
    # Cycling
    "Ride": "cycling", "VirtualRide": "cycling", "EBikeRide": "cycling",
    # Strength
    "WeightTraining": "strength", "Workout": "strength",
    # Cross-training
    "Crossfit": "crossfit", "Elliptical": "cross_trainer",
}
```

---

## Part 5: HR Zone Calculation from Raw Data

### 5.1 Zone Definitions

Store per-athlete zone anchors in the `athletes` table:

```sql
ALTER TABLE athletes ADD COLUMN max_hr INT;           -- from test or estimate
ALTER TABLE athletes ADD COLUMN lactate_threshold_hr INT; -- LTHR
ALTER TABLE athletes ADD COLUMN resting_hr INT;       -- from WHOOP/HealthKit
ALTER TABLE athletes ADD COLUMN hr_zone_method TEXT DEFAULT 'max_hr_percent';
-- options: 'max_hr_percent' | 'lthr' | 'hrr' (heart rate reserve)
```

### 5.2 Three Zone Models — Implement All Three

**Model A: % Max HR (default)**
```python
def zones_from_max_hr(max_hr: int) -> dict:
    return {
        "Z1": (0,          round(max_hr * 0.60)),   # Recovery
        "Z2": (round(max_hr * 0.60), round(max_hr * 0.70)),  # Aerobic base
        "Z3": (round(max_hr * 0.70), round(max_hr * 0.80)),  # Tempo
        "Z4": (round(max_hr * 0.80), round(max_hr * 0.90)),  # Threshold
        "Z5": (round(max_hr * 0.90), max_hr + 20),           # VO2max / Anaerobic
    }
```

**Model B: % LTHR — Coggan 5-Zone (the model you're using)**
```python
def _lthr_zones(lthr: int) -> list[HRZone]:
    """Coggan-style 5-zone model anchored to lactate threshold HR (Z5 merges VO2max + anaerobic)."""
    return [
        HRZone(1, "Active Recovery", 0,              int(lthr * 0.81)),
        HRZone(2, "Endurance",       int(lthr * 0.81), int(lthr * 0.89)),
        HRZone(3, "Tempo",           int(lthr * 0.89), int(lthr * 0.93)),
        HRZone(4, "Threshold",       int(lthr * 0.93), int(lthr * 1.05)),
        HRZone(5, "VO2max+",         int(lthr * 1.05), 999),
    ]
```

**Model C: Heart Rate Reserve (Karvonen) — best for general athletes**
```python
def zones_from_hrr(max_hr: int, resting_hr: int) -> dict:
    hrr = max_hr - resting_hr
    return {
        "Z1": (0, resting_hr + round(hrr * 0.60)),
        "Z2": (resting_hr + round(hrr * 0.60), resting_hr + round(hrr * 0.70)),
        "Z3": (resting_hr + round(hrr * 0.70), resting_hr + round(hrr * 0.80)),
        "Z4": (resting_hr + round(hrr * 0.80), resting_hr + round(hrr * 0.90)),
        "Z5": (resting_hr + round(hrr * 0.90), max_hr + 20),
    }
```

### 5.3 Estimating Max HR (when not set)

```python
def estimate_max_hr(age: int, sex: str) -> int:
    # Tanaka formula (more accurate for trained athletes than 220-age)
    base = 208 - (0.7 * age)
    # Fox formula for comparison: 220 - age
    return round(base)
```

### 5.4 Computing Zone Distribution from a Stream

```python
def compute_zone_distribution(hr_stream: list[int], zones: dict) -> dict:
    total = len(hr_stream)
    dist = {zone: 0 for zone in zones}
    for hr in hr_stream:
        for zone, (low, high) in zones.items():
            if low <= hr < high:
                dist[zone] += 1
                break
    return {zone: round(count / total * 100, 1) for zone, count in dist.items()}
```

### 5.5 Estimating LTHR from Workout Data (auto-detect)

If no LTHR is set, estimate it from a hard effort: the average HR of the final 20 minutes of a threshold workout approximates LTHR. Add a flag to the UI: *"We estimated your LTHR from your recent [workout name]. Tap to confirm or adjust."*

---

## Part 6: New Backend Endpoints

### New Routes to Add to `routers/workouts.py` or new `routers/strava.py`:

```
GET  /activities/{workout_id}/streams        → full time-series streams
GET  /activities/{workout_id}/laps           → lap breakdown
GET  /activities/{workout_id}/zones          → hr zone distribution for this workout
GET  /activities/{workout_id}/splits         → per-km/per-500m splits
POST /v1/sync/strava/webhook                 → webhook receiver (existing pattern)
GET  /v1/sync/strava/auth/connect            → OAuth start
GET  /v1/sync/strava/callback                → OAuth callback
POST /v1/sync/strava/backfill                → historical import
GET  /athlete/zones                          → calculated HR + power zones
PUT  /athlete/zones                          → manually set anchors (max_hr, lthr, etc.)
```

---

## Part 7: New Visualizations

All charts use your existing LayerChart / D3 SVG stack on the frontend. Here's every chart to build, grouped by screen.

---

### 7.1 Workout Detail Screen (new screen or expanded existing)

**A. Secondary HR Chart**
- Y-axis: BPM | X-axis: elapsed time (seconds → mm:ss)
- Color zones: render the line in zone color (Z1=blue, Z2=green, Z3=yellow, Z4=orange, Z5=red)
- Overlay: show lap markers as vertical dashed lines
- Tooltip: show exact HR + zone + elapsed time on hover

**B. Power Curve (watts over time)**
- Y-axis: watts | X-axis: elapsed time
- Secondary Y-axis: 30s rolling average watts (bolder line)
- Dashed line: FTP reference
- Fill: gradient from base to peaks

**C. Cadence Stream**
- Y-axis: rpm or spm | X-axis: elapsed time
- Simple line, zone-agnostic
- Useful for rowing: shows catch rate patterns

**D. Velocity / Pace Stream**
- Y-axis: m/s converted to pace (min/km for run, min/500m for row, mph for bike)
- X-axis: elapsed time
- Invert axis optionally for pace (lower = faster)

**E. Elevation Profile (outdoor activities)**
- Area chart below, fill with terrain texture
- GPS route rendered as polyline map (Mapbox/Leaflet tile overlay in WebView)

**F. HR Zone Distribution Donut**
- 5-segment donut showing % time in each zone
- Color coded: Z1=steel blue, Z2=teal, Z3=yellow-green, Z4=amber, Z5=coral red (Astrape palette!)
- Center: dominant zone label

**G. Grade vs Pace Scatter (running/cycling)**
- X-axis: grade % | Y-axis: pace
- Scatter plot of every second in the workout
- Reveals true effort-vs-terrain relationship

---

### 7.2 Laps / Splits Breakdown Panel

**A. Lap Strip Chart**
- Horizontal bar for each lap, width = duration
- Color fill = average HR zone for that lap
- Below each bar: lap number, distance, avg HR, avg watts

**B. Splits Table + Bar Comparison**
- Table: per-500m splits (rowing) or per-km splits (running)
- Alongside: micro bar chart for pace, HR, watts per split
- Color: red/green delta from average pace
- Perfect for rowing — shows how well you held power and rating across pieces

**C. Lap-over-Lap Overlay Line Chart**
- Each lap rendered as its own HR or power line
- All laps share same X-axis (0 → lap duration)
- Different color/opacity per lap
- Shows pacing strategy — did you positive/negative split?

---

### 7.3 Zones Screen (new or expanded)

**A. Zone Distribution: This Workout vs. 30-Day Average**
- Grouped bar chart: 2 bars per zone
- Shows how today's workout compared to your recent training distribution

**B. Zone Time Trend (30-day rolling)**
- Stacked area chart, one band per zone
- X-axis: date | Y-axis: minutes in each zone
- Reveals if training is shifting aerobic vs. anaerobic over time

**C. Zone Anchors Config UI**
- Input fields: Max HR, LTHR, Resting HR
- Zone preview: live-updating zone ranges as user adjusts anchors
- Toggle: select zone method (% Max HR / LTHR / Karvonen HRR)

---

### 7.4 Dashboard Additions

**A. Recent Power Trend (if cycling/rowing)**
- 7-day sparkline of average watts or normalized watts
- Simple, compact — fits in existing dashboard grid

**B. Training Load by Source Badge**
- Small icons showing which sources contributed data this week (Strava ✓, WHOOP ✓, Garmin ✓)
- Useful for user trust / debugging

---

### 7.5 Athlete Progress Screen (new — Phase 2)

**A. Best Efforts Chart**
- X-axis: effort duration (1min, 5min, 20min, 60min)
- Y-axis: best average power (watts) or best average HR for that duration
- Plots a power curve — the canonical fitness fingerprint
- Compare across date ranges

**B. Segment History (Strava segments)**
- Repeat efforts on known routes
- Timeline of your time on each segment
- Shows improvement over season

---

## Part 8: New `services/strava.py` Structure

```
services/
  strava.py
    ├── StravaOAuth          - token exchange, refresh, storage
    ├── StravaWebhook        - signature validation, event routing  
    ├── StravaActivityFetcher
    │   ├── get_activity_detail(activity_id)
    │   ├── get_activity_streams(activity_id, keys=[...])
    │   ├── get_activity_laps(activity_id)
    │   └── get_athlete_zones(athlete_id)
    ├── StravaIngestionPipeline
    │   ├── ingest_activity(owner_strava_id, activity_id)
    │   │   ├── 1. fetch detail + streams + laps
    │   │   ├── 2. find_or_create_canonical_workout (dedup)
    │   │   ├── 3. store streams to activity_streams table
    │   │   ├── 4. store laps to activity_laps table
    │   │   ├── 5. compute TSS + zone distribution
    │   │   └── 6. update CTL/ATL
    │   └── backfill_historical(athlete_id, days=90)
    └── StravaZoneCalculator
        ├── calculate_zones(athlete)
        └── compute_distribution(hr_stream, zones)
```

---

## Part 9: Implementation Phases

### Phase 1 — Foundation (1–2 weeks)
- [ ] Register Strava app, get credentials
- [ ] Add `STRAVA_CLIENT_ID`, `STRAVA_CLIENT_SECRET` to `.env` and Cloud Run secrets
- [ ] Add `strava_activity_id`, `source_ids`, `primary_source` columns to `workouts`
- [ ] Create `activity_streams` and `activity_laps` tables (migrations)
- [ ] Add `max_hr`, `resting_hr`, `lthr`, `hr_zone_method` to `athletes`
- [ ] Build `services/strava.py` — OAuth + token refresh
- [ ] Build `POST /v1/sync/strava/webhook` + `GET /v1/sync/strava/callback`
- [ ] Connect OAuth flow from mobile Settings screen
- [ ] Verify webhook fires and activity ingests end-to-end

### Phase 2 — Streams & Dedup (1–2 weeks)
- [ ] Implement `find_or_create_canonical_workout` deduplication logic
- [ ] Store streams to `activity_streams` (JSONB, compressed)
- [ ] Store laps to `activity_laps`
- [ ] Implement all three HR zone calculation models
- [ ] Add `GET /activities/{id}/streams` endpoint
- [ ] Add `GET /activities/{id}/laps` endpoint
- [ ] Add `GET /athlete/zones` + `PUT /athlete/zones` endpoints
- [ ] 90-day backfill after OAuth connect

### Phase 3 — Visualizations (2 weeks)
- [ ] Workout Detail screen with HR stream chart (with zone coloring)
- [ ] Power / watts stream chart
- [ ] Lap strip chart + splits table
- [ ] HR Zone Distribution donut
- [ ] Zone anchors config UI
- [ ] Velocity/cadence charts

### Phase 4 — Advanced (Phase 2 of product)
- [ ] Lap-over-Lap overlay chart
- [ ] Best Efforts / Power Curve chart
- [ ] Zone trend (30-day stacked area)
- [ ] Segment history
- [ ] LTHR auto-detection from workout streams
- [ ] Grade vs Pace scatter (outdoor)

---

## Part 10: Key Gotchas & Edge Cases

1. **Strava rate limits**: 100 req/15min, 1000 req/day. For historical backfill, batch requests with a 0.5s delay. Do NOT fetch streams for every activity during backfill — only fetch summaries first, then hydrate streams lazily when the user opens a specific workout.

2. **`device_watts` flag**: Only fetch/display power charts if `device_watts: true`. If false, Strava estimated watts — still useful but mark as "estimated" in the UI.

3. **Stream gaps**: The `time` stream can have jumps (auto-pause). Before rendering, interpolate or mask the gaps. A jump of >30s in the time array = paused segment.

4. **Rowing on Strava**: Sport type is `Rowing` (outdoor) or check for `VirtualRow`. On-water rowing won't have `watts` streams unless you use a Concept2 with PM5. Indoor Concept2 *will* have watts if uploaded via the Concept2 logbook → Strava connection.

5. **WHOOP + Strava same workout**: WHOOP will fire its webhook first (faster). Strava fires after the user ends the activity and the app syncs. Build the dedup to handle arriving in either order — idempotent upserts.

6. **Strava `suffer_score`**: This is their proprietary training load score. Map it alongside your TSS as a "Strava Load" field — useful for athletes who think in Strava terms.

7. **Secondary HR**: Strava HR stream comes from whatever device recorded the activity (Watch, Garmin, Wahoo). For rowing: typically Garmin HR strap via Garmin device → uploaded to Strava. This is the same HR as Garmin webhook data — deduplicate at the `average_heartrate` field level, prefer whichever has stream data.

8. **Laps vs Splits (Rowing)**: Both Garmin rowing sport profiles and Apple Watch rowing workouts **auto-lap every 500m by default** — so `laps` in Strava for a rowing activity will almost always be device-generated 500m segments with full per-lap HR, pace, watts, and cadence. This is better than `splits_metric` for rowing because Strava's `splits_metric` is per-kilometer for all activities regardless of sport. A 4×2000m session gives you 16 laps at 500m from the device vs. 8 one-km splits from Strava — laps are far more analytically useful for intervals.

   **Strategy: laps as primary, stream-derived as fallback, splits_metric always stored.**

   ```python
   async def get_rowing_intervals(workout_id, activity, streams):
       laps = activity.laps or []

       # Check if laps look like auto-500m intervals
       valid_500m_laps = [
           l for l in laps
           if 450 <= l.distance <= 550  # 500m ± 10% tolerance
       ]

       if len(valid_500m_laps) >= len(laps) * 0.8:
           # 80%+ of laps are ~500m → device auto-lapped reliably
           primary = "laps"
           intervals = valid_500m_laps
       else:
           # Fallback: derive 500m splits from distance stream directly
           # Slices time/HR/watts/cadence arrays at every 500m mark
           primary = "stream_derived"
           intervals = compute_500m_splits_from_streams(streams)

       # Always store splits_metric too (per-km, useful for longer pieces)
       return {
           "primary": primary,
           "intervals": intervals,
           "splits_metric": activity.splits_metric,
       }
   ```

   The stream-derived fallback slices the `distance`/`time`/`heartrate`/`watts` arrays at every 500m mark — bulletproof for edge cases like manual recordings, phone-only Strava sessions, or Concept2 ErgData uploads with no auto-lap config.

   **Store all three in the DB**: raw `laps` JSONB, raw `splits_metric` JSONB, and a computed `intervals` JSONB column using the priority logic above. The UI always reads from `intervals` — sourcing logic stays entirely in the backend.

---

## Summary

| Capability | Source | Priority |
|---|---|---|
| OAuth + Webhook | Strava | Phase 1 |
| Activity deduplication | Cross-source logic | Phase 1 |
| HR streams (1s resolution) | Strava | Phase 2 |
| Watts / power streams | Strava | Phase 2 |
| Lap breakdown | Strava | Phase 2 |
| Splits per 500m/km | Strava | Phase 2 |
| HR Zone calculation | Server (from any HR source) | Phase 2 |
| Secondary HR chart | Frontend | Phase 3 |
| Power chart | Frontend | Phase 3 |
| Zone distribution donut | Frontend | Phase 3 |
| Lap strip + overlay | Frontend | Phase 3 |
| Best Efforts / Power Curve | Frontend | Phase 4 |
| LTHR auto-detect | Server | Phase 4 |