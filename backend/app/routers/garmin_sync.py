"""Garmin Connect sync routes: credential-based connect (with MFA), backfill.

Mounted at the same ``/v1/sync`` prefix as ``sync.py``. Garmin has no
consumer-facing OAuth (see ``docs/GARMIN_INTEGRATION.md``), so this mirrors
the intervals.icu API-key connect flow — an in-app credential form — rather
than the Strava/WHOOP OAuth-redirect flow.

Split into its own router (rather than added to the already-1700+ line
``sync.py``) to keep the Garmin surface area easy to find and review.
"""
from __future__ import annotations

import asyncio
import logging

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException
from pydantic import BaseModel, Field

from app.config import settings
from app.dependencies import get_current_athlete, get_admin_db
from app.services import garmin as garmin_service

logger = logging.getLogger(__name__)

router = APIRouter(prefix=f"{settings.API_PREFIX}/sync", tags=["Sync & Webhooks"])


class GarminConnectPayload(BaseModel):
    username: str = Field(..., min_length=1, max_length=254)
    password: str = Field(..., min_length=1, max_length=512)
    days: int = Field(default=90, ge=1, le=365)


class GarminMfaPayload(BaseModel):
    state_token: str = Field(..., min_length=1, max_length=128)
    mfa_code: str = Field(..., min_length=1, max_length=20)
    days: int = Field(default=90, ge=1, le=365)


def _schedule_backfill(
    background_tasks: BackgroundTasks | None, athlete_id: str, db, days: int
) -> None:
    if background_tasks is not None:
        background_tasks.add_task(
            garmin_service.backfill_historical_data, athlete_id, db, days
        )
    else:
        asyncio.create_task(garmin_service.backfill_historical_data(athlete_id, db, days))


def _persist_and_schedule(
    client, athlete_id: str, admin_db, background_tasks: BackgroundTasks, days: int
) -> dict:
    # Garmin's login flow (via garminconnect/garth) doesn't hand back a
    # stable numeric account id the way Strava/WHOOP's OAuth token exchange
    # does; the account's display name is unique and stable, so use that for
    # the webhook-owner-lookup column other providers populate.
    external_user_id = getattr(client, "display_name", None)
    garmin_service.persist_session(admin_db, athlete_id, client, external_user_id)
    _schedule_backfill(background_tasks, athlete_id, admin_db, days)
    return {
        "status": "success",
        "provider": garmin_service.PROVIDER,
        "connected": True,
        "scheduled": True,
        "days": days,
    }


@router.post("/garmin/connect")
async def garmin_connect(
    payload: GarminConnectPayload,
    background_tasks: BackgroundTasks,
    athlete_id: str = Depends(get_current_athlete),
    admin_db=Depends(get_admin_db),
):
    """
    Connect Garmin with the athlete's own username/password.

    Garmin has no self-serve OAuth (see ``docs/GARMIN_INTEGRATION.md``); this
    logs in via the community ``garminconnect`` library and persists only the
    resulting session token — never the password. If the account has MFA
    enabled, returns ``{mfa_required: true, state_token}`` instead of
    connecting; resume with ``POST /garmin/connect/mfa``.
    """
    try:
        # garminconnect is a synchronous (requests/curl_cffi) client.
        client = await asyncio.to_thread(
            garmin_service.login, payload.username, payload.password
        )
    except garmin_service.GarminMfaRequired as exc:
        return {"status": "mfa_required", "mfa_required": True, "state_token": exc.state_token}
    except garmin_service.GarminRateLimitedError as exc:
        raise HTTPException(
            status_code=429, detail=str(exc) or "Garmin rate limit; try again later"
        )
    except garmin_service.GarminAuthError as exc:
        raise HTTPException(
            status_code=401, detail=str(exc) or "Garmin authentication failed"
        )
    except Exception as exc:
        # Log the real exception server-side, but don't hand an arbitrary/
        # unexpected exception's message to the client — unlike the typed
        # errors above (whose messages we control), this branch can catch
        # anything, including internals we don't want to leak.
        logger.warning("garmin_connect failed athlete_id=%s: %s", athlete_id, exc)
        raise HTTPException(status_code=502, detail="Garmin connect failed")

    return _persist_and_schedule(client, athlete_id, admin_db, background_tasks, payload.days)


@router.post("/garmin/connect/mfa")
async def garmin_connect_mfa(
    payload: GarminMfaPayload,
    background_tasks: BackgroundTasks,
    athlete_id: str = Depends(get_current_athlete),
    admin_db=Depends(get_admin_db),
):
    """
    Complete a Garmin login that returned ``mfa_required``.

    Must be called against the same backend process that returned the
    ``state_token`` — see the MFA session note in ``app/services/garmin.py``.
    """
    try:
        client = await asyncio.to_thread(
            garmin_service.resume_mfa, payload.state_token, payload.mfa_code
        )
    except garmin_service.GarminRateLimitedError as exc:
        raise HTTPException(
            status_code=429, detail=str(exc) or "Garmin rate limit; try again later"
        )
    except garmin_service.GarminAuthError as exc:
        raise HTTPException(
            status_code=401, detail=str(exc) or "Garmin MFA verification failed"
        )
    except Exception as exc:
        # See the equivalent comment in garmin_connect() above.
        logger.warning("garmin_connect_mfa failed athlete_id=%s: %s", athlete_id, exc)
        raise HTTPException(status_code=502, detail="Garmin MFA failed")

    return _persist_and_schedule(client, athlete_id, admin_db, background_tasks, payload.days)


@router.post("/garmin/backfill")
async def garmin_backfill_now(
    days: int = 90,
    athlete_id: str = Depends(get_current_athlete),
    admin_db=Depends(get_admin_db),
):
    """Manually trigger a Garmin backfill for the authenticated athlete."""
    d = max(1, min(int(days), 365))
    client = await asyncio.to_thread(
        garmin_service.get_client_for_athlete, athlete_id, admin_db
    )
    if client is None:
        raise HTTPException(
            status_code=400, detail="Garmin not connected — try reconnecting Garmin"
        )

    asyncio.create_task(garmin_service.backfill_historical_data(athlete_id, admin_db, d))
    return {"status": "success", "scheduled": True, "days": d}
