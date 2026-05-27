"""
Gemini function-calling tool schemas and handlers for the ASTRAPE agentic coach.
"""
from __future__ import annotations

import json
from datetime import date, timedelta
from typing import Any, Callable

import numpy as np
from google.genai import types
from supabase import Client

from app.services.algorithms import compute_atl, compute_ctl
from app.services.time_utils import athlete_local_date

# Zone-derived intensity factors for TSS estimation (IF^2 * duration_h * 100)
ZONE_IF: dict[str, float] = {
    "Recovery": 0.55,
    "Endurance": 0.70,
    "Tempo": 0.85,
    "Threshold": 0.97,
    "VO2Max": 1.10,
}

FOCUS_ZONES = tuple(ZONE_IF.keys())
DEFAULT_SPORT = "other"


def _parse_iso_date(s: str) -> date:
    if not s or not str(s).strip():
        raise ValueError("date is required")
    return date.fromisoformat(str(s).strip()[:10])


def _safe_float(v: Any) -> float | None:
    try:
        if v is None:
            return None
        return float(v)
    except (TypeError, ValueError):
        return None


def _safe_int(v: Any) -> int | None:
    try:
        if v is None:
            return None
        return int(v)
    except (TypeError, ValueError):
        return None


def _fetch_tss_history_rows(
    db: Client,
    athlete_id: str,
    days_back: int = 120,
    today: date | None = None,
) -> list[dict[str, Any]]:
    local_today = today or athlete_local_date(db, athlete_id)
    start = (local_today - timedelta(days=days_back)).isoformat()
    try:
        res = (
            db.table("tss_history")
            .select("date,daily_tss")
            .eq("athlete_id", athlete_id)
            .gte("date", start)
            .order("date", desc=False)
            .execute()
        )
        return list(res.data or [])
    except Exception as e:
        return [{"_error": str(e)}]


def handle_simulate_training_impact(
    args: dict[str, Any],
    *,
    athlete_id: str,
    db: Client,
) -> dict[str, Any]:
    """
    Project CTL/ATL/TSB on target_date after applying target_tss on today's calendar date.
    """
    try:
        target_tss = int(args.get("target_tss", 0))
    except (TypeError, ValueError):
        return {"error": "target_tss must be an integer"}
    if target_tss < 0:
        return {"error": "target_tss must be non-negative"}

    try:
        target_date = _parse_iso_date(str(args.get("target_date", "")))
    except ValueError as e:
        return {"error": f"invalid target_date: {e}"}

    today = athlete_local_date(db, athlete_id)
    if target_date < today:
        return {"error": "target_date must be today or in the future"}

    rows = _fetch_tss_history_rows(db, athlete_id, today=today)
    if rows and isinstance(rows[0], dict) and rows[0].get("_error"):
        return {"error": rows[0]["_error"]}

    by_day: dict[date, float] = {}
    for r in rows:
        d_raw = r.get("date")
        if not d_raw:
            continue
        try:
            d = date.fromisoformat(str(d_raw)[:10])
        except ValueError:
            continue
        v = _safe_float(r.get("daily_tss"))
        by_day[d] = float(v or 0.0)

    # Build contiguous calendar from (today - 119d) through target_date
    window_start = today - timedelta(days=119)
    start = min(window_start, today)
    # If we have older history inside rows, extend start backward minimally
    if by_day:
        earliest = min(by_day.keys())
        start = min(start, earliest)

    dates: list[date] = []
    cur = start
    while cur <= target_date:
        dates.append(cur)
        cur += timedelta(days=1)

    tss_series: list[float] = []
    for d in dates:
        if d < today:
            tss_series.append(float(by_day.get(d, 0.0)))
        elif d == today:
            tss_series.append(float(target_tss))
        else:
            tss_series.append(0.0)

    arr = np.array(tss_series, dtype=float)
    ctl_arr = compute_ctl(arr, time_constant=42)
    atl_arr = compute_atl(arr, time_constant=7)
    last_i = len(dates) - 1
    projected_ctl = float(ctl_arr[last_i])
    projected_atl = float(atl_arr[last_i])
    projected_tsb = round(projected_ctl - projected_atl, 2)
    days_out = (target_date - today).days

    return {
        "projected_ctl": round(projected_ctl, 2),
        "projected_atl": round(projected_atl, 2),
        "projected_tsb": projected_tsb,
        "days_out": days_out,
        "today_tss_assumed": target_tss,
        "target_date": target_date.isoformat(),
        "series_start": start.isoformat(),
        "note": "Projection uses EWMA CTL(42d) and ATL(7d) from daily TSS; athlete-local today overridden with target_tss; future days assumed 0 TSS.",
    }


def _workout_structure_bodyweight(
    focus_zone: str,
    duration_minutes: int,
    thr_hr: int | None,
    max_hr: int | None,
    resting_hr: int | None,
    sport: str,
) -> dict[str, Any]:
    """
    Mobility / strength sessions without power targets (no FTP-based watts).
    """
    d = max(15, int(duration_minutes))
    wu = max(5, int(round(d * 0.18)))
    cd = max(5, int(round(d * 0.15)))
    main = max(5, d - wu - cd)

    def hr_band(lo_pct: float, hi_pct: float) -> dict[str, int] | None:
        if not all([thr_hr, max_hr, resting_hr]):
            return None
        hrr = max_hr - resting_hr
        if hrr <= 0:
            return None
        return {
            "hr_low": int(resting_hr + lo_pct * hrr),
            "hr_high": int(resting_hr + hi_pct * hrr),
        }

    if sport == "mobility":
        main_desc = {
            "Recovery": "Easy flow: breath-led mobility, joint circles, light range-of-motion work",
            "Endurance": "Sustained mobility circuit: longer holds and repeated patterns without fatigue",
            "Tempo": "Dynamic mobility with controlled tempo; stay smooth, not ballistic",
            "Threshold": "Challenging mobility flows; brief quality-focused efforts with full rest",
            "VO2Max": "Short explosive mobility bouts with generous recovery between rounds",
        }.get(focus_zone, "Main mobility work")
        warmup_desc = "Breath and joint prep; gradual range expansion"
        cooldown_desc = "Down-shift: static holds and parasympathetic breathing"
    else:
        main_desc = {
            "Recovery": "Light movement prep and technique work; very submaximal loads",
            "Endurance": "Muscular endurance strength circuit; controlled reps, steady tempo",
            "Tempo": "Moderate-load strength work with consistent tempo",
            "Threshold": "Heavier compound work; quality sets near challenging loads",
            "VO2Max": "Power or explosive primitives; low reps, full recovery between sets",
        }.get(focus_zone, "Main strength work")
        warmup_desc = "General warmup: activation and patterning"
        cooldown_desc = "Easy cooldown and mobility flush"

    blocks: list[dict[str, Any]] = [
        {
            "phase": "warmup",
            "duration_min": wu,
            "description": warmup_desc,
            "target_hr": hr_band(0.45, 0.65),
        },
        {
            "phase": "main",
            "duration_min": main,
            "description": main_desc,
            "target_hr": hr_band(0.50, 0.72),
        },
        {
            "phase": "cooldown",
            "duration_min": cd,
            "description": cooldown_desc,
            "target_hr": hr_band(0.45, 0.60),
        },
    ]

    return {
        "sport": sport,
        "focus_zone": focus_zone,
        "duration_minutes": d,
        "structure": blocks,
    }


def _workout_structure(
    focus_zone: str,
    duration_minutes: int,
    ftp: int,
    thr_hr: int | None,
    max_hr: int | None,
    resting_hr: int | None,
    sport: str,
) -> dict[str, Any]:
    """Build a structured JSON workout (warmup / main / cooldown)."""
    if sport in ("mobility", "strength"):
        return _workout_structure_bodyweight(
            focus_zone, duration_minutes, thr_hr, max_hr, resting_hr, sport
        )
    d = max(15, int(duration_minutes))
    wu = max(5, int(round(d * 0.15)))
    cd = max(5, int(round(d * 0.15)))
    main = max(5, d - wu - cd)
    ftp = max(ftp, 1)
    z2_lo, z2_hi = int(0.56 * ftp), int(0.75 * ftp)
    z3_lo, z3_hi = int(0.76 * ftp), int(0.90 * ftp)
    z4_lo, z4_hi = int(0.91 * ftp), int(1.05 * ftp)
    z5_lo, z5_hi = int(1.06 * ftp), int(1.20 * ftp)

    def hr_band(lo_pct: float, hi_pct: float) -> dict[str, int] | None:
        if not all([thr_hr, max_hr, resting_hr]):
            return None
        hrr = max_hr - resting_hr
        if hrr <= 0:
            return None
        return {
            "hr_low": int(resting_hr + lo_pct * hrr),
            "hr_high": int(resting_hr + hi_pct * hrr),
        }

    blocks: list[dict[str, Any]] = [
        {
            "phase": "warmup",
            "duration_min": wu,
            "description": "Gradual ramp into working intensity",
            "target_watts": {"low": z2_lo, "high": z2_hi},
            "target_hr": hr_band(0.55, 0.70),
        }
    ]

    if focus_zone == "Recovery":
        blocks.append(
            {
                "phase": "main",
                "duration_min": main,
                "description": "Continuous low intensity; conversational pace",
                "target_watts": {"low": int(0.50 * ftp), "high": int(0.60 * ftp)},
                "target_hr": hr_band(0.50, 0.65),
            }
        )
    elif focus_zone == "Endurance":
        blocks.append(
            {
                "phase": "main",
                "duration_min": main,
                "description": "Steady Zone 2 aerobic endurance",
                "target_watts": {"low": z2_lo, "high": z2_hi},
                "target_hr": hr_band(0.65, 0.78),
            }
        )
    elif focus_zone == "Tempo":
        blocks.append(
            {
                "phase": "main",
                "duration_min": main,
                "description": "Sustained tempo / upper sweet spot",
                "target_watts": {"low": z3_lo, "high": z3_hi},
                "target_hr": hr_band(0.78, 0.88),
            }
        )
    elif focus_zone == "Threshold":
        n_rep = max(2, min(6, main // 12))
        work = min(12, max(6, main // (n_rep * 2)))
        rec = max(3, work // 3)
        blocks.append(
            {
                "phase": "main",
                "duration_min": main,
                "description": f"{n_rep}x{work}min @ threshold with {rec}min recovery",
                "intervals": [
                    {
                        "type": "work",
                        "duration_min": work,
                        "target_watts": {"low": z4_lo, "high": z4_hi},
                        "target_hr": hr_band(0.85, 0.95),
                    },
                    {
                        "type": "recovery",
                        "duration_min": rec,
                        "target_watts": {"low": z2_lo, "high": int(0.72 * ftp)},
                    },
                ]
                * n_rep,
            }
        )
    else:  # VO2Max
        n_rep = max(3, min(8, main // 6))
        work = 3
        slot = main // max(1, n_rep * 2)
        rec = max(2, min(4, max(0, slot - work)))
        blocks.append(
            {
                "phase": "main",
                "duration_min": main,
                "description": f"{n_rep}x{work}min VO2max with {rec}min recovery",
                "intervals": [
                    {
                        "type": "work",
                        "duration_min": work,
                        "target_watts": {"low": z5_lo, "high": z5_hi},
                        "target_hr": hr_band(0.92, 1.00),
                    },
                    {
                        "type": "recovery",
                        "duration_min": rec,
                        "target_watts": {"low": z2_lo, "high": int(0.70 * ftp)},
                    },
                ]
                * n_rep,
            }
        )

    blocks.append(
        {
            "phase": "cooldown",
            "duration_min": cd,
            "description": "Easy spin / flush",
            "target_watts": {"low": int(0.50 * ftp), "high": int(0.65 * ftp)},
            "target_hr": hr_band(0.55, 0.70),
        }
    )

    return {
        "sport": sport,
        "focus_zone": focus_zone,
        "duration_minutes": d,
        "structure": blocks,
    }


def _sanitize_workout_structure(raw_structure: Any) -> list[dict[str, Any]]:
    """Normalize legacy generator blocks and AI tool output to canonical interval shape."""
    if not isinstance(raw_structure, list):
        return []
    clean_structure: list[dict[str, Any]] = []

    for block in raw_structure:
        if not isinstance(block, dict):
            continue

        duration = block.get("duration_minutes") or block.get("duration_min") or block.get("duration") or 0
        try:
            duration = int(duration)
        except (TypeError, ValueError):
            duration = 0

        name = block.get("name") or block.get("phase") or block.get("type") or "Step"

        clean_block: dict[str, Any] = {
            "name": str(name).capitalize(),
            "duration_minutes": duration,
            "description": str(block.get("description") or ""),
            "sub_intervals": [],
        }

        for key in ("target_power_percent_ftp", "target_hr_zone"):
            if key in block:
                try:
                    clean_block[key] = int(block[key])
                except (TypeError, ValueError):
                    pass

        raw_subs = block.get("sub_intervals") or block.get("intervals") or []
        if isinstance(raw_subs, list):
            for sub in raw_subs:
                if not isinstance(sub, dict):
                    continue
                sub_dur = sub.get("duration_minutes") or sub.get("duration_min") or sub.get("duration") or 0
                try:
                    sub_dur_int = int(sub_dur)
                except (TypeError, ValueError):
                    sub_dur_int = 0
                sub_name = sub.get("name") or sub.get("type") or "Interval"

                clean_sub: dict[str, Any] = {
                    "name": str(sub_name).capitalize(),
                    "duration_minutes": sub_dur_int,
                    "description": str(sub.get("description") or ""),
                }
                for key in ("target_power_percent_ftp", "target_hr_zone"):
                    if key in sub:
                        try:
                            clean_sub[key] = int(sub[key])
                        except (TypeError, ValueError):
                            pass
                clean_block["sub_intervals"].append(clean_sub)

        clean_structure.append(clean_block)

    return clean_structure


def handle_schedule_workout(
    args: dict[str, Any],
    *,
    athlete_id: str,
    db: Client,
) -> dict[str, Any]:
    focus_zone = str(args.get("focus_zone", "Endurance")).strip()
    if focus_zone not in ZONE_IF:
        return {"error": f"focus_zone must be one of {FOCUS_ZONES}"}

    try:
        duration_minutes = int(args.get("duration_minutes", 45))
    except (TypeError, ValueError):
        return {"error": "duration_minutes must be an integer"}
    # Allow 0-min entries for rest days / guideline notes that must persist in the plan.
    if duration_minutes < 0 or duration_minutes > 600:
        return {"error": "duration_minutes must be between 0 and 600"}

    try:
        planned_date = _parse_iso_date(str(args.get("date", "")))
    except ValueError as e:
        return {"error": f"invalid date: {e}"}

    raw_sport = str(args.get("sport", DEFAULT_SPORT)).strip() or DEFAULT_SPORT
    sport_norm = raw_sport.strip().lower()
    # Normalize to frontend conventions (Workout.sport):
    if sport_norm in ("bike", "biking", "cycling", "cycle", "ride"):
        sport = "bike"
    elif sport_norm in ("run", "running", "jogging"):
        sport = "run"
    elif sport_norm in ("swim", "swimming"):
        sport = "swim"
    elif sport_norm in ("row", "rowing", "erg"):
        sport = "row"
    elif sport_norm in ("strength", "gym", "lifting", "weights"):
        sport = "strength"
    elif sport_norm in ("mobility", "yoga", "stretching", "stretch"):
        sport = "mobility"
    else:
        # Safely default to 'other' for unrecognized activities
        sport = "other"

    try:
        res = (
            db.table("athletes")
            .select("ftp_watts,threshold_hr,max_hr,resting_hr,threshold_pace,display_name")
            .eq("id", athlete_id)
            .maybe_single()
            .execute()
        )
        row = res.data or {}
    except Exception as e:
        return {"error": f"athlete_query_failed: {e}"}

    ftp = _safe_int(row.get("ftp_watts")) or 250
    thr_hr = _safe_int(row.get("threshold_hr"))
    max_hr = _safe_int(row.get("max_hr"))
    resting_hr = _safe_int(row.get("resting_hr"))

    if duration_minutes == 0:
        est_tss = 0.0
        workout_json = {"sport": sport, "focus_zone": focus_zone, "duration_minutes": 0, "structure": []}
        title = f"{sport} — Guidelines/Rest"
    else:
        if_ = ZONE_IF[focus_zone]
        dur_h = duration_minutes / 60.0
        est_tss = round(dur_h * (if_**2) * 100.0, 1)
        workout_json = _workout_structure(
            focus_zone, duration_minutes, ftp, thr_hr, max_hr, resting_hr, sport
        )
        title = f"{sport} — {focus_zone} ({duration_minutes}m)"

    raw_ai_structure = args.get("structure")
    if duration_minutes > 0 and isinstance(raw_ai_structure, list) and len(raw_ai_structure) > 0:
        workout_json["structure"] = raw_ai_structure

    clean_structure = _sanitize_workout_structure(workout_json.get("structure") or [])
    workout_json["structure"] = clean_structure

    # Keep legacy `description` as a compact JSON string for backwards compatibility.
    description = json.dumps(workout_json, ensure_ascii=False)
    markdown_notes = str(args.get("markdown_notes", "")).strip()

    try:
        ins = (
            db.table("training_plans")
            .insert(
                {
                    "athlete_id": athlete_id,
                    "planned_date": planned_date.isoformat(),
                    "sport": sport,
                    "title": title,
                    "description": markdown_notes if markdown_notes else description,
                    "duration_min": duration_minutes,
                    "target_tss": int(round(est_tss)),
                    "primary_zone": focus_zone,
                    "structure": clean_structure,
                    "status": "planned",
                    "generated_by": "astrape_ai",
                }
            )
            .execute()
        )
        row_id = (ins.data or [{}])[0].get("id") if ins.data else None
    except Exception as e:
        return {"error": f"training_plans_insert_failed: {e}"}

    workout_strict = {
        "id": row_id,
        "date": planned_date.isoformat(),
        "title": title,
        "sport": sport,
        "primary_zone": focus_zone,
        "duration_minutes": duration_minutes,
        "projected_tss": int(round(est_tss)),
        "description": (workout_json.get("notes") or "") if isinstance(workout_json, dict) else "",
        "structure": clean_structure,
        "completed": False,
    }

    return {
        "training_plan_id": row_id,
        "planned_date": planned_date.isoformat(),
        "title": title,
        "target_tss_estimate": est_tss,
        "workout": workout_json,
        "workout_strict": workout_strict,
        "garmin_push": {
            "status": "stubbed",
            "reason": "Garmin Training API integration not yet wired",
        },
    }


def handle_calculate_nutrition(
    args: dict[str, Any],
    *,
    athlete_id: str,
    db: Client,
) -> dict[str, Any]:
    try:
        est_duration = int(args.get("estimated_duration_minutes", 60))
    except (TypeError, ValueError):
        return {"error": "estimated_duration_minutes must be an integer"}
    try:
        est_tss = int(args.get("estimated_tss", 0))
    except (TypeError, ValueError):
        return {"error": "estimated_tss must be an integer"}

    if est_duration <= 0:
        return {"error": "estimated_duration_minutes must be positive"}
    if est_tss < 0:
        return {"error": "estimated_tss must be non-negative"}

    ctl = 0.0
    try:
        tss_res = (
            db.table("tss_history")
            .select("ctl")
            .eq("athlete_id", athlete_id)
            .order("date", desc=True)
            .limit(1)
            .execute()
        )
        if tss_res.data:
            ctl = float(_safe_float(tss_res.data[0].get("ctl")) or 0.0)
    except Exception:
        pass

    # kJ proxy from TSS; small CTL-based correction (engine size)
    ctl_factor = 1.0 + min(0.15, max(0.0, ctl / 500.0) * 0.05)
    kj = round(float(est_tss) * 3.6 * ctl_factor, 1)

    dur_h = est_duration / 60.0
    tss_per_h = (est_tss / dur_h) if dur_h > 1e-6 else 0.0

    if est_duration <= 60 and est_tss < 80:
        carb_g_per_hour = 0.0
    elif est_duration <= 120:
        carb_g_per_hour = 60.0
    elif est_duration <= 180:
        carb_g_per_hour = 80.0
    else:
        carb_g_per_hour = 90.0

    if tss_per_h >= 70 and est_duration > 60:
        carb_g_per_hour = max(carb_g_per_hour, 80.0)
    if est_duration > 180:
        carb_g_per_hour = max(carb_g_per_hour, 90.0)

    total_carb_g = round(carb_g_per_hour * dur_h, 1) if carb_g_per_hour > 0 else 0.0

    # Fluid: use mid band 625 mL/hr (weather-aware hydration TODO)
    fluid_ml_per_hour = 625.0
    total_fluid_ml = int(round(fluid_ml_per_hour * dur_h))

    sodium_mg_per_hour = 500.0

    return {
        "kj": kj,
        "carb_g_per_hour": carb_g_per_hour,
        "total_carb_g": total_carb_g,
        "fluid_ml_per_hour": fluid_ml_per_hour,
        "total_fluid_ml": total_fluid_ml,
        "sodium_mg_per_hour": sodium_mg_per_hour,
        "ctl_proxy": round(ctl, 2),
        "notes": "Weather-adjusted fluid targets not applied in v1 (TODO).",
    }


def handle_save_memory(
    args: dict[str, Any],
    *,
    athlete_id: str,
    db: Client,
) -> dict[str, Any]:
    """Persist an important athlete fact to long-term coach memory."""
    content = str(args.get("content", "")).strip()[:200]
    if not content:
        return {"error": "content is required"}
    try:
        from app.services.memory import save_coach_memory
        save_coach_memory(athlete_id, content, db)
        return {"status": "saved", "content": content}
    except Exception as e:
        return {"error": str(e)}


def handle_update_memory(
    args: dict[str, Any],
    *,
    athlete_id: str,
    db: Client,
) -> dict[str, Any]:
    """
    Update a coach memory row. Prefer selecting a target using list_memories first.

    This handler is resilient to schema drift: if optional columns (event_date, entity_key, memory_type)
    don't exist yet, it retries with only supported fields.
    """
    memory_id = str(args.get("memory_id", "")).strip()
    if not memory_id:
        return {"error": "memory_id is required"}

    update: dict[str, Any] = {}
    for k in ("content", "memory_type", "entity_key", "event_date"):
        if k in args and args.get(k) is not None:
            update[k] = args.get(k)
    if not update:
        return {"error": "No fields to update"}

    def _try_update(payload: dict[str, Any]) -> Any:
        return (
            db.table("coach_memories")
            .update(payload)
            .eq("id", memory_id)
            .eq("athlete_id", athlete_id)
            .execute()
        )

    try:
        res = _try_update(update)
        return {"status": "success", "memory": (res.data or [{}])[0] if res else None}
    except Exception as e:
        err = str(e)
        # Common failure while local DB hasn't applied the new migration yet.
        if "does not exist" in err and "coach_memories." in err:
            safe = dict(update)
            for drop in ("event_date", "entity_key", "memory_type"):
                safe.pop(drop, None)
            if not safe:
                return {"error": err}
            try:
                res2 = _try_update(safe)
                return {
                    "status": "partial_success",
                    "dropped_fields": list(set(update.keys()) - set(safe.keys())),
                    "memory": (res2.data or [{}])[0] if res2 else None,
                }
            except Exception as e2:
                return {"error": str(e2)}
        return {"error": err}


def handle_list_memories(
    args: dict[str, Any],
    *,
    athlete_id: str,
    db: Client,
) -> dict[str, Any]:
    from app.services.memory import list_coach_memories

    memory_type = args.get("memory_type")
    limit = args.get("limit", 50)
    rows = list_coach_memories(
        athlete_id,
        db=db,
        memory_type=str(memory_type) if memory_type else None,
        limit=int(limit) if isinstance(limit, int | float | str) else 50,
    )
    return {"status": "success", "memories": rows}


def handle_clear_training_plans(
    args: dict[str, Any],
    *,
    athlete_id: str,
    db: Client,
) -> dict[str, Any]:
    """
    Delete training_plans rows for this athlete within a date range (inclusive).
    This prevents duplicate workouts when regenerating a week.
    """
    try:
        start_date = _parse_iso_date(str(args.get("start_date", "")))
    except ValueError as e:
        return {"error": f"invalid start_date: {e}"}
    try:
        end_date = _parse_iso_date(str(args.get("end_date", "")))
    except ValueError as e:
        return {"error": f"invalid end_date: {e}"}
    if end_date < start_date:
        return {"error": "end_date must be >= start_date"}

    try:
        res = (
            db.table("training_plans")
            .delete()
            .eq("athlete_id", athlete_id)
            .gte("planned_date", start_date.isoformat())
            .lte("planned_date", end_date.isoformat())
            .execute()
        )
        deleted = len(res.data or [])
        return {"status": "success", "deleted": deleted, "start_date": start_date.isoformat(), "end_date": end_date.isoformat()}
    except Exception as e:
        return {"error": f"training_plans_delete_failed: {e}"}


# --- Gemini tool declarations ---

_simulate_decl = types.FunctionDeclaration(
    name="simulate_training_impact",
    description=(
        "Project the athlete's CTL, ATL, and TSB (Form) on a target calendar date after "
        "assuming they complete a given TSS load today. Future days until the target "
        "assume 0 TSS. Use for all 'what if' readiness questions."
    ),
    parameters=types.Schema(
        type=types.Type.OBJECT,
        properties={
            "target_tss": types.Schema(type=types.Type.INTEGER, description="TSS to assume for today"),
            "target_date": types.Schema(
                type=types.Type.STRING,
                description="ISO date (YYYY-MM-DD) for the projection endpoint",
            ),
        },
        required=["target_tss", "target_date"],
    ),
)

_schedule_decl = types.FunctionDeclaration(
    name="schedule_workout",
    description=(
        "Build a structured workout and write it to the athlete's training_plans calendar. "
        "Garmin device push is stubbed until the integration is live."
    ),
    parameters=types.Schema(
        type=types.Type.OBJECT,
        properties={
            "duration_minutes": types.Schema(type=types.Type.INTEGER),
            "focus_zone": types.Schema(
                type=types.Type.STRING,
                enum=list(FOCUS_ZONES),
            ),
            "date": types.Schema(
                type=types.Type.STRING,
                description=(
                    "Planned date ISO YYYY-MM-DD. Resolve relative dates from the athlete-local "
                    "current_local_date/current_local_datetime in SYSTEM CONTEXT; tomorrow is "
                    "current_local_date + 1 calendar day."
                ),
            ),
            "sport": types.Schema(
                type=types.Type.STRING,
                description="run, bike, swim, row, strength, mobility, or other. (default other)",
            ),
            "structure": types.Schema(
                type=types.Type.ARRAY,
                description="The workout structure blocks (Warmup, Main Set, Cooldown).",
                items=types.Schema(
                    type=types.Type.OBJECT,
                    properties={
                        "name": types.Schema(
                            type=types.Type.STRING,
                            description="'Warmup', 'Main Set', or 'Cooldown'",
                        ),
                        "duration_minutes": types.Schema(type=types.Type.INTEGER),
                        "description": types.Schema(type=types.Type.STRING),
                        "target_power_percent_ftp": types.Schema(type=types.Type.INTEGER),
                        "target_hr_zone": types.Schema(type=types.Type.INTEGER),
                        "sub_intervals": types.Schema(
                            type=types.Type.ARRAY,
                            description="Optional nested intervals (e.g., 6x 3min Work / 1min Recovery).",
                            items=types.Schema(
                                type=types.Type.OBJECT,
                                properties={
                                    "name": types.Schema(
                                        type=types.Type.STRING,
                                        description="'Work' or 'Recovery'",
                                    ),
                                    "duration_minutes": types.Schema(type=types.Type.INTEGER),
                                    "target_power_percent_ftp": types.Schema(type=types.Type.INTEGER),
                                    "target_hr_zone": types.Schema(type=types.Type.INTEGER),
                                },
                            ),
                        ),
                    },
                ),
            ),
            "markdown_notes": types.Schema(
                type=types.Type.STRING,
                description=(
                    "A concise Markdown-formatted summary of the intervals, including target watts, "
                    "heart rate, or pace (e.g., a table or bulleted list)."
                ),
            ),
        },
        required=["duration_minutes", "focus_zone", "date"],
    ),
)

_nutrition_decl = types.FunctionDeclaration(
    name="calculate_nutrition",
    description=(
        "Estimate energy (kJ) and carbohydrate/fluid targets for a planned effort using "
        "TSS, duration, and CTL as an engine-size proxy. Use for all fueling questions."
    ),
    parameters=types.Schema(
        type=types.Type.OBJECT,
        properties={
            "estimated_duration_minutes": types.Schema(type=types.Type.INTEGER),
            "estimated_tss": types.Schema(type=types.Type.INTEGER),
        },
        required=["estimated_duration_minutes", "estimated_tss"],
    ),
)

_save_memory_decl = types.FunctionDeclaration(
    name="save_memory",
    description=(
        "Save an important long-term fact about the athlete to persistent memory. "
        "Use proactively when the athlete reveals a specific race goal or target date, "
        "an injury or physical limitation, a dietary restriction, equipment preference, "
        "or a significant performance milestone. Call once per distinct fact."
    ),
    parameters=types.Schema(
        type=types.Type.OBJECT,
        properties={
            "content": types.Schema(
                type=types.Type.STRING,
                description="A concise statement of the fact to remember (max 200 chars).",
            ),
        },
        required=["content"],
    ),
)

_update_memory_decl = types.FunctionDeclaration(
    name="update_memory",
    description=(
        "Update an existing coach memory by id. Use this when the athlete corrects previously saved "
        "information (e.g. correcting a race date from May 28 to June 28). Prefer calling list_memories "
        "first to get the correct memory id."
    ),
    parameters=types.Schema(
        type=types.Type.OBJECT,
        properties={
            "memory_id": types.Schema(type=types.Type.STRING, description="coach_memories.id to update"),
            "content": types.Schema(type=types.Type.STRING, description="New memory content (max ~200 chars recommended)"),
            "memory_type": types.Schema(type=types.Type.STRING, description="Optional type, e.g. 'race' or 'note'"),
            "entity_key": types.Schema(type=types.Type.STRING, description="Optional normalized key for upserts"),
            "event_date": types.Schema(type=types.Type.STRING, description="Optional ISO date YYYY-MM-DD"),
        },
        required=["memory_id"],
    ),
)

_list_memories_decl = types.FunctionDeclaration(
    name="list_memories",
    description="List recent coach memories for the athlete. Use to disambiguate when multiple races exist.",
    parameters=types.Schema(
        type=types.Type.OBJECT,
        properties={
            "memory_type": types.Schema(type=types.Type.STRING, description="Optional filter, e.g. 'race' or 'note'"),
            "limit": types.Schema(type=types.Type.INTEGER, description="Max rows (default 50)"),
        },
        required=[],
    ),
)

_clear_training_plans_decl = types.FunctionDeclaration(
    name="clear_training_plans",
    description=(
        "Delete planned workouts (training_plans) in a date range for the current athlete. "
        "Use this before scheduling a replacement week to prevent duplicates."
    ),
    parameters=types.Schema(
        type=types.Type.OBJECT,
        properties={
            "start_date": types.Schema(type=types.Type.STRING, description="ISO date YYYY-MM-DD (inclusive)"),
            "end_date": types.Schema(type=types.Type.STRING, description="ISO date YYYY-MM-DD (inclusive)"),
        },
        required=["start_date", "end_date"],
    ),
)

def handle_internal_scratchpad(
    args: dict[str, Any],
    *,
    athlete_id: str,
    db: Client,
) -> dict[str, Any]:
    """
    Sinks internal AI reasoning and planning into a tool call to hide it from the user.
    """
    print("--- [AI SCRATCHPAD RECORDED] ---")
    return {"status": "success", "message": "Thought recorded in scratchpad."}


_scratchpad_decl = types.FunctionDeclaration(
    name="internal_scratchpad",
    description=(
        "Use this tool to record your internal reasoning, planning, and draft responses. "
        "Content sent here will be hidden from the user. Use this BEFORE calling other tools "
        "or generating your final message to the athlete."
    ),
    parameters=types.Schema(
        type=types.Type.OBJECT,
        properties={
            "thought": types.Schema(
                type=types.Type.STRING,
                description="Your detailed reasoning, step-by-step plan, or draft content.",
            ),
        },
        required=["thought"],
    ),
)

TOOLS: list[types.Tool] = [
    types.Tool(function_declarations=[
        _simulate_decl, 
        _schedule_decl, 
        _nutrition_decl, 
        _clear_training_plans_decl, 
        _save_memory_decl,
        _list_memories_decl,
        _update_memory_decl,
        _scratchpad_decl
    ]),
    types.Tool(google_search=types.GoogleSearch()),
]

ToolHandler = Callable[[dict[str, Any], str, Client], dict[str, Any]]

TOOL_HANDLERS: dict[str, ToolHandler] = {
    "simulate_training_impact": lambda args, aid, db: handle_simulate_training_impact(args, athlete_id=aid, db=db),
    "schedule_workout": lambda args, aid, db: handle_schedule_workout(args, athlete_id=aid, db=db),
    "calculate_nutrition": lambda args, aid, db: handle_calculate_nutrition(args, athlete_id=aid, db=db),
    "clear_training_plans": lambda args, aid, db: handle_clear_training_plans(args, athlete_id=aid, db=db),
    "save_memory": lambda args, aid, db: handle_save_memory(args, athlete_id=aid, db=db),
    "list_memories": lambda args, aid, db: handle_list_memories(args, athlete_id=aid, db=db),
    "update_memory": lambda args, aid, db: handle_update_memory(args, athlete_id=aid, db=db),
    "internal_scratchpad": lambda args, aid, db: handle_internal_scratchpad(args, athlete_id=aid, db=db),
}


def parse_function_args(fc: types.FunctionCall) -> dict[str, Any]:
    """Normalize Gemini function args to a dict."""
    raw = fc.args
    if raw is None:
        return {}
    if isinstance(raw, dict):
        return dict(raw)
    if isinstance(raw, str):
        try:
            return json.loads(raw)
        except json.JSONDecodeError:
            return {}
    # Some SDK versions expose mapping-like objects
    try:
        return dict(raw)  # type: ignore[arg-type]
    except Exception:
        return {}
