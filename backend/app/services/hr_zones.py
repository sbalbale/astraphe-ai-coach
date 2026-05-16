"""
Canonical HR zone calculation for Astrape.

Priority (when `hr_zone_method` is not set on the athlete):
  1. Coggan LTHR  (threshold_hr > 0 AND threshold_hr_source == 'manual')
  2. Karvonen HRR (max_hr + resting_hr set)
  3. Max HR %     (max_hr only)

When `hr_zone_method` is set (lthr | hrr | max_hr), that method is used if inputs allow,
otherwise falls back to the automatic priority above.

All public functions return a consistent ZoneResult with a `method` field
so callers can surface which method was used in the UI.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal, Optional

ZoneMethod = Literal["lthr", "hrr", "max_hr"]

VALID_ZONE_METHODS = frozenset({"lthr", "hrr", "max_hr"})
METHOD_ALIASES = {"max_hr_percent": "max_hr"}


def canonical_hr_zone_method(raw: object) -> str:
    """Normalize a non-empty client value to lthr|hrr|max_hr."""
    s = str(raw).strip().lower()
    if not s:
        raise ValueError("hr_zone_method must be lthr, hrr, or max_hr")
    m = METHOD_ALIASES.get(s, s)
    if m not in VALID_ZONE_METHODS:
        raise ValueError("hr_zone_method must be lthr, hrr, or max_hr")
    return m


def optional_canonical_hr_zone_method(raw: Optional[object]) -> Optional[str]:
    """None or blank -> None. Otherwise same as canonical_hr_zone_method."""
    if raw is None:
        return None
    s = str(raw).strip().lower()
    if not s:
        return None
    return canonical_hr_zone_method(s)


@dataclass
class HRZone:
    zone: int
    name: str
    min_bpm: int
    max_bpm: int


@dataclass
class ZoneResult:
    method: ZoneMethod
    zones: list[HRZone]
    anchor_label: str


# Display names are shared with the mobile app (`mobile/src/lib/hrZoneDisplay.ts`).
HR_ZONE_STANDARD_NAMES: tuple[str, ...] = (
    "Recovery",  # Z1
    "Endurance",
    "Tempo",
    "Threshold",
    "VO2max+",  # Z5
)


def _lthr_zones(lthr: int) -> list[HRZone]:
    """Coggan-style 5-zone model anchored to lactate threshold HR (Z5 merges VO2max + anaerobic)."""
    names = HR_ZONE_STANDARD_NAMES
    return [
        HRZone(1, names[0], 0, int(lthr * 0.81)),
        HRZone(2, names[1], int(lthr * 0.81), int(lthr * 0.89)),
        HRZone(3, names[2], int(lthr * 0.89), int(lthr * 0.93)),
        HRZone(4, names[3], int(lthr * 0.93), int(lthr * 1.05)),
        HRZone(5, names[4], int(lthr * 1.05), 999),
    ]


def _hrr_zones(max_hr: int, resting_hr: int) -> list[HRZone]:
    """Karvonen 5-zone model using heart rate reserve."""
    hrr = max_hr - resting_hr

    def z(pct: float) -> int:
        return int(resting_hr + hrr * pct)

    names = HR_ZONE_STANDARD_NAMES

    return [
        HRZone(1, names[0], 0, z(0.60)),
        HRZone(2, names[1], z(0.60), z(0.70)),
        HRZone(3, names[2], z(0.70), z(0.80)),
        HRZone(4, names[3], z(0.80), z(0.90)),
        HRZone(5, names[4], z(0.90), 999),
    ]


def _max_hr_zones(max_hr: int) -> list[HRZone]:
    """Simple 5-zone model as % of max HR. Least accurate, last resort."""
    names = HR_ZONE_STANDARD_NAMES
    return [
        HRZone(1, names[0], 0, int(max_hr * 0.60)),
        HRZone(2, names[1], int(max_hr * 0.60), int(max_hr * 0.70)),
        HRZone(3, names[2], int(max_hr * 0.70), int(max_hr * 0.80)),
        HRZone(4, names[3], int(max_hr * 0.80), int(max_hr * 0.90)),
        HRZone(5, names[4], int(max_hr * 0.90), 999),
    ]


def _compute_hr_zones_auto(
    max_hr: Optional[int],
    resting_hr: Optional[int],
    threshold_hr: Optional[int],
    threshold_hr_source: Optional[str] = None,
) -> Optional[ZoneResult]:
    """Automatic tier: manual LTHR -> HRR -> % max."""
    lthr_confirmed = bool(
        threshold_hr
        and threshold_hr > 0
        and threshold_hr_source == "manual"
    )
    if lthr_confirmed:
        return ZoneResult(
            method="lthr",
            zones=_lthr_zones(int(threshold_hr)),
            anchor_label=f"LTHR {int(threshold_hr)} bpm",
        )
    if max_hr and resting_hr and max_hr > resting_hr > 0:
        return ZoneResult(
            method="hrr",
            zones=_hrr_zones(int(max_hr), int(resting_hr)),
            anchor_label=f"Max HR {int(max_hr)} / RHR {int(resting_hr)} bpm",
        )
    if max_hr and max_hr > 0:
        return ZoneResult(
            method="max_hr",
            zones=_max_hr_zones(int(max_hr)),
            anchor_label=f"Max HR {int(max_hr)} bpm",
        )
    return None


def compute_hr_zones(
    max_hr: Optional[int],
    resting_hr: Optional[int],
    threshold_hr: Optional[int],
    threshold_hr_source: Optional[str] = None,
    hr_zone_method: Optional[str] = None,
) -> Optional[ZoneResult]:
    """
    Returns a ZoneResult using the athlete's preferred method when set and valid,
    else the automatic priority chain, or None if insufficient data for any method.
    """
    pref: Optional[str] = None
    if hr_zone_method is not None and str(hr_zone_method).strip() != "":
        try:
            pref = optional_canonical_hr_zone_method(hr_zone_method)
        except ValueError:
            pref = None

    if pref == "lthr":
        if threshold_hr and int(threshold_hr) > 0:
            thr = int(threshold_hr)
            return ZoneResult(
                method="lthr",
                zones=_lthr_zones(thr),
                anchor_label=f"LTHR {thr} bpm",
            )
    elif pref == "hrr":
        if max_hr and resting_hr and max_hr > resting_hr > 0:
            return ZoneResult(
                method="hrr",
                zones=_hrr_zones(int(max_hr), int(resting_hr)),
                anchor_label=f"Max HR {int(max_hr)} / RHR {int(resting_hr)} bpm",
            )
    elif pref == "max_hr":
        if max_hr and max_hr > 0:
            return ZoneResult(
                method="max_hr",
                zones=_max_hr_zones(int(max_hr)),
                anchor_label=f"Max HR {int(max_hr)} bpm",
            )

    return _compute_hr_zones_auto(max_hr, resting_hr, threshold_hr, threshold_hr_source)


def classify_hr(bpm: int, zone_result: ZoneResult) -> Optional[int]:
    """Returns the zone number (1–5) for a given heart rate; each zone is [min_bpm, max_bpm)."""
    for z in zone_result.zones:
        if z.min_bpm <= bpm < z.max_bpm:
            return z.zone
    return None


def profile_hr_zones_payload(
    max_hr: Optional[int],
    resting_hr: Optional[int],
    threshold_hr: Optional[int],
    threshold_hr_source: Optional[str] = None,
    hr_zone_method: Optional[str] = None,
) -> dict[str, Any]:
    """JSON-friendly block for athlete profile API (method, anchor_label, zones)."""
    zr = compute_hr_zones(
        max_hr,
        resting_hr,
        threshold_hr,
        threshold_hr_source,
        hr_zone_method=hr_zone_method,
    )
    if zr is None:
        return {"method": None, "anchor_label": None, "zones": []}
    return {
        "method": zr.method,
        "anchor_label": zr.anchor_label,
        "zones": [
            {"zone": z.zone, "name": z.name, "min": z.min_bpm, "max": z.max_bpm}
            for z in zr.zones
        ],
    }


def athlete_dict_with_hr_zones(row: dict[str, Any]) -> dict[str, Any]:
    """Shallow-copy athlete row and attach computed hr_zones."""
    out = dict(row)
    out["hr_zones"] = profile_hr_zones_payload(
        max_hr=row.get("max_hr"),
        resting_hr=row.get("resting_hr"),
        threshold_hr=row.get("threshold_hr"),
        threshold_hr_source=row.get("threshold_hr_source"),
        hr_zone_method=row.get("hr_zone_method"),
    )
    return out


def get_athlete_zones(athlete: dict) -> list[HRZone]:
    """
    Dispatches to compute_hr_zones using an athlete dict from the athletes table.
    Automatic fallback when unset: lthr (manual) → hrr → max_hr → default LTHR=170.
    """
    thr = athlete.get("lthr") or athlete.get("threshold_hr")
    zr = compute_hr_zones(
        max_hr=athlete.get("max_hr"),
        resting_hr=athlete.get("resting_hr"),
        threshold_hr=thr,
        threshold_hr_source=athlete.get("threshold_hr_source"),
        hr_zone_method=athlete.get("hr_zone_method"),
    )
    return zr.zones if zr else _lthr_zones(170)


def compute_zone_distribution(hr_stream: list[int], zones: list[HRZone]) -> dict:
    """
    Returns percent time spent in each zone from a raw 1-second HR array.
    e.g. {"Z1": 12.5, "Z2": 45.0, "Z3": 30.0, "Z4": 10.0, "Z5": 2.5}
    Uses z.zone (int) and z.min_bpm / z.max_bpm from the HRZone dataclass.
    """
    if not hr_stream:
        return {f"Z{z.zone}": 0.0 for z in zones}
    total = len(hr_stream)
    counts = {z.zone: 0 for z in zones}
    for hr in hr_stream:
        for zone in zones:
            if zone.min_bpm <= hr < zone.max_bpm:
                counts[zone.zone] += 1
                break
    return {f"Z{num}": round(count / total * 100, 1) for num, count in counts.items()}
