from fastapi import APIRouter, HTTPException, Depends, Security
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from pydantic import BaseModel, field_validator
from typing import Optional
from supabase import Client

from app.dependencies import get_user_db, get_admin_db, VALID_TIERS, TIER_DEFAULTS

security = HTTPBearer()
router = APIRouter(prefix="/v1/admin", tags=["Admin"])


# ---------------------------------------------------------------------------
# Request model
# ---------------------------------------------------------------------------

class UserConfigUpdate(BaseModel):
    """All fields are optional — only provided fields are changed."""
    tier: Optional[str] = None
    gemini_model: Optional[str] = None          # empty string clears the override
    gemini_analysis_model: Optional[str] = None # empty string clears the override
    rate_limit_rpm: Optional[int] = None        # None = revert to tier default
    rate_limit_rph: Optional[int] = None        # None = revert to tier default
    is_admin: Optional[bool] = None

    @field_validator("tier")
    @classmethod
    def validate_tier(cls, v: Optional[str]) -> Optional[str]:
        if v is not None and v not in VALID_TIERS:
            raise ValueError(f"tier must be one of: {', '.join(sorted(VALID_TIERS))}")
        return v

    @field_validator("rate_limit_rpm", "rate_limit_rph")
    @classmethod
    def validate_positive(cls, v: Optional[int]) -> Optional[int]:
        if v is not None and v < 1:
            raise ValueError("Rate limits must be >= 1")
        return v


# ---------------------------------------------------------------------------
# Admin auth dependency
# ---------------------------------------------------------------------------

async def get_admin_user(
    credentials: HTTPAuthorizationCredentials = Security(security),
    db: Client = Depends(get_user_db),
) -> dict:
    """Verifies the caller has app_metadata.is_admin = true."""
    token = credentials.credentials
    try:
        user_res = db.auth.get_user(token)
        u = user_res.user
        app_meta = getattr(u, "app_metadata", None) or {}
        if not app_meta.get("is_admin"):
            raise HTTPException(status_code=403, detail="Admin access required")
        return {"user_id": u.id}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=401, detail=f"Authentication failed: {str(e)}")


# ---------------------------------------------------------------------------
# Formatting helper
# ---------------------------------------------------------------------------

def _format_user(u) -> dict:
    app_meta = getattr(u, "app_metadata", None) or {}
    user_meta = getattr(u, "user_metadata", None) or {}
    tier = str(app_meta.get("tier") or "free").strip().lower()
    defaults = TIER_DEFAULTS.get(tier, TIER_DEFAULTS["free"])
    return {
        "user_id": u.id,
        "email": getattr(u, "email", None),
        "created_at": str(getattr(u, "created_at", "")),
        "display_name": user_meta.get("full_name") or user_meta.get("name"),
        "config": {
            "tier": tier,
            "gemini_model": app_meta.get("gemini_model"),
            "gemini_analysis_model": app_meta.get("gemini_analysis_model"),
            "rate_limit_rpm": app_meta.get("rate_limit_rpm", defaults["rpm"]),
            "rate_limit_rph": app_meta.get("rate_limit_rph", defaults["rph"]),
            "is_admin": bool(app_meta.get("is_admin", False)),
        },
    }


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

@router.get("/users")
async def list_users(
    page: int = 1,
    per_page: int = 50,
    _admin: dict = Depends(get_admin_user),
    admin_db: Client = Depends(get_admin_db),
):
    """List all users with their config. Paginated (max 100 per page)."""
    per_page = max(1, min(per_page, 100))
    try:
        res = admin_db.auth.admin.list_users(page=page, per_page=per_page)
        users = res if isinstance(res, list) else getattr(res, "users", [])
        return {
            "status": "success",
            "page": page,
            "per_page": per_page,
            "users": [_format_user(u) for u in users],
        }
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to list users: {str(e)}")


@router.get("/users/{user_id}")
async def get_user(
    user_id: str,
    _admin: dict = Depends(get_admin_user),
    admin_db: Client = Depends(get_admin_db),
):
    """Get a single user's config."""
    try:
        res = admin_db.auth.admin.get_user_by_id(user_id)
        u = res.user if hasattr(res, "user") else res
        if not u:
            raise HTTPException(status_code=404, detail="User not found")
        return {"status": "success", "user": _format_user(u)}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to get user: {str(e)}")


@router.patch("/users/{user_id}")
async def update_user_config(
    user_id: str,
    payload: UserConfigUpdate,
    _admin: dict = Depends(get_admin_user),
    admin_db: Client = Depends(get_admin_db),
):
    """
    Update a user's admin-controlled config. Only the fields you provide are changed;
    everything else in app_metadata is preserved (Supabase merges, not replaces).

    To clear a model override and revert to the server default, pass an empty string:
        {"gemini_model": ""}

    To revert rate limits to the tier default, pass null:
        {"rate_limit_rpm": null}
    """
    update: dict = {}

    if payload.tier is not None:
        update["tier"] = payload.tier
    if payload.gemini_model is not None:
        # empty string -> null (removes per-user override, falls back to server default)
        update["gemini_model"] = payload.gemini_model.strip() or None
    if payload.gemini_analysis_model is not None:
        update["gemini_analysis_model"] = payload.gemini_analysis_model.strip() or None
    if payload.rate_limit_rpm is not None:
        update["rate_limit_rpm"] = payload.rate_limit_rpm
    if payload.rate_limit_rph is not None:
        update["rate_limit_rph"] = payload.rate_limit_rph
    if payload.is_admin is not None:
        update["is_admin"] = payload.is_admin

    if not update:
        raise HTTPException(status_code=400, detail="No fields provided")

    try:
        res = admin_db.auth.admin.update_user_by_id(user_id, {"app_metadata": update})
        u = res.user if hasattr(res, "user") else res
        return {"status": "success", "user": _format_user(u)}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to update user: {str(e)}")


@router.delete("/users/{user_id}/config/{field}")
async def clear_user_config_field(
    user_id: str,
    field: str,
    _admin: dict = Depends(get_admin_user),
    admin_db: Client = Depends(get_admin_db),
):
    """
    Clear a specific per-user override back to the tier default by setting it to null.
    Clearable fields: gemini_model, gemini_analysis_model, rate_limit_rpm, rate_limit_rph.
    """
    clearable = {"gemini_model", "gemini_analysis_model", "rate_limit_rpm", "rate_limit_rph"}
    if field not in clearable:
        raise HTTPException(
            status_code=400,
            detail=f"'{field}' is not clearable. Clearable fields: {', '.join(sorted(clearable))}",
        )
    try:
        admin_db.auth.admin.update_user_by_id(user_id, {"app_metadata": {field: None}})
        return {"status": "success", "cleared": field, "user_id": user_id}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to clear field: {str(e)}")
