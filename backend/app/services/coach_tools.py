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

# Zone-derived intensity factors for TSS estimation (IF^2 * duration_h * 100)
ZONE_IF: dict[str, float] = {
    "Recovery": 0.55,
    "Endurance": 0.70,
    "Tempo": 0.85,
    "Threshold": 0.97,
    "VO2Max": 1.10,
}

FOCUS_ZONES = tuple(ZONE_IF.keys())
DEFAULT_SPORT = "Bike"


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


def _fetch_tss_history_rows(db: Client, athlete_id: str, days_back: int = 120) -> list[dict[str, Any]]:
    start = (date.today() - timedelta(days=days_back)).isoformat()
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

    today = date.today()
    if target_date < today:
        return {"error": "target_date must be today or in the future"}

    rows = _fetch_tss_history_rows(db, athlete_id)
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
        "note": "Projection uses EWMA CTL(42d) and ATL(7d) from daily TSS; today overridden with target_tss; future days assumed 0 TSS.",
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
    if duration_minutes < 10 or duration_minutes > 600:
        return {"error": "duration_minutes must be between 10 and 600"}

    try:
        planned_date = _parse_iso_date(str(args.get("date", "")))
    except ValueError as e:
        return {"error": f"invalid date: {e}"}

    raw_sport = str(args.get("sport", DEFAULT_SPORT)).strip() or DEFAULT_SPORT
    sport_norm = raw_sport.strip().lower()
    # Normalize to frontend conventions (Workout.sport):
    # running|cycling|swimming|rowing|strength
    if sport_norm in ("bike", "biking", "cycling", "ride"):
        sport = "cycling"
    elif sport_norm in ("run", "running"):
        sport = "running"
    elif sport_norm in ("swim", "swimming"):
        sport = "swimming"
    elif sport_norm in ("row", "rowing"):
        sport = "rowing"
    elif sport_norm in ("strength", "gym", "lifting", "weights"):
        sport = "strength"
    else:
        # Default to cycling (most common) to keep downstream UI stable.
        sport = "cycling"

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

    if_ = ZONE_IF[focus_zone]
    dur_h = duration_minutes / 60.0
    est_tss = round(dur_h * (if_**2) * 100.0, 1)

    workout_json = _workout_structure(
        focus_zone, duration_minutes, ftp, thr_hr, max_hr, resting_hr, sport
    )

    title = f"{sport} — {focus_zone} ({duration_minutes}m)"
    # Keep legacy `description` as a compact JSON string for backwards compatibility.
    description = json.dumps(workout_json, ensure_ascii=False)

    try:
        ins = (
            db.table("training_plans")
            .insert(
                {
                    "athlete_id": athlete_id,
                    "planned_date": planned_date.isoformat(),
                    "sport": sport,
                    "title": title,
                    "description": description,
                    "duration_min": duration_minutes,
                    "target_tss": int(round(est_tss)),
                    "primary_zone": focus_zone,
                    "structure": workout_json.get("structure") or [],
                    "status": "planned",
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
        "structure": workout_json.get("structure") or [],
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
            "date": types.Schema(type=types.Type.STRING, description="Planned date ISO YYYY-MM-DD"),
            "sport": types.Schema(
                type=types.Type.STRING,
                description="Bike, Run, or Swim (default Bike)",
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

TOOLS: list[types.Tool] = [
    types.Tool(function_declarations=[_simulate_decl, _schedule_decl, _nutrition_decl]),
]

ToolHandler = Callable[[dict[str, Any], str, Client], dict[str, Any]]

TOOL_HANDLERS: dict[str, ToolHandler] = {
    "simulate_training_impact": lambda args, aid, db: handle_simulate_training_impact(args, athlete_id=aid, db=db),
    "schedule_workout": lambda args, aid, db: handle_schedule_workout(args, athlete_id=aid, db=db),
    "calculate_nutrition": lambda args, aid, db: handle_calculate_nutrition(args, athlete_id=aid, db=db),
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
