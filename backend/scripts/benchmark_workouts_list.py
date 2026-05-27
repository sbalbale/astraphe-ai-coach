"""Benchmark workouts list: DB EXPLAIN + PostgREST + FastAPI /v1/workouts.

Run from backend/:
  python scripts/benchmark_workouts_list.py

Uses local Supabase by default (settings from .env). Does not print secrets.
"""

from __future__ import annotations

import statistics
import subprocess
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

import httpx
import jwt

BACKEND_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND_DIR))

from app.config import settings  # noqa: E402
from supabase import create_client  # noqa: E402

ATHLETE_ID = "1868283c-5a27-4c32-925e-fd7c2fecfdf5"
USER_ID = "61cd603a-819e-459f-9524-50579eb53873"
LIMIT = 20
ROUNDS = 10
DOCKER_DB = "supabase_db_astrape-ai-coach"
JWT_SECRET = "super-secret-jwt-token-with-at-least-32-characters-long"

RLS_FIXED = (
    "athlete_id IN (SELECT id FROM public.athletes "
    "WHERE user_id = (SELECT auth.uid()))"
)
RLS_LEGACY = (
    "athlete_id IN (SELECT id FROM public.athletes WHERE user_id = auth.uid())"
)


def _psql(sql: str) -> str:
    proc = subprocess.run(
        ["docker", "exec", DOCKER_DB, "psql", "-U", "postgres", "-d", "postgres", "-c", sql],
        capture_output=True,
        text=True,
        check=False,
    )
    if proc.returncode != 0:
        raise RuntimeError(proc.stderr or proc.stdout)
    return proc.stdout


def _mint_jwt() -> str:
    now = datetime.now(timezone.utc)
    payload = {
        "sub": USER_ID,
        "role": "authenticated",
        "aud": "authenticated",
        "iat": int(now.timestamp()),
        "exp": int((now + timedelta(hours=1)).timestamp()),
    }
    return jwt.encode(payload, JWT_SECRET, algorithm="HS256")


def _explain_rls(label: str, user_id: str, athlete_id: str) -> str:
    sql = f"""
BEGIN;
SET LOCAL role authenticated;
SELECT set_config('request.jwt.claim.sub', '{user_id}', true);
EXPLAIN (ANALYZE, BUFFERS)
SELECT * FROM public.workouts
WHERE athlete_id = '{athlete_id}'
ORDER BY started_at DESC
LIMIT {LIMIT};
ROLLBACK;
"""
    out = _psql(sql)
    exec_ms = None
    for line in out.splitlines():
        if "Execution Time:" in line:
            exec_ms = line.strip()
    return exec_ms or "(see full plan below)\n" + out


def _set_workouts_policy(using_expr: str) -> None:
    sql = (
        f'ALTER POLICY "workouts_athlete_access" ON public.workouts '
        f"USING ({using_expr});"
    )
    _psql(sql)


def _time_postgrest(token: str, athlete_id: str) -> list[float]:
    db = create_client(settings.SUPABASE_URL, settings.SUPABASE_KEY)
    db.postgrest.auth(token)
    timings: list[float] = []
    for _ in range(ROUNDS):
        t0 = time.perf_counter()
        db.table("workouts").select("*").eq("athlete_id", athlete_id).order(
            "started_at", desc=True
        ).limit(LIMIT).execute()
        timings.append((time.perf_counter() - t0) * 1000)
    return timings


def _api_base_url() -> str:
    base = settings.APP_BASE_URL.rstrip("/")
    if "localhost" in base:
        return base.replace("localhost", "127.0.0.1")
    return base


def _time_api(token: str) -> list[float]:
    url = f"{_api_base_url()}/v1/workouts"
    headers = {"Authorization": f"Bearer {token}"}
    timings: list[float] = []
    with httpx.Client(timeout=30.0) as client:
        for _ in range(ROUNDS):
            t0 = time.perf_counter()
            r = client.get(url, params={"limit": LIMIT}, headers=headers)
            r.raise_for_status()
            timings.append((time.perf_counter() - t0) * 1000)
    return timings


def _summarize_ms(label: str, samples: list[float]) -> str:
    return (
        f"{label}: min={min(samples):.1f}ms p50={statistics.median(samples):.1f}ms "
        f"mean={statistics.mean(samples):.1f}ms max={max(samples):.1f}ms (n={len(samples)})"
    )


def main() -> None:
    print(f"SUPABASE_URL={settings.SUPABASE_URL}")
    print(f"APP_BASE_URL={settings.APP_BASE_URL}")
    print()

    indexes = _psql(
        "SELECT indexname FROM pg_indexes "
        "WHERE schemaname='public' AND tablename='workouts' "
        "AND indexname LIKE '%athlete%started%' ORDER BY 1;"
    )
    print("Workouts athlete+started indexes:")
    print(indexes)

    # --- Legacy RLS (simulate pre-migration) ---
    print("\n=== BEFORE (legacy RLS: auth.uid() without initplan subselect) ===")
    _set_workouts_policy(RLS_LEGACY)
    try:
        print("EXPLAIN:", _explain_rls("legacy", USER_ID, ATHLETE_ID))
        token = _mint_jwt()
        legacy = _time_postgrest(token, ATHLETE_ID)
        print(_summarize_ms("PostgREST select", legacy))
    finally:
        _set_workouts_policy(RLS_FIXED)
        print("(restored fixed RLS policy)")

    # --- Fixed RLS (current) ---
    print("\n=== AFTER (fixed RLS + canonical index) ===")
    print("EXPLAIN:", _explain_rls("fixed", USER_ID, ATHLETE_ID))
    token = _mint_jwt()
    fixed = _time_postgrest(token, ATHLETE_ID)
    print(_summarize_ms("PostgREST select", fixed))

    try:
        api = _time_api(token)
        print(_summarize_ms("GET /v1/workouts", api))
    except Exception as exc:
        print(f"GET /v1/workouts skipped: {exc}")

    if legacy and fixed:
        delta = statistics.mean(legacy) - statistics.mean(fixed)
        pct = (delta / statistics.mean(legacy) * 100) if statistics.mean(legacy) else 0
        print(f"\nPostgREST mean delta (legacy - fixed): {delta:+.1f}ms ({pct:+.0f}%)")


if __name__ == "__main__":
    main()
