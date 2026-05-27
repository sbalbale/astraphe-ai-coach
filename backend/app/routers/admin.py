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


class MergeCoachMemoryDuplicatesRequest(BaseModel):
    athlete_id: str
    dry_run: bool = True
    # Safety limits: scan up to N newest rows for this athlete.
    max_scan: int = 1000
    # Delete in chunks to avoid URL/query limits.
    delete_chunk_size: int = 50

    @field_validator("max_scan", "delete_chunk_size")
    @classmethod
    def validate_positive_ints(cls, v: int) -> int:
        if v < 1:
            raise ValueError("Value must be >= 1")
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


def _normalize_memory_content_for_dedupe(text: str | None) -> str:
    # Conservative normalization: trim, collapse whitespace, casefold.
    # (Avoid aggressive punctuation stripping that might merge distinct facts.)
    s = (text or "").strip()
    s = " ".join(s.split())
    return s.casefold()


@router.post("/coach-memories/merge-duplicates")
def merge_coach_memory_duplicates(
    payload: MergeCoachMemoryDuplicatesRequest,
    _admin: dict = Depends(get_admin_user),
    admin_db: Client = Depends(get_admin_db),
):
    """
    One-off maintenance endpoint.

    Finds duplicates in `coach_memories` for a specific athlete by normalized `content`,
    keeps the newest row, and deletes the rest.

    Defaults to dry-run. Set dry_run=false to actually delete.
    """
    athlete_id = payload.athlete_id.strip()
    if not athlete_id:
        raise HTTPException(status_code=400, detail="athlete_id is required")

    max_scan = min(int(payload.max_scan), 10000)
    delete_chunk_size = min(int(payload.delete_chunk_size), 200)

    try:
        res = (
            admin_db.table("coach_memories")
            .select("id,content,created_at,updated_at")
            .eq("athlete_id", athlete_id)
            # Prefer updated_at if present; otherwise created_at
            .order("updated_at", desc=True)
            .limit(max_scan)
            .execute()
        )
        rows = res.data or []
    except Exception as e:
        # Some local schemas may not have updated_at; fall back to created_at ordering.
        try:
            res = (
                admin_db.table("coach_memories")
                .select("id,content,created_at")
                .eq("athlete_id", athlete_id)
                .order("created_at", desc=True)
                .limit(max_scan)
                .execute()
            )
            rows = res.data or []
        except Exception as e2:
            raise HTTPException(status_code=500, detail=f"Failed to load coach_memories: {str(e2)}") from e

    groups: dict[str, list[dict]] = {}
    for r in rows:
        key = _normalize_memory_content_for_dedupe(str(r.get("content") or ""))
        if not key:
            continue
        groups.setdefault(key, []).append(r)

    duplicates = {k: v for k, v in groups.items() if len(v) > 1}
    if not duplicates:
        return {
            "status": "success",
            "dry_run": payload.dry_run,
            "athlete_id": athlete_id,
            "scanned": len(rows),
            "duplicate_groups": 0,
            "would_delete": 0,
            "deleted": 0,
            "groups": [],
        }

    groups_out: list[dict] = []
    ids_to_delete: list[str] = []

    def _sort_key(r: dict) -> str:
        # ISO timestamps sort lexicographically.
        return str(r.get("updated_at") or r.get("created_at") or "")

    for key, items in duplicates.items():
        # Sort newest-first.
        items_sorted = sorted(items, key=_sort_key, reverse=True)
        keep = items_sorted[0]
        drop = items_sorted[1:]
        drop_ids = [str(d.get("id")) for d in drop if d.get("id")]
        ids_to_delete.extend(drop_ids)
        groups_out.append(
            {
                "content": keep.get("content"),
                "normalized_key": key,
                "keep_id": keep.get("id"),
                "drop_ids": drop_ids,
                "count": len(items_sorted),
            }
        )

    deleted = 0
    if not payload.dry_run and ids_to_delete:
        # Chunk deletes to keep requests small and reduce the blast radius if something fails.
        for i in range(0, len(ids_to_delete), delete_chunk_size):
            chunk = ids_to_delete[i : i + delete_chunk_size]
            if not chunk:
                continue
            try:
                admin_db.table("coach_memories").delete().in_("id", chunk).execute()
                deleted += len(chunk)
            except Exception as e:
                raise HTTPException(status_code=500, detail=f"Delete failed after deleting {deleted}: {str(e)}")

    return {
        "status": "success",
        "dry_run": payload.dry_run,
        "athlete_id": athlete_id,
        "scanned": len(rows),
        "duplicate_groups": len(groups_out),
        "would_delete": len(ids_to_delete),
        "deleted": deleted,
        "groups": groups_out[:200],  # cap response size
    }
