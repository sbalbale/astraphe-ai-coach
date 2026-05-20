"""
Semantic memory service for the ASTRAPE AI coach.
Stores per-athlete facts with vector embeddings for RAG retrieval.
"""
from __future__ import annotations

import json
import re
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
        embedding = _extract_embedding(content)
        db.table("coach_memories").insert({
            "athlete_id": athlete_id,
            "content": content,
            "embedding": embedding,
        }).execute()
    except Exception as e:
        print(f"[memory] save failed: {e}")


def retrieve_relevant_memories(athlete_id: str, query: str, db: Client, top_k: int = 5) -> list[dict]:
    try:
        embedding = _extract_embedding(query)
        result = db.rpc("match_coach_memories", {
            "athlete_id": athlete_id,
            "query_embedding": embedding,
            "match_threshold": 0.75,
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
