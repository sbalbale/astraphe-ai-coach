# AI Coach System

## Overview

The ASTRAPHE coach is implemented in `backend/app/services/ai_coach.py`, `backend/app/services/coach_tools.py`, `backend/app/services/memory.py`, `backend/app/services/plan_import.py`, `backend/app/services/llm_provider.py`, and `backend/app/routers/coach.py`.

It uses the `google-genai` SDK, prompt-file instructions, structured athlete context, tool calls, web search, image/document inputs, and pgvector-backed long-term memory. The coach is open to `premium` and active `trial` accounts (`tiers.has_premium_access`).

## Model Configuration

Defaults are loaded from `backend/app/config.py`:

| Setting | Default | Purpose |
|---|---|---|
| `GEMINI_MODEL` | `gemini-3.5-flash-lite` | Main coach chat model |
| `GEMINI_FALLBACK_MODEL` | `gemini-3.1-flash-lite` | Takes over when the chat model fails, is overloaded or times out |
| `GEMINI_ANALYSIS_MODEL` | `gemini-3.1-flash-lite` | Screen-level analysis model |
| `GEMINI_EMBEDDING_MODEL` | `gemini-embedding-2` | Coach memory embeddings (always Gemini) |
| `GEMINI_IMPORT_MODELS` | `gemini-3-flash-preview,gemini-3.8-flash,gemini-3.6-flash` | Plan import models, tried in order (then `GEMINI_MODEL`) |
| `GEMINI_REQUEST_TIMEOUT_SEC` | `45` | Per-request timeout before failing over |
| `GEMINI_FREE_TIER` | `true` | Enables the proactive RPM guardrail and the free-tier search rules |
| `LLM_PROVIDER` | `gemini` | `openai` sends chat, analysis and memory extraction to an OpenAI-compatible endpoint (`OPENAI_API_BASE_URL`, `OPENAI_API_KEY`) |
| `CHAT_LLM_PROVIDER` / `CHAT_MODEL` | unset | `openai` plus a model id runs only the coach chat on the OpenAI-compatible endpoint (e.g. self-hosted); `GEMINI_FALLBACK_MODEL` still covers failures |
| `CHAT_REQUEST_TIMEOUT_SEC` / `CHAT_TURN_DEADLINE_SEC` | `120` / `240` | Per-request and whole-turn budgets for `CHAT_MODEL`; past the deadline the turn finishes on the fallback model |

Per-user overrides for coach/analysis models live in `auth.users.app_metadata` as `gemini_model` and `gemini_analysis_model` (`dependencies.get_user_config`). The backend never reads user-editable `user_metadata` for model, tier, admin, or rate-limit decisions.

## Prompt Source

The coach instructions are read from:

```text
backend/app/prompts/coach_behavior.md
```

If that file is missing, the service falls back to a minimal "elite, data-driven performance coach" instruction.

The prompt tells the model to put private reasoning in the `internal_scratchpad` tool and wrap the athlete-facing reply in `<response>...</response>`. Only the last `<response>` block reaches the athlete. Without one, the backend strips `<scratchpad>` / `<think>` blocks and other reasoning scaffolding; text that is still only reasoning counts as a failed reply so the turn can ask again.

## Coach Endpoints

- `POST /v1/coach/message`: complete JSON response.
- `POST /v1/coach/message/async`: saves the user message and returns `status: "pending"`; the reply lands in `coach_messages` (with a push notification) when ready.
- `POST /v1/coach/stream`: Server-Sent Events streaming response.
- `POST /v1/coach/initialize`: warm coach context / opening message.
- `GET /v1/coach/conversations`: list threads.
- `POST /v1/coach/conversations`: create thread.
- `POST /v1/coach/conversations/{id}/read`: mark a thread read.
- `GET /v1/coach/conversations/{id}/messages`: read messages.
- `GET /v1/coach/conversations/{id}/progress`: progress steps of the reply being generated.
- `DELETE /v1/coach/conversations/{id}`: delete thread.
- `GET /v1/coach/memories`, `PATCH /v1/coach/memories/{id}`, `DELETE /v1/coach/memories/{id}`: view and edit long-term memories.
- `POST /v1/coach/upload-document`: upload a document attachment.

The mobile chat screen sends with `POST /v1/coach/message/async` and polls the messages and progress endpoints.

## Context Assembly

Before inference, the service builds a compact context from current athlete data:

- Profile: name, gender, units, timezone offset, HR/FTP/pace anchors.
- Biometrics: latest HRV, resting HR, sleep, recovery, readiness, strain, SpO2, skin temperature, and 7-day averages.
- Training load: latest `tss_history` row with CTL, ATL, TSB, and daily TSS.
- Conversation history: recent `coach_messages` in the active conversation.
- Memories: relevant `coach_memories` from pgvector similarity search.
- Attachments: uploaded document/image URLs when supplied.

Biometrics, profile and training-load parts are cached in process per athlete for 10 minutes, stamped with the athlete's Redis `body_version` (bumped by every data change, so a write on another replica retires the copy). Without Redis the cache lives 60 seconds.

## Tools

The coach exposes custom Python tools through Gemini function declarations:

| Tool | Purpose |
|---|---|
| `simulate_training_impact` | Project CTL, ATL, and TSB after a hypothetical TSS load. |
| `schedule_workout` | Create a structured planned workout in `training_plans`. |
| `schedule_workouts` | Schedule several planned sessions in one call. |
| `import_plan` | Read a plan the athlete shared (Word, Excel, PDF or photo) with the import models and save it, replacing planned sessions on the dates it covers (up to 62 days). Limited to `PLAN_IMPORTS_PER_DAY` (default 5) per athlete per day. |
| `calculate_nutrition` | Estimate kJ, carb, fluid, and sodium targets for a planned effort. |
| `clear_training_plans` | Replace planned workouts in a date range; unless the athlete asked to clear, only days that then get new sessions are cleared. |
| `list_workouts` | List completed activities by athlete-local date range or sport. |
| `get_workout_summary` | Fetch TSS, zones, duration, and load metrics for one workout. |
| `get_workout_streams_window` | Downsampled HR/power/pace for a specific time segment. |
| `log_workout` | Record a completed session the athlete reports in chat. |
| `update_workout` | Correct duration, power, or date on an existing workout. |
| `log_biometrics` | Save manual sleep, HRV, resting HR, or weight. |
| `get_athlete_zones` | HR zone boundaries plus FTP/threshold anchors. |
| `update_profile` | Change FTP, threshold pace/HR, max/resting HR, zone method, weight, height, units, time format or notification settings (same validation, anchor history and re-scoring as Settings). |
| `update_planned_workout` | Reschedule or edit one future planned workout. |
| `delete_planned_workout` | Remove one future planned workout. |
| `list_planned_workouts` | List future planned workouts for a date range. |
| `get_training_load_series` | PMC history (daily TSS, CTL, ATL, TSB) for a date range. |
| `get_biometrics_for_dates` | Sleep/HRV/recovery for up to 7 specific dates. |
| `summarize_workouts` | Week/month or range rollup: TSS, hours, sport mix, hardest session. |
| `compare_workouts` | Side-by-side two completed workouts with numeric deltas. |
| `save_memory` | Persist an important athlete fact to `coach_memories`. |
| `update_memory` | Correct a saved memory by id. |
| `list_memories` | List recent memories (e.g. to pick the right race). |
| `internal_scratchpad` | Sink private model reasoning so it is never shown to the athlete. Dropped when every candidate model reasons natively (Gemini 3+ or `CHAT_MODEL`). |
| `web_search` | SearXNG search; added only when Google Search grounding is unavailable and `SEARXNG_URL` is set. |

The tool list also enables Google Search grounding through `types.Tool(google_search=types.GoogleSearch())`. Models that can't use it (the self-hosted chat model on the OpenAI-compatible endpoint, and Gemini 3+ while `GEMINI_FREE_TIER` is on) get `web_search` instead (`coach_tools.tools_for_models`).

## Memory Pipeline

Long-term memory is stored in `coach_memories`:

- `athlete_id`
- `content`
- `memory_type` (`note` or `race`)
- `entity_key` (for upserts, e.g. one row per race)
- `event_date`
- `embedding vector(3072)`
- `created_at`, `updated_at`

The service embeds user queries and important facts with `GEMINI_EMBEDDING_MODEL`, retrieves the most relevant memories (top 5) through the `match_coach_memories` RPC, and stores new memories after replies (a separate extraction call) or through the `save_memory` / `update_memory` tools.

## Message Persistence

Conversation state is stored in:

- `coach_conversations`
- `coach_messages`

Messages can include `image_urls` and document attachments. The app uploads coach images to the private `coach-uploads` Supabase Storage bucket and sends signed URLs with the message.

## Rate Limits And Access

AI rate limits are enforced per athlete with Redis-backed sliding windows when Redis is available (`dependencies.TIER_DEFAULTS`):

| Tier | Requests/min | Requests/hour | Requests/day |
|---|---:|---:|---:|
| `free` | 5 | 20 | 40 |
| `trial` | 6 | 60 | 150 |
| `premium` | 10 | 150 | 400 |

`rate_limit_rpm` and `rate_limit_rph` in `auth.users.app_metadata` override the minute/hour limits; an `rph` override above the daily limit also lifts the daily cap.

Tier gating uses `auth.users.app_metadata.tier`. A `trial` past `trial_ends_at` (default 14 days after signup) is treated as `free`, and the downgrade is written back to app metadata and `athletes.tier`.

Separately, `gemini_quota.py` spaces model calls to stay under Google's free-tier requests-per-minute per model (about 90% of the stated limit, e.g. 13 for the flash-lite models, 4 for the import models). The count is shared across API replicas through Redis (in process without it) and is skipped when `GEMINI_FREE_TIER=false` or on the OpenAI-compatible provider. Plan import's per-athlete daily count and its "model exhausted until Pacific midnight" flags are also shared through Redis.

## Screen-Level Analysis

Short analysis strings are implemented separately in `backend/app/routers/analysis.py` and `backend/app/services/analysis_cache.py`.

Routes include recovery, sleep, strain, training load, dashboard summary, workout, and time-in-zones analysis. Results are cached in `athlete_analyses` using a context fingerprint to avoid repeated model calls when data has not changed.

Free users receive deterministic fallback summaries; premium and trial users get model-generated analysis from the configured analysis model (with the deterministic text on errors or when the generation budget is used up).

## Operational Notes

- Synchronous SDK calls are run off the FastAPI event loop.
- The backend stores only the athlete-facing response in normal chat output.
- AI-generated training plan rows are normalized/sanitized before insertion.
- Garmin device push from generated workouts is stubbed in the `schedule_workout` tool response (`garmin_push.status = "stubbed"`).
- Google Search grounding sources may be returned alongside replies.
