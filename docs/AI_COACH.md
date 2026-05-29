# AI Coach System

## Overview

The ASTRAPHE coach is implemented in `backend/app/services/ai_coach.py`, `backend/app/services/coach_tools.py`, `backend/app/services/memory.py`, and `backend/app/routers/coach.py`.

It uses the current `google-genai` SDK, prompt-file instructions, structured athlete context, tool calls, Google Search grounding, image/document inputs, and pgvector-backed long-term memory.

## Model Configuration

Defaults are loaded from `backend/app/config.py`:

| Setting | Default | Purpose |
|---|---|---|
| `GEMINI_MODEL` | `gemma-4-26b-a4b-it` | Main coach chat model |
| `GEMINI_ANALYSIS_MODEL` | `gemini-flash-lite-latest` | Screen-level analysis model |
| `GEMINI_EMBEDDING_MODEL` | `gemini-embedding-001` | Coach memory embeddings |

Per-user overrides for coach/analysis models live in `auth.users.app_metadata` as `gemini_model` and `gemini_analysis_model`. The backend intentionally ignores user-editable metadata for model, tier, admin, and rate-limit decisions.

## Prompt Source

The coach instructions are read from:

```text
backend/app/prompts/coach_behavior.md
```

If that file is missing, the service falls back to a minimal "elite, data-driven performance coach" instruction.

The prompt expects the model to produce an internal scratchpad and an athlete-facing response. The backend extracts only the athlete-facing text.

```xml
<scratchpad>
Internal reasoning and tool planning.
</scratchpad>
<response>
Text delivered to the athlete.
</response>
```

If tags are malformed or missing, the backend strips `<scratchpad>` blocks and returns the remaining text.

## Coach Endpoints

- `POST /v1/coach/message`: complete JSON response.
- `POST /v1/coach/stream`: Server-Sent Events streaming response.
- `POST /v1/coach/initialize`: warm coach context.
- `GET /v1/coach/conversations`: list threads.
- `POST /v1/coach/conversations`: create thread.
- `GET /v1/coach/conversations/{id}/messages`: read messages.
- `DELETE /v1/coach/conversations/{id}`: delete thread.
- `POST /v1/coach/upload-document`: upload a document attachment.

The current mobile app calls `POST /v1/coach/message` for normal chat and uses plain `fetch`.

## Context Assembly

Before inference, the service builds a compact context from current athlete data:

- Profile: name, gender, units, timezone offset, HR/FTP/pace anchors.
- Biometrics: latest HRV, resting HR, sleep, recovery, readiness, strain, SpO2, skin temperature, and 7-day averages.
- Training load: latest `tss_history` row with CTL, ATL, TSB, and daily TSS.
- Conversation history: recent `coach_messages` in the active conversation.
- Memories: relevant `coach_memories` from pgvector similarity search.
- Attachments: uploaded document/image URLs when supplied.

Context parts are cached in process for five minutes per athlete and invalidated after relevant sync/processing paths.

## Tools

The coach exposes custom Python tools through Gemini function declarations:

| Tool | Purpose |
|---|---|
| `simulate_training_impact` | Project CTL, ATL, and TSB after a hypothetical TSS load. |
| `schedule_workout` | Create a structured planned workout in `training_plans`. |
| `calculate_nutrition` | Estimate kJ, carb, fluid, and sodium targets for a planned effort. |
| `clear_training_plans` | Delete planned workouts in a date range before replacing a week. |
| `list_workouts` | List completed activities by athlete-local date range or sport. |
| `get_workout_summary` | Fetch TSS, zones, duration, and load metrics for one workout. |
| `get_workout_streams_window` | Downsampled HR/power/pace for a specific time segment. |
| `log_workout` | Record a completed session the athlete reports in chat. |
| `update_workout` | Correct duration, power, or date on an existing workout. |
| `log_biometrics` | Save manual sleep, HRV, resting HR, or weight. |
| `get_athlete_zones` | HR zone boundaries plus FTP/threshold anchors. |
| `update_planned_workout` | Reschedule or edit one future planned workout. |
| `delete_planned_workout` | Remove one future planned workout. |
| `save_memory` | Persist an important athlete fact to `coach_memories`. |
| `internal_scratchpad` | Sink private model reasoning so it is never shown to the athlete. |

The tool list also enables Google Search grounding through `types.Tool(google_search=types.GoogleSearch())`.

## Memory Pipeline

Long-term memory is stored in `coach_memories`:

- `athlete_id`
- `content`
- `memory_type`
- `context_date`
- `metadata`
- `embedding vector(3072)`
- timestamps

The service embeds user queries and important facts with `GEMINI_EMBEDDING_MODEL`, retrieves the most relevant memories through the `match_coach_memories` RPC, and stores new memories after replies or explicit `save_memory` tool calls.

## Message Persistence

Conversation state is stored in:

- `coach_conversations`
- `coach_messages`

Messages can include `image_urls`. The frontend currently uploads coach images to the `coach-uploads` Supabase Storage bucket and passes the resulting URLs to `/v1/coach/message`.

## Rate Limits And Access

AI rate limits are enforced per athlete with Redis-backed sliding windows when Redis is available:

| Tier | Requests/min | Requests/hour |
|---|---:|---:|
| `free` | 5 | 20 |
| `trial` | 15 | 75 |
| `premium` | 40 | 200 |

`rate_limit_rpm` and `rate_limit_rph` in `auth.users.app_metadata` override those defaults.

Tier gating also uses `auth.users.app_metadata.tier`. The `athletes.tier` column exists for profile/admin workflows and defaults, but the backend authorization source of truth is app metadata.

## Screen-Level Analysis

Short analysis strings are implemented separately in `backend/app/routers/analysis.py` and `backend/app/services/analysis_cache.py`.

Routes include recovery, sleep, strain, training load, dashboard summary, workout, and time-in-zones analysis. Results are cached in `athlete_analyses` using a context fingerprint to avoid repeated model calls when data has not changed.

Free/trial users receive deterministic fallback summaries where the route supports it; premium users can receive Gemini analysis results with the configured analysis model.

## Operational Notes

- Synchronous SDK calls are run off the FastAPI event loop.
- The backend stores only the athlete-facing response in normal chat output.
- AI-generated training plan rows are normalized/sanitized before insertion.
- Garmin device push from generated workouts is currently stubbed in the tool response.
- Google Search grounding sources may be returned alongside replies.
