# AI Coach System

## Overview

The APEX AI Coach is a Gemini 1.5 Pro agent that combines structured physiological context, function calling for live data retrieval, and a RAG memory pipeline to deliver coaching responses that are simultaneously data-driven and conversationally natural.

---

## System Prompt

The system prompt defines the APEX persona, constraints, and output style. It is injected once per conversation session.

```python
APEX_SYSTEM_PROMPT = """
You are APEX, an AI endurance sports coach embedded in the athlete's training platform.

## Identity
You are a world-class coaching intelligence with deep expertise in:
- Exercise physiology (VO2max, lactate threshold, energy systems)
- Training load management (CTL/ATL/TSB model, periodization)
- Recovery science (HRV, sleep staging, autonomic nervous system)
- Sport-specific technique: running, cycling, triathlon

## Tone and Style
- Concise. Maximum 3 sentences unless the athlete asks for detail.
- Data-first. Always anchor recommendations to actual numbers from context.
  Bad: "Your recovery looks good."
  Good: "Your HRV is 78ms — 9% above your 30-day baseline — and TSB is +28. Attack today."
- Direct. No hedging, no "it depends" without immediately explaining what it depends on.
- Warm but professional. You care about this athlete's performance AND their health.

## Decision Framework
When recommending workout intensity, always check in this order:
1. TSB position (is the athlete fresh or fatigued?)
2. HRV trend (is the nervous system recovered?)
3. Sleep quality (was the last 24h restorative?)
4. Recent load pattern (is this a build week or a recovery week?)

## Hard Rules
- NEVER recommend training through illness (elevated skin temp, low SpO2).
- NEVER recommend an intensity upgrade when TSB < -30.
- ALWAYS reference at least one specific number in every response.
- If asked for a training plan, confirm race date and current CTL before generating.

## Output Format
- For conversational responses: plain prose, no markdown.
- For training plans: structured format with day, session, duration, and target zone.
- For metric explanations: include the formula and a plain-language interpretation.
"""
```

---

## Context Assembly

Before every AI call, the API assembles a structured context object from the database. This is injected as the first user turn in the conversation history.

```python
async def build_athlete_context(athlete_id: str, db: Client) -> dict:
    """
    Assemble complete physiological context for Gemini injection.
    Called before every /coach/message request.
    """
    # Fetch current state
    state = await get_athlete_state(athlete_id, db)
    
    # Fetch recent workouts (last 7)
    recent_workouts = await db.table("workouts") \
        .select("sport,title,started_at,duration_secs,tss,avg_hr") \
        .eq("athlete_id", athlete_id) \
        .order("started_at", desc=True) \
        .limit(7) \
        .execute()
    
    # Fetch HRV trend (last 14 days)
    biometrics = await db.table("biometrics") \
        .select("date,hrv_rmssd,resting_hr,sleep_score,sleep_duration_min,recovery_score") \
        .eq("athlete_id", athlete_id) \
        .order("date", desc=True) \
        .limit(14) \
        .execute()
    
    # Fetch training plan (next 7 days)
    upcoming = await db.table("training_plans") \
        .select("planned_date,sport,title,duration_min,target_tss,status") \
        .eq("athlete_id", athlete_id) \
        .gte("planned_date", date.today().isoformat()) \
        .order("planned_date") \
        .limit(7) \
        .execute()
    
    return {
        "athlete": {
            "name": state.display_name,
            "ftp_watts": state.ftp_watts,
            "max_hr": state.max_hr,
            "threshold_hr": state.threshold_hr,
            "weight_kg": state.weight_kg,
        },
        "current_load": {
            "ctl": state.ctl,
            "atl": state.atl,
            "tsb": state.tsb,
            "readiness_score": state.readiness_score,
        },
        "today_biometrics": {
            "hrv_rmssd": state.hrv_rmssd,
            "hrv_delta_7d": state.hrv_delta_7d,
            "resting_hr": state.resting_hr,
            "sleep_hours": state.sleep_hours,
            "sleep_score": state.sleep_score,
            "recovery_score": state.recovery_score,
        },
        "recent_workouts": recent_workouts.data,
        "biometric_history_14d": biometrics.data,
        "upcoming_plan": upcoming.data,
    }
```

---

## Function Calling Tools

Gemini can autonomously invoke these tools to fetch fresher or more specific data mid-conversation.

```python
APEX_TOOLS = [
    {
        "name": "get_athlete_state",
        "description": "Get the athlete's current load metrics (CTL, ATL, TSB) and readiness score. Use when the athlete asks about their current fitness, fatigue, or form.",
        "parameters": {
            "type": "object",
            "properties": {
                "date": {
                    "type": "string",
                    "description": "ISO date string (YYYY-MM-DD). Defaults to today if not specified."
                }
            }
        }
    },
    {
        "name": "get_workout_history",
        "description": "Get recent completed workouts with TSS and HR data. Use when analyzing training patterns or when the athlete asks about specific past sessions.",
        "parameters": {
            "type": "object",
            "properties": {
                "days_back": {
                    "type": "integer",
                    "description": "Number of days of history to retrieve (1–90).",
                    "default": 14
                },
                "sport": {
                    "type": "string",
                    "enum": ["run", "bike", "swim", "strength", "all"],
                    "default": "all"
                }
            }
        }
    },
    {
        "name": "get_hrv_trend",
        "description": "Get HRV trend analysis including delta vs baseline and trend direction. Use when discussing recovery or nervous system readiness.",
        "parameters": {
            "type": "object",
            "properties": {
                "days": {
                    "type": "integer",
                    "description": "Analysis window in days (7–30).",
                    "default": 14
                }
            }
        }
    },
    {
        "name": "get_training_plan",
        "description": "Get the athlete's upcoming planned sessions. Use when discussing upcoming training or race preparation.",
        "parameters": {
            "type": "object",
            "properties": {
                "days_ahead": {
                    "type": "integer",
                    "description": "Number of days to look ahead (1–30).",
                    "default": 7
                }
            }
        }
    },
    {
        "name": "generate_training_plan",
        "description": "Generate a new training plan block. Use ONLY when the athlete explicitly requests a new plan or significant plan modification.",
        "parameters": {
            "type": "object",
            "properties": {
                "weeks": {
                    "type": "integer",
                    "description": "Number of weeks to plan (1–8).",
                    "default": 4
                },
                "target_event_date": {
                    "type": "string",
                    "description": "ISO date of the target race or event, if applicable."
                },
                "weekly_tss_target": {
                    "type": "integer",
                    "description": "Target weekly TSS for the plan block."
                }
            },
            "required": []
        }
    }
]
```

---

## RAG Memory Pipeline

Before calling Gemini, APEX performs a similarity search over the athlete's `coach_memories` table to retrieve relevant prior coaching context.

```python
import google.generativeai as genai

async def retrieve_relevant_memories(
    athlete_id: str,
    query: str,
    db: Client,
    top_k: int = 5,
) -> list[dict]:
    """
    Retrieve semantically relevant memories from the athlete's coaching history.
    
    Uses Google's text-embedding-004 model for query embedding,
    then performs cosine similarity search via pgvector.
    """
    # Embed the user's query
    embedding_model = genai.embed_content(
        model="models/text-embedding-004",
        content=query,
        task_type="retrieval_query",
    )
    query_embedding = embedding_model["embedding"]
    
    # pgvector similarity search
    result = await db.rpc("match_coach_memories", {
        "athlete_id": athlete_id,
        "query_embedding": query_embedding,
        "match_threshold": 0.75,
        "match_count": top_k,
    }).execute()
    
    return result.data
```

**The `match_coach_memories` SQL function:**

```sql
CREATE OR REPLACE FUNCTION match_coach_memories(
    athlete_id UUID,
    query_embedding vector(768),
    match_threshold FLOAT,
    match_count INT
)
RETURNS TABLE (
    id UUID,
    content TEXT,
    memory_type TEXT,
    context_date DATE,
    similarity FLOAT
)
LANGUAGE SQL STABLE
AS $$
  SELECT
    id,
    content,
    memory_type,
    context_date,
    1 - (embedding <=> query_embedding) AS similarity
  FROM coach_memories
  WHERE
    coach_memories.athlete_id = match_coach_memories.athlete_id
    AND 1 - (embedding <=> query_embedding) > match_threshold
  ORDER BY similarity DESC
  LIMIT match_count;
$$;
```

---

## Full Inference Pipeline

```python
async def coach_response(
    athlete_id: str,
    message: str,
    conversation_history: list[dict],
    db: Client,
) -> AsyncIterator[str]:
    """
    Complete APEX coaching inference pipeline.
    Streams response tokens back to the client.
    """
    # 1. Build structured context
    context = await build_athlete_context(athlete_id, db)
    
    # 2. Retrieve relevant memories
    memories = await retrieve_relevant_memories(athlete_id, message, db)
    
    # 3. Construct messages array
    messages = []
    
    # Inject context as a synthetic "user" setup message
    context_injection = f"""
CURRENT ATHLETE CONTEXT (as of {date.today().isoformat()}):
{json.dumps(context, indent=2)}

RELEVANT COACHING HISTORY:
{chr(10).join(f"- {m['content']} ({m['context_date']})" for m in memories)}
"""
    messages.append({
        "role": "user",
        "parts": [context_injection]
    })
    messages.append({
        "role": "model",
        "parts": ["Context received. Ready to coach."]
    })
    
    # Append conversation history (last 10 turns)
    for turn in conversation_history[-10:]:
        messages.append({
            "role": turn["role"],
            "parts": [turn["content"]]
        })
    
    # Add current message
    messages.append({
        "role": "user",
        "parts": [message]
    })
    
    # 4. Call Gemini with streaming
    model = genai.GenerativeModel(
        model_name="gemini-1.5-pro",
        system_instruction=APEX_SYSTEM_PROMPT,
        tools=APEX_TOOLS,
    )
    
    chat = model.start_chat(history=messages[:-1])
    response = await chat.send_message_async(
        message,
        stream=True,
    )
    
    # 5. Stream response tokens
    full_response = ""
    async for chunk in response:
        token = chunk.text
        full_response += token
        yield token
    
    # 6. Persist response as a memory (async, non-blocking)
    asyncio.create_task(
        store_coaching_memory(
            athlete_id=athlete_id,
            content=f"Q: {message} | A: {full_response}",
            memory_type="coaching_insight",
            context=context["current_load"],
            db=db,
        )
    )
```

---

## Personality Modes

The front-end `coachPersonality` tweak modifies a personality suffix appended to the system prompt.

```python
PERSONALITY_SUFFIXES = {
    "analytical": """
Focus on numbers, trends, and mechanisms. Explain *why* a metric matters.
Lead with data, follow with recommendation.
""",
    "motivational": """
Lead with encouragement. Use athlete's name. Acknowledge the hard work.
Data supports the motivation, not the other way around.
""",
    "gentle": """
Softer tone. Frame challenges as opportunities. Avoid words like "must" or "should."
Check in on how the athlete is feeling, not just the numbers.
""",
    "tough_love": """
Direct and demanding. High expectations. Challenge the athlete.
Call out excuses. The numbers don't lie — hold the athlete to them.
""",
}
```

---

## Token Budget Management

Gemini 1.5 Pro's 1M context window eliminates most truncation concerns, but APEX still implements a tiered context strategy to minimize latency and cost:

| Context Tier | Included When | Approximate Tokens |
|---|---|---|
| Core state | Always | ~200 |
| Recent workouts (7d) | Always | ~400 |
| Biometric history (14d) | Always | ~300 |
| Upcoming plan (7d) | Always | ~300 |
| RAG memories (top 5) | Always | ~500 |
| Extended workout history (90d) | User asks about long-term trends | ~3,000 |
| Full conversation history | Continuing conversation | Variable |
| Season-level TSS history | User asks about fitness trajectory | ~1,500 |

**Total per-query token estimate (typical): ~1,700 tokens input, ~200–400 tokens output.**

At Gemini 1.5 Pro pricing, this is approximately $0.003–0.006 per coaching message — commercially viable at any reasonable user volume.
