"""Tests for WHOOP startup backfill orchestration."""
from __future__ import annotations

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch


def test_whoop_backfill_recent_iterates_connected_athletes():
    from app.services import whoop_backfill

    mock_db = MagicMock()
    mock_db.table.return_value.select.return_value.eq.return_value.execute.return_value = (
        SimpleNamespace(
            data=[
                {"athlete_id": "w1", "access_token": "tok-1"},
                {"athlete_id": "w2", "access_token": None},
                {"athlete_id": "w3", "access_token": "tok-3"},
            ]
        )
    )

    async def _run():
        with (
            patch("app.services.whoop_backfill.get_admin_db", return_value=mock_db),
            patch(
                "app.services.whoop_backfill.backfill_historical_data",
                new_callable=AsyncMock,
            ) as mock_bf,
        ):
            await whoop_backfill.backfill_recent(hours=12)

        assert mock_bf.await_count == 2
        mock_bf.assert_any_await(
            "w1", "tok-1", mock_db, hours=12, include_workouts=True
        )
        mock_bf.assert_any_await(
            "w3", "tok-3", mock_db, hours=12, include_workouts=True
        )

    asyncio.run(_run())
