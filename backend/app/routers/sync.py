from fastapi import APIRouter, Request, Response, HTTPException, Depends
from fastapi.responses import RedirectResponse
from app.dependencies import get_current_athlete, get_db

router = APIRouter(prefix="/v1/sync", tags=["Sync & Webhooks"])

@router.post("/garmin/webhook")
async def garmin_webhook(request: Request):
    """Webhook receiver for Garmin Connect push notifications."""
    signature = request.headers.get("X-Garmin-Signature")
    if not signature:
        raise HTTPException(status_code=401, detail="Missing Garmin signature")
    
    # Signature validation and payload parsing logic goes here
    # Garmin requires a quick 200 OK response within 5 seconds
    return Response(status_code=200)

@router.post("/whoop/webhook")
async def whoop_webhook(request: Request):
    """Webhook receiver for WHOOP data push events."""
    signature = request.headers.get("X-WHOOP-Signature")
    if not signature:
        raise HTTPException(status_code=401, detail="Missing WHOOP signature")
        
    return Response(status_code=200)

@router.get("/oauth/garmin/authorize")
async def garmin_oauth_authorize():
    """Initiates the Garmin OAuth 2.0 authorization flow."""
    # Logic to generate OAuth URL
    garmin_auth_url = "https://connect.garmin.com/oauthConfirm?oauth_token=PLACEHOLDER"
    return RedirectResponse(url=garmin_auth_url)

@router.get("/oauth/garmin/callback")
async def garmin_oauth_callback(code: str, state: str):
    """OAuth callback handler. Exchanges auth code for tokens."""
    # Logic to exchange `code` for access/refresh tokens and store in `oauth_tokens` table
    mobile_deep_link = "astrape://connected?provider=garmin"
    return RedirectResponse(url=mobile_deep_link)

@router.get("/oauth/whoop/authorize")
async def whoop_oauth_authorize():
    """Initiates the WHOOP OAuth 2.0 authorization flow."""
    whoop_auth_url = "https://api.prod.whoop.com/oauth/oauth2/auth?response_type=code&client_id=PLACEHOLDER"
    return RedirectResponse(url=whoop_auth_url)

@router.get("/oauth/whoop/callback")
async def whoop_oauth_callback(code: str, state: str):
    """WHOOP OAuth callback handler."""
    mobile_deep_link = "astrape://connected?provider=whoop"
    return RedirectResponse(url=mobile_deep_link)

@router.get("/status")
async def get_sync_status(athlete_id: str = Depends(get_current_athlete), db = Depends(get_db)):
    """Returns connection status for all configured integrations."""
    # Checks the `oauth_tokens` table
    return {
        "integrations": {
            "garmin": {
                "connected": True,
                "last_sync": "2026-04-26T10:14:00Z",
                "token_expires": "2026-04-26T12:14:00Z"
            },
            "whoop": {
                "connected": False,
                "last_sync": None
            },
            "healthkit": {
                "connected": True,
                "last_sync": "2026-04-26T06:12:00Z",
                "background_refresh": True
            }
        }
    }