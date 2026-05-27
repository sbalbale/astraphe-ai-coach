"""
Semantic memory service for the ASTRAPE AI coach.
Stores per-athlete facts with vector embeddings for RAG retrieval.
"""
from __future__ import annotations

import json
import re
import string
from datetime import date, datetime, timezone
from typing import Any

from google import genai
from google.genai import types
from supabase import Client

from app.config import settings

_client = genai.Client(api_key=settings.GEMINI_API_KEY)

_MEMORY_EXTRACT_PROMPT = """\
You are extracting long-term coaching facts from a conversation excerpt.
Return ONLY a JSON array of strings. Each string is one memorable fact (max 150 chars).
Include ONLY: race goals with target dates/times, injuries or physical limitations, \
equipment specifics, dietary restrictions, schedule constraints, or significant performance milestones.
Do NOT include: generic advice, temporary states, or info derivable from biometrics.
If the athlete corrects a previously stated race date (e.g. "I meant June 28th"), output only the corrected race fact (not both).
Return [] if nothing meets the bar.

Conversation:
{transcript}

JSON array:"""


def _get_embedding_model_name() -> str:
    m = settings.GEMINI_EMBEDDING_MODEL
    return m if m.startswith("models/") else f"models/{m}"


def _extract_embedding(text: str) -> list[float]:
    resp = _client.models.embed_content(model=_get_embedding_model_name(), contents=text)
    emb = getattr(resp, "embedding", None)
    if emb is None:
        emb = getattr(resp, "embeddings", None)
    if emb is not None:
        if isinstance(emb, dict):
            return emb.get("values") or emb.get("embedding") or emb.get("vector") or []
        elif isinstance(emb, (list, tuple)) and emb:
            first = emb[0]
            return getattr(first, "values", None) or getattr(first, "embedding", None) or []
        else:
            return getattr(emb, "values", None) or []
    try:
        return resp["embedding"]  # type: ignore[index]
    except Exception:
        return []


def save_coach_memory(athlete_id: str, content: str, db: Client) -> None:
    content = (content or "").strip()[:200]
    if not content:
        return
    try:
        # Prevent obvious duplicates (same trimmed content) from piling up.
        try:
            existing = (
                db.table("coach_memories")
                .select("id")
                .eq("athlete_id", athlete_id)
                .eq("content", content)
                .limit(1)
                .execute()
            )
            if (existing.data or []):
                return
        except Exception:
            # Best-effort only; still attempt insert below.
            pass

        embedding = _extract_embedding(content)
        payload = {
            "athlete_id": athlete_id,
            "content": content,
            "embedding": embedding,
            "memory_type": "note",
            "updated_at": datetime.now(timezone.utc).isoformat(),
        }
        try:
            db.table("coach_memories").insert(payload).execute()
        except Exception as e:
            # Schema-drift tolerance: if local DB hasn't applied migrations yet,
            # retry without the structured columns.
            if "PGRST204" in str(e) or "Could not find the 'memory_type' column" in str(e):
                payload.pop("memory_type", None)
                payload.pop("updated_at", None)
                db.table("coach_memories").insert(payload).execute()
            else:
                raise
    except Exception as e:
        print(f"[memory] save failed: {e}")


def _normalize_entity_key(text: str) -> str:
    t = (text or "").strip().casefold()
    t = t.translate(str.maketrans("", "", string.punctuation))
    t = " ".join(t.split())
    return t[:80]


def upsert_race_memory(
    athlete_id: str,
    *,
    race_name: str,
    event_date: date,
    goal: str | None = None,
    notes: str | None = None,
    db: Client,
) -> dict[str, Any]:
    """
    Upsert a race memory by (athlete_id, memory_type='race', entity_key).
    Overwrites date/content when the same race is corrected (e.g. May 28 -> June 28).
    """
    name = (race_name or "").strip()
    if not name:
        return {"error": "race_name is required"}
    key = _normalize_entity_key(name)
    if not key:
        return {"error": "race_name is required"}
    try:
        iso = event_date.isoformat()
    except Exception:
        return {"error": "event_date must be a date"}

    parts = [f"Race: {name}", f"Date: {iso}"]
    if goal:
        g = str(goal).strip()
        if g:
            parts.append(f"Goal: {g[:120]}")
    if notes:
        n = str(notes).strip()
        if n:
            parts.append(f"Notes: {n[:200]}")
    content = " | ".join(parts)[:200]

    try:
        embedding = _extract_embedding(content)
        existing = (
            db.table("coach_memories")
            .select("id,content,event_date,entity_key")
            .eq("athlete_id", athlete_id)
            .eq("memory_type", "race")
            .eq("entity_key", key)
            .order("updated_at", desc=True)
            .limit(1)
            .execute()
        )
        rows = existing.data or []
        if rows:
            mid = rows[0]["id"]
            upd = (
                db.table("coach_memories")
                .update(
                    {
                        "content": content,
                        "embedding": embedding,
                        "event_date": iso,
                        "updated_at": datetime.now(timezone.utc).isoformat(),
                    }
                )
                .eq("id", mid)
                .eq("athlete_id", athlete_id)
                .execute()
            )
            return {"status": "updated", "id": mid, "race_key": key, "event_date": iso, "content": content, "row": (upd.data or [{}])[0]}

        ins = (
            db.table("coach_memories")
            .insert(
                {
                    "athlete_id": athlete_id,
                    "memory_type": "race",
                    "entity_key": key,
                    "event_date": iso,
                    "content": content,
                    "embedding": embedding,
                    "updated_at": datetime.now(timezone.utc).isoformat(),
                }
            )
            .execute()
        )
        mid = (ins.data or [{}])[0].get("id")
        return {"status": "inserted", "id": mid, "race_key": key, "event_date": iso, "content": content, "row": (ins.data or [{}])[0]}
    except Exception as e:
        return {"error": str(e)}


def list_coach_memories(
    athlete_id: str,
    *,
    db: Client,
    memory_type: str | None = None,
    limit: int = 50,
) -> list[dict[str, Any]]:
    try:
        q = db.table("coach_memories").select("id,content,memory_type,entity_key,event_date,created_at,updated_at").eq("athlete_id", athlete_id)
        if memory_type:
            q = q.eq("memory_type", memory_type)
        res = q.order("updated_at", desc=True).limit(max(1, min(int(limit), 200))).execute()
        return res.data or []
    except Exception:
        return []


_RAG_HINT_KEYWORDS = frozenset({
    "race", "goal", "marathon", "ironman", "injury", "pain", "hurt", "limitation",
    "plan", "schedule", "week", "ftp", "threshold", "ctl", "atl", "tsb", "taper",
    "nutrition", "diet", "equipment", "bike", "shoe", "remember", "allergy",
})


def should_skip_rag_for_message(message: str) -> bool:
    """
    Skip embedding + vector search for short casual messages with no coaching-data cues.
    """
    text = (message or "").strip().lower()
    if any(k in text for k in _RAG_HINT_KEYWORDS):
        return False
    if len(text) < 12:
        return True
    words = text.split()
    if len(words) <= 4 and "?" not in text:
        return True
    return False


def retrieve_relevant_memories(athlete_id: str, query: str, db: Client, top_k: int = 5) -> list[dict]:
    try:
        embedding = _extract_embedding(query)
        result = db.rpc("match_coach_memories", {
            "athlete_id": athlete_id,
            "query_embedding": embedding,
            "match_threshold": 0.50,
            "match_count": top_k,
        }).execute()
        return result.data or []
    except Exception as e:
        print(f"[memory] retrieval failed: {e}")
        return []


def extract_and_save_memories(
    athlete_id: str,
    conversation_excerpt: list[dict],
    db: Client,
    model_name: str | None = None,
) -> None:
    lines: list[str] = []
    for msg in conversation_excerpt[-10:]:
        role = "Athlete" if msg.get("role") == "user" else "Coach"
        body = (msg.get("content") or "").strip()
        if body:
            lines.append(f"{role}: {body[:500]}")
    transcript = "\n".join(lines)
    if not transcript.strip():
        return

    prompt = _MEMORY_EXTRACT_PROMPT.format(transcript=transcript)
    effective_model = model_name or settings.GEMINI_ANALYSIS_MODEL
    try:
        response = _client.models.generate_content(
            model=effective_model,
            contents=prompt,
            config=types.GenerateContentConfig(max_output_tokens=512, temperature=0.1),
        )
        text = (getattr(response, "text", None) or "").strip()
        match = re.search(r"\[.*?\]", text, re.DOTALL)
        if not match:
            return
        facts: Any = json.loads(match.group())
        if not isinstance(facts, list):
            return
        for fact in facts[:5]:
            if isinstance(fact, str) and 10 < len(fact) < 200:
                save_coach_memory(athlete_id, fact, db)
    except Exception as e:
        print(f"[memory] extraction failed: {e}")
