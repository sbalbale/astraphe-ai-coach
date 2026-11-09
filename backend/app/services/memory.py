"""
Semantic memory service for the ASTRAPHE AI coach.
Stores per-athlete facts with vector embeddings for RAG retrieval.
"""
from __future__ import annotations

import json
import re
import string
from datetime import date, datetime, timedelta, timezone
from typing import Any

from google import genai
from google.genai import types
from supabase import Client

from app.config import settings
from app.services import gemini_quota
from app.services.llm_provider import get_llm_client
from app.services.time_utils import coerce_timezone_offset_min, local_datetime_from_timezone_offset

# Embeddings have no OpenAI-compatible equivalent wired up (LLM_PROVIDER
# only swaps chat/insights/memory-extraction text generation) — always use
# the real Gemini client for embed_content(), regardless of LLM_PROVIDER.
_client = genai.Client(api_key=settings.GEMINI_API_KEY)
_llm_client = get_llm_client()

_MEMORY_EXTRACT_PROMPT = """\
You are extracting long-term coaching facts from a conversation excerpt.
Today is {today} ({weekday}) in the athlete's timezone.

Include ONLY: race goals with target dates/times, injuries or physical limitations, \
equipment specifics, dietary restrictions, schedule constraints, or significant performance milestones.
Do NOT include: generic advice, temporary states, or info derivable from biometrics.
Do NOT include profile settings (FTP, threshold heart rate or pace, max or resting heart rate, weight):
they live in the athlete's profile, and a copy in memory goes stale.
Only record numbers the athlete stated themselves, never numbers the coach suggested.

Rules:
- Never use relative dates ("Saturday", "this weekend", "next month", "in two weeks"). Resolve every
  time reference against today's date and write it as an absolute date, e.g. "52 km row on 2026-10-24".
- Put the date of any dated event (race, trip, planned effort) in "event_date" as YYYY-MM-DD; otherwise null.
- If a fact is already covered by a known memory below, do not repeat it.
- If a fact updates or supersedes known memories (a corrected date, an event that has now been completed,
  an injury that has healed), output the new fact and list the ids it replaces in "replaces".

Known memories (id · noted on · content):
{known}

Conversation:
{transcript}

Return ONLY a JSON array (or [] if nothing meets the bar) of objects:
[{{"fact": "<max 150 chars>", "event_date": "YYYY-MM-DD" or null, "replaces": ["<id>", ...]}}]
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


def save_coach_memory(athlete_id: str, content: str, db: Client, event_date: str | None = None) -> bool:
    """Store a memory. Returns True when the fact is now stored (newly or already)."""
    content = (content or "").strip()[:200]
    if not content:
        return False
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
                return True
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
        if event_date:
            payload["event_date"] = event_date
        try:
            db.table("coach_memories").insert(payload).execute()
        except Exception as e:
            # Schema-drift tolerance: if local DB hasn't applied migrations yet,
            # retry without the structured columns.
            if "PGRST204" in str(e) or "Could not find the 'memory_type' column" in str(e):
                payload.pop("memory_type", None)
                payload.pop("updated_at", None)
                payload.pop("event_date", None)
                db.table("coach_memories").insert(payload).execute()
            else:
                raise
        return True
    except Exception as e:
        print(f"[memory] save failed: {e}")
        return False


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
        rows = result.data or []
        ids = [r.get("id") for r in rows if r.get("id")]
        if ids:
            try:
                dated = (
                    db.table("coach_memories")
                    .select("id,event_date")
                    .eq("athlete_id", athlete_id)
                    .in_("id", ids)
                    .execute()
                )
                by_id = {d.get("id"): d.get("event_date") for d in (dated.data or [])}
                for r in rows:
                    r.setdefault("event_date", by_id.get(r.get("id")))
            except Exception:
                pass
        return rows
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

    today = _athlete_local_today(athlete_id, db)
    known = list_coach_memories(athlete_id, db=db, limit=40)
    known_lines = "\n".join(
        f"{m.get('id')} · {str(m.get('created_at') or '')[:10]} · {m.get('content')}" for m in known
    ) or "(none)"
    prompt = _MEMORY_EXTRACT_PROMPT.format(
        today=today.isoformat(),
        weekday=today.strftime("%A"),
        known=known_lines,
        transcript=transcript,
    )
    effective_model = model_name or settings.GEMINI_ANALYSIS_MODEL
    try:
        # This runs as a best-effort background task after every chat turn,
        # competing with insights generation for the same analysis-model RPM
        # budget — a short max_wait here (rather than the ~15-20s used for
        # user-facing calls) means a busy budget just skips this pass's
        # memory extraction instead of holding up the background task queue.
        gemini_quota.wait_for_slot(effective_model, max_wait_sec=5.0)
        response = _llm_client.models.generate_content(
            model=effective_model,
            contents=prompt,
            config=types.GenerateContentConfig(max_output_tokens=768, temperature=0.1),
        )
        text = (getattr(response, "text", None) or "").strip()
        match = re.search(r"\[.*\]", text, re.DOTALL)
        if not match:
            return
        facts: Any = json.loads(match.group())
        if not isinstance(facts, list):
            return
        known_ids = {str(m.get("id")) for m in known if m.get("id")}
        for item in facts[:5]:
            # Older prompt versions (and some models) return plain strings.
            if isinstance(item, str):
                item = {"fact": item}
            if not isinstance(item, dict):
                continue
            fact = item.get("fact")
            if not (isinstance(fact, str) and 10 < len(fact) < 200):
                continue
            event_date = _parse_iso_date(item.get("event_date"))
            saved = save_coach_memory(athlete_id, fact, db, event_date=event_date)
            replaces = item.get("replaces") or []
            # Only drop the superseded memories once the replacement is really stored;
            # otherwise an embedding/quota error would delete the fact with nothing in its place.
            if saved and isinstance(replaces, list):
                _delete_memories(athlete_id, [str(r) for r in replaces if str(r) in known_ids], db)
    except Exception as e:
        print(f"[memory] extraction failed: {e}")


def _parse_iso_date(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    try:
        return date.fromisoformat(value.strip()[:10]).isoformat()
    except ValueError:
        return None


_MONTHS = {m: i for i, m in enumerate(
    ["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"], start=1
)}
_TEXT_DATE = re.compile(
    r"\b(jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)[a-z]*\.?\s+(\d{1,2})(?:st|nd|rd|th)?\b(?:,?\s+(\d{4}))?",
    re.IGNORECASE,
)


def memory_event_date(m: dict[str, Any]) -> date | None:
    """When the event a memory is about happens: its event_date, else the first date written
    in it ("July 26, 2026", "June 28"). Without a year, the first such date on or after the
    day the memory was saved. (Most race memories never got an event_date, so a race months
    past still read as the athlete's goal.)"""
    iso = _parse_iso_date(m.get("event_date")) if m.get("event_date") else None
    if iso:
        return date.fromisoformat(iso)
    match = _TEXT_DATE.search(str(m.get("content") or ""))
    if not match:
        return None
    month, day = _MONTHS[match.group(1).lower()[:3]], int(match.group(2))
    saved = _parse_iso_date(str(m.get("created_at") or ""))
    saved_on = date.fromisoformat(saved) if saved else None
    year = int(match.group(3)) if match.group(3) else (saved_on.year if saved_on else datetime.now(timezone.utc).year)
    try:
        when = date(year, month, day)
    except ValueError:
        return None
    if not match.group(3) and saved_on and when < saved_on:
        try:
            when = date(year + 1, month, day)
        except ValueError:
            return None
    return when


def _athlete_local_today(athlete_id: str, db: Client) -> date:
    """Today's date in the athlete's timezone (falls back to UTC)."""
    offset: Any = None
    try:
        res = (
            db.table("athletes")
            .select("timezone_offset_min")
            .eq("id", athlete_id)
            .maybe_single()
            .execute()
        )
        row = getattr(res, "data", None) if res else None
        if isinstance(row, dict):
            offset = row.get("timezone_offset_min")
    except Exception:
        pass
    return local_datetime_from_timezone_offset(coerce_timezone_offset_min(offset)).date()


def _delete_memories(athlete_id: str, ids: list[str], db: Client) -> None:
    for mid in ids:
        try:
            db.table("coach_memories").delete().eq("id", mid).eq("athlete_id", athlete_id).execute()
        except Exception as e:
            print(f"[memory] delete failed: {e}")


MEMORY_CONTEXT_RULE = (
    "memories are notes from earlier conversations. Each has noted_on (when it was saved) and, for "
    "dated events, event_date and event_status. Relative words inside a memory ('Saturday', 'next week') "
    "are relative to noted_on, not today. An event whose event_status is 'past', or whose relative date "
    "has already gone by, has happened: never present it as upcoming. Prefer the most recent memory "
    "when two conflict. Profile numbers (FTP, thresholds, weight) come from athlete_profile, never from "
    "memories."
)

# Notes that restate a profile setting ("Athlete FTP is 275W."). The profile is the source of truth,
# and older notes like this went stale and overrode it.
_PROFILE_SETTING_RE = re.compile(
    r"\b(ftp|threshold power)\b[^.]{0,30}?\b\d{2,3}\s*(w|watts)\b"
    r"|\b(threshold (heart rate|hr)|lthr|max(imum)? (heart rate|hr)|resting (heart rate|hr))\b[^.]{0,30}?\b\d{2,3}\s*bpm\b"
    r"|\bthreshold pace\b[^.]{0,30}?\b\d{1,2}:\d{2}\b",
    re.IGNORECASE,
)


def restates_profile_setting(content: str) -> bool:
    """True for a memory that is just a copy of a profile number (FTP, thresholds)."""
    return bool(_PROFILE_SETTING_RE.search(content or ""))


def memories_for_context(memories: list[dict], today_iso: str) -> list[dict[str, Any]]:
    """
    Memories for the coach's system context, newest first, each with when it was noted,
    how long ago, and (for dated events) whether the event is past, today or upcoming.
    """
    try:
        today = date.fromisoformat(today_iso)
    except (TypeError, ValueError):
        today = datetime.now(timezone.utc).date()
    out: list[dict[str, Any]] = []
    for m in memories:
        content = m.get("content")
        if not content or restates_profile_setting(content):
            continue
        entry: dict[str, Any] = {"content": content}
        noted = _parse_iso_date(str(m.get("created_at") or ""))
        if noted:
            entry["noted_on"] = noted
            entry["noted_days_ago"] = (today - date.fromisoformat(noted)).days
        event_on = memory_event_date(m)
        if event_on:
            entry["event_date"] = event_on.isoformat()
            delta = (event_on - today).days
            entry["event_status"] = "past" if delta < 0 else "today" if delta == 0 else "upcoming"
        out.append(entry)
    out.sort(key=lambda e: e.get("noted_on") or "", reverse=True)
    return out
