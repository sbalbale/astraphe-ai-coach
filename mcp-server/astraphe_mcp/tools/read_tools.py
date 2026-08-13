"""Read-only MCP tools for Astraphe (Phase 1 — see docs/MCP_SERVER.md).

Every tool here is a thin wrapper: build an args dict from typed parameters (MCPServer
infers each tool's JSON Schema inputSchema from these type hints), then dispatch into
`app.services.coach_tools.TOOL_HANDLERS`, the same handler functions the in-app AI coach's
agentic tool-calling already uses and backend/tests already covers extensively. Field
names/types are transcribed from the Gemini `types.FunctionDeclaration` objects in
coach_tools.py, which remain the source of truth for what each handler accepts.

Write tools (log_workout, schedule_workout, save_memory, etc.) are deliberately not here
yet — see the Phase 3 write-tool rollout in docs/MCP_SERVER.md.
"""
from __future__ import annotations

from typing import Any

from astraphe_mcp.tools._call import call_handler


def register_read_tools(mcp) -> None:
    @mcp.tool(
        description=(
            "List completed workouts for the connected athlete. Returns duration, avg_hr, "
            "avg_power_w, TSS, and strain per row."
        )
    )
    async def list_workouts(
        on_date: str | None = None,
        start_date: str | None = None,
        end_date: str | None = None,
        sport: str | None = None,
        limit: int | None = None,
    ) -> dict[str, Any]:
        """on_date/start_date/end_date are ISO YYYY-MM-DD. limit defaults to 10, max 25."""
        return await call_handler(
            "list_workouts",
            {"on_date": on_date, "start_date": start_date, "end_date": end_date, "sport": sport, "limit": limit},
        )

    @mcp.tool(
        description=(
            "Get a coaching summary for one completed workout: duration, avg_hr, avg_power_w, "
            "norm_power_w, HR zone split, TSS, strain. No raw streams."
        )
    )
    async def get_workout_summary(
        workout_id: str | None = None,
        on_date: str | None = None,
        sport: str | None = None,
        which: str | None = None,
    ) -> dict[str, Any]:
        """which: 'most_recent' or 'only', used when resolving by date/sport instead of workout_id."""
        return await call_handler(
            "get_workout_summary",
            {"workout_id": workout_id, "on_date": on_date, "sport": sport, "which": which},
        )

    @mcp.tool(
        description=(
            "Get downsampled HR/power/pace for a time segment of one workout. Use only for "
            "questions about a specific minute or interval, not general summaries."
        )
    )
    async def get_workout_streams_window(
        workout_id: str | None = None,
        start_offset_min: float | None = None,
        end_offset_min: float | None = None,
        center_min: float | None = None,
        window_min: float | None = None,
        metrics: list[str] | None = None,
    ) -> dict[str, Any]:
        """metrics: any of hr, power, pace, cadence."""
        return await call_handler(
            "get_workout_streams_window",
            {
                "workout_id": workout_id,
                "start_offset_min": start_offset_min,
                "end_offset_min": end_offset_min,
                "center_min": center_min,
                "window_min": window_min,
                "metrics": metrics,
            },
        )

    @mcp.tool(description="List future planned workouts on the training calendar for a date range.")
    async def list_planned_workouts(
        start_date: str | None = None,
        end_date: str | None = None,
    ) -> dict[str, Any]:
        return await call_handler("list_planned_workouts", {"start_date": start_date, "end_date": end_date})

    @mcp.tool(
        description="Fetch PMC history (daily TSS, CTL, ATL, TSB) for coaching load trends. Defaults to the last 42 days."
    )
    async def get_training_load_series(
        start_date: str | None = None,
        end_date: str | None = None,
    ) -> dict[str, Any]:
        return await call_handler("get_training_load_series", {"start_date": start_date, "end_date": end_date})

    @mcp.tool(
        description="Fetch sleep, HRV, recovery, and strain for specific dates (max 7). Ties workout days to recovery context."
    )
    async def get_biometrics_for_dates(dates: list[str]) -> dict[str, Any]:
        """dates: ISO YYYY-MM-DD, up to 7."""
        return await call_handler("get_biometrics_for_dates", {"dates": dates})

    @mcp.tool(
        description="Roll up completed workouts for a week/month or date range: total TSS, hours, sport mix, hardest session."
    )
    async def summarize_workouts(
        period: str | None = None,
        start_date: str | None = None,
        end_date: str | None = None,
        sport: str | None = None,
    ) -> dict[str, Any]:
        """period: shorthand 'week' or 'month' (athlete-local), used instead of start_date/end_date."""
        return await call_handler(
            "summarize_workouts",
            {"period": period, "start_date": start_date, "end_date": end_date, "sport": sport},
        )

    @mcp.tool(
        description="Side-by-side comparison of two completed workouts (same sport preferred). Returns summaries and numeric deltas (B minus A)."
    )
    async def compare_workouts(
        workout_id_b: str,
        workout_id_a: str | None = None,
        workout_id: str | None = None,
    ) -> dict[str, Any]:
        """workout_id is an alias for workout_id_a."""
        return await call_handler(
            "compare_workouts",
            {"workout_id_a": workout_id_a, "workout_id_b": workout_id_b, "workout_id": workout_id},
        )

    @mcp.tool(description="Fetch HR zone boundaries and FTP/threshold anchors used for training prescriptions.")
    async def get_athlete_zones() -> dict[str, Any]:
        return await call_handler("get_athlete_zones", {})

    @mcp.tool(description="List recent coach memories saved for the athlete (race goals, injuries, preferences, etc.).")
    async def list_memories(
        memory_type: str | None = None,
        limit: int | None = None,
    ) -> dict[str, Any]:
        """memory_type: optional filter, e.g. 'race' or 'note'. limit defaults to 50."""
        return await call_handler("list_memories", {"memory_type": memory_type, "limit": limit})

    @mcp.tool(
        description=(
            "Project the athlete's CTL, ATL, and TSB (Form) on a target date after assuming a "
            "given TSS load today. Read-only projection — does not write anything."
        )
    )
    async def simulate_training_impact(target_tss: int, target_date: str) -> dict[str, Any]:
        """target_date: ISO YYYY-MM-DD."""
        return await call_handler("simulate_training_impact", {"target_tss": target_tss, "target_date": target_date})

    @mcp.tool(
        description=(
            "Estimate energy (kJ) and carbohydrate/fluid targets for a planned effort using TSS, "
            "duration, and CTL as an engine-size proxy. Pure computation — does not write anything."
        )
    )
    async def calculate_nutrition(estimated_duration_minutes: int, estimated_tss: int) -> dict[str, Any]:
        return await call_handler(
            "calculate_nutrition",
            {"estimated_duration_minutes": estimated_duration_minutes, "estimated_tss": estimated_tss},
        )
