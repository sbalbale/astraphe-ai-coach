"""Notification preferences (athletes.notification_settings).

Shape (v2, matches the Notification settings screen):
  {
    "v": 2,
    "types": {
      "debrief": {"on": true, "opt": "now",     "push": true},          # now | evening
      "plan":    {"on": true,                   "push": true, "email": false},
      "ready":   {"on": true, "opt": "07:00",   "push": true},          # 06:30 | 07:00 | 07:30 | 08:00
      "missed":  {"on": true, "opt": "morning", "push": true},          # morning | evening
      "weekly":  {"on": true, "opt": "Sun",     "push": true, "email": true},   # Sun | Mon
      "sync":    {"on": true,                   "push": true, "email": true}
    },
    "quiet": {"on": true, "from": "22:00", "to": "07:00"},
    "texts": "active" | "off"          # coach texts over Photon (being replaced by push)
  }

Email is stored but never sent: the app doesn't send notification email (yet). The old
flat booleans (readiness / coach / workouts / insights) are read as a fallback.
"""
from __future__ import annotations

import copy
from datetime import datetime, time
from typing import Any

TYPE_IDS = ("debrief", "plan", "ready", "missed", "weekly", "sync")

OPTIONS: dict[str, tuple[str, ...]] = {
    "debrief": ("now", "evening"),
    "ready": ("06:30", "07:00", "07:30", "08:00"),
    "missed": ("morning", "evening"),
    "weekly": ("Sun", "Mon"),
}

DEFAULTS: dict[str, Any] = {
    "v": 2,
    "types": {
        "debrief": {"on": True, "opt": "now", "push": True},
        "plan": {"on": True, "push": True, "email": False},
        "ready": {"on": True, "opt": "07:00", "push": True},
        "missed": {"on": True, "opt": "morning", "push": True},
        "weekly": {"on": True, "opt": "Sun", "push": True, "email": False},
        "sync": {"on": True, "push": True, "email": False},
    },
    "quiet": {"on": True, "from": "22:00", "to": "07:00"},
    "texts": "active",
}

# Old flat keys → the new types they stood for.
_LEGACY = {"readiness": ("ready",), "coach": ("debrief", "plan"), "workouts": ("missed",), "insights": ("weekly",)}


def _hhmm(v: Any, default: str) -> str:
    try:
        h, m = str(v).split(":")
        t = time(int(h), int(m))
        return f"{t.hour:02d}:{t.minute:02d}"
    except (ValueError, TypeError):
        return default


def effective(raw: Any) -> dict:
    """Saved settings merged over the defaults (unknown keys and bad values ignored)."""
    out = copy.deepcopy(DEFAULTS)
    saved = raw if isinstance(raw, dict) else {}
    for legacy, ids in _LEGACY.items():
        if isinstance(saved.get(legacy), bool):
            for i in ids:
                out["types"][i]["on"] = saved[legacy]
    for tid, val in (saved.get("types") or {}).items():
        if tid not in out["types"] or not isinstance(val, dict):
            continue
        cur = out["types"][tid]
        for k in ("on", "push", "email"):
            if isinstance(val.get(k), bool):
                cur[k] = val[k]
        if tid in OPTIONS and val.get("opt") in OPTIONS[tid]:
            cur["opt"] = val["opt"]
    q = saved.get("quiet")
    if isinstance(q, dict):
        if isinstance(q.get("on"), bool):
            out["quiet"]["on"] = q["on"]
        out["quiet"]["from"] = _hhmm(q.get("from"), out["quiet"]["from"])
        out["quiet"]["to"] = _hhmm(q.get("to"), out["quiet"]["to"])
    if saved.get("texts") in ("active", "off"):
        out["texts"] = saved["texts"]
    return out


def push_enabled(prefs: dict, type_id: str) -> bool:
    t = prefs["types"].get(type_id)
    return bool(t and t.get("on") and t.get("push", True))


def option(prefs: dict, type_id: str) -> str | None:
    return prefs["types"].get(type_id, {}).get("opt")


def in_quiet_hours(prefs: dict, local_now: datetime) -> bool:
    """Quiet hours may wrap midnight (22:00 → 07:00)."""
    q = prefs.get("quiet") or {}
    if not q.get("on"):
        return False
    start = _hhmm(q.get("from"), "22:00")
    end = _hhmm(q.get("to"), "07:00")
    now = f"{local_now.hour:02d}:{local_now.minute:02d}"
    if start == end:
        return False
    if start < end:
        return start <= now < end
    return now >= start or now < end


def legacy_type_enabled(raw: Any, notification_type: str) -> bool:
    """For pushes still sent with the old type names ('coach' = a chat reply finished, etc.).
    Old names map onto the v2 types they stood for (saved settings only keep the v2 shape):
    on while any of those types still has push on, so 'coach' goes quiet once both coach
    types (debrief and plan changes) are off."""
    prefs = effective(raw)
    if notification_type in TYPE_IDS:
        return push_enabled(prefs, notification_type)
    if notification_type in _LEGACY:
        return any(push_enabled(prefs, t) for t in _LEGACY[notification_type])
    saved = raw if isinstance(raw, dict) else {}
    v = saved.get(notification_type)
    return v if isinstance(v, bool) else True
