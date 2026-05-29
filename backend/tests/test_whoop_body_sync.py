"""Tests for WHOOP body measurement sync into biometrics.weight_kg."""

import asyncio
from datetime import date
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.routers import sync as sync_router


WHOOP_BODY = {"weight_kilogram": 87.09, "height_meter": 1.854}
WHOOP_PROFILE = {"user_id": "whoop-user-1", "first_name": "Test"}


def _athletes_table(have_height: bool = True):
    tbl = MagicMock()
    row = {"height_cm": 180.0 if have_height else None}
    tbl.select.return_value.eq.return_value.maybe_single.return_value.execute.return_value = MagicMock(
        data=row
    )
    return tbl


def _biometrics_table(weight_kg=None):
    tbl = MagicMock()
    data = None
    if weight_kg is not None:
        data = {"weight_kg": weight_kg}
    tbl.select.return_value.eq.return_value.eq.return_value.maybe_single.return_value.execute.return_value = (
        MagicMock(data=data)
    )
    tbl.upsert.return_value.execute.return_value = MagicMock(data=[])
    return tbl


def _oauth_tokens_table():
    tbl = MagicMock()
    tbl.update.return_value.eq.return_value.eq.return_value.execute.return_value = MagicMock(data=[])
    return tbl


def _db_for_body_sync(*, have_height: bool = True, bio_weight_kg=None):
    db = MagicMock()
    athletes_tbl = _athletes_table(have_height=have_height)
    biometrics_tbl = _biometrics_table(bio_weight_kg)
    oauth_tbl = _oauth_tokens_table()

    def table(name):
        if name == "athletes":
            return athletes_tbl
        if name == "biometrics":
            return biometrics_tbl
        if name == "oauth_tokens":
            return oauth_tbl
        return MagicMock()

    db.table.side_effect = table
    db._athletes_tbl = athletes_tbl
    db._biometrics_tbl = biometrics_tbl
    return db


def test_whoop_biometrics_weight_kg_missing_when_no_row():
    db = _db_for_body_sync(bio_weight_kg=None)
    assert sync_router._whoop_biometrics_weight_kg_missing(db, "athlete-1", date(2026, 5, 21)) is True


def test_whoop_biometrics_weight_kg_missing_when_null():
    db = _db_for_body_sync(bio_weight_kg=None)
    tbl = db.table("biometrics")
    tbl.select.return_value.eq.return_value.eq.return_value.maybe_single.return_value.execute.return_value = (
        MagicMock(data={"weight_kg": None})
    )
    assert sync_router._whoop_biometrics_weight_kg_missing(db, "athlete-1", date(2026, 5, 21)) is True


def test_whoop_biometrics_weight_kg_not_missing_when_set():
    db = _db_for_body_sync(bio_weight_kg=87.09)
    assert sync_router._whoop_biometrics_weight_kg_missing(db, "athlete-1", date(2026, 5, 21)) is False


def test_whoop_local_date_from_iso_respects_offset():
    d = sync_router._whoop_local_date_from_iso("2026-05-21T10:00:00.000Z", offset_min=-240)
    assert d == date(2026, 5, 21)


def test_body_sync_always_upserts_weight_kg_not_athletes_weight():
    async def _run():
        db = _db_for_body_sync(have_height=True)
        athletes_tbl = db._athletes_tbl
        biometrics_tbl = db._biometrics_tbl

        with (
            patch.object(sync_router.whoop, "fetch_profile", new_callable=AsyncMock, return_value=WHOOP_PROFILE),
            patch.object(sync_router.whoop, "fetch_body_measurement", new_callable=AsyncMock, return_value=WHOOP_BODY),
        ):
            await sync_router._whoop_sync_whoop_body_measurements(
                "athlete-1",
                bio_date=date(2026, 5, 21),
                access_token="token",
                refresh_token=None,
                external_user_id="ext-1",
                db=db,
            )

        biometrics_tbl.upsert.assert_called_once()
        upsert_payload = biometrics_tbl.upsert.call_args[0][0]
        assert upsert_payload["weight_kg"] == 87.09
        assert "height_cm" not in upsert_payload
        athletes_tbl.update.assert_not_called()

    asyncio.run(_run())


def test_body_sync_fills_height_when_missing():
    async def _run():
        db = _db_for_body_sync(have_height=False)
        athletes_tbl = db._athletes_tbl
        biometrics_tbl = db._biometrics_tbl

        with (
            patch.object(sync_router.whoop, "fetch_profile", new_callable=AsyncMock, return_value=WHOOP_PROFILE),
            patch.object(sync_router.whoop, "fetch_body_measurement", new_callable=AsyncMock, return_value=WHOOP_BODY),
        ):
            await sync_router._whoop_sync_whoop_body_measurements(
                "athlete-1",
                bio_date=date(2026, 5, 21),
                access_token="token",
                refresh_token=None,
                external_user_id="ext-1",
                db=db,
            )

        athletes_tbl.update.assert_called_once()
        assert athletes_tbl.update.call_args[0][0] == {"height_cm": 185.4}
        upsert_payload = biometrics_tbl.upsert.call_args[0][0]
        assert upsert_payload["weight_kg"] == 87.09
        assert upsert_payload["height_cm"] == 185.4

    asyncio.run(_run())


def test_body_sync_skips_weight_kg_when_disabled():
    async def _run():
        db = _db_for_body_sync(have_height=True)
        biometrics_tbl = db._biometrics_tbl

        with (
            patch.object(sync_router.whoop, "fetch_profile", new_callable=AsyncMock, return_value=WHOOP_PROFILE),
            patch.object(sync_router.whoop, "fetch_body_measurement", new_callable=AsyncMock, return_value=WHOOP_BODY),
        ):
            await sync_router._whoop_sync_whoop_body_measurements(
                "athlete-1",
                bio_date=date(2026, 5, 21),
                access_token="token",
                refresh_token=None,
                external_user_id="ext-1",
                db=db,
                sync_weight_kg=False,
            )

        biometrics_tbl.upsert.assert_not_called()

    asyncio.run(_run())
