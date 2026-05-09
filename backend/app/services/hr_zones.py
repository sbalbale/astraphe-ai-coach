"""
Canonical HR zone calculation for Astrape.

Priority:
  1. Coggan LTHR  (threshold_hr > 0 AND threshold_hr_source == 'manual')
  2. Karvonen HRR (max_hr + resting_hr set)
  3. Max HR %     (max_hr only)

All public functions return a consistent ZoneResult with a `method` field
so callers can surface which method was used in the UI.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal, Optional

ZoneMethod = Literal["lthr", "hrr", "max_hr"]


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


def _lthr_zones(lthr: int) -> list[HRZone]:
    """Coggan-style 5-zone model anchored to lactate threshold HR (Z5 merges VO2max + anaerobic)."""
    return [
        HRZone(1, "Active Recovery", 0, int(lthr * 0.81)),
        HRZone(2, "Endurance", int(lthr * 0.81), int(lthr * 0.89)),
        HRZone(3, "Tempo", int(lthr * 0.89), int(lthr * 0.93)),
        HRZone(4, "Threshold", int(lthr * 0.93), int(lthr * 1.05)),
        HRZone(5, "VO2max+", int(lthr * 1.05), 999),
    ]


def _hrr_zones(max_hr: int, resting_hr: int) -> list[HRZone]:
    """Karvonen 5-zone model using heart rate reserve."""
    hrr = max_hr - resting_hr

    def z(pct: float) -> int:
        return int(resting_hr + hrr * pct)

    return [
        HRZone(1, "Recovery", z(0.50), z(0.60)),
        HRZone(2, "Aerobic", z(0.60), z(0.70)),
        HRZone(3, "Tempo", z(0.70), z(0.80)),
        HRZone(4, "Threshold", z(0.80), z(0.90)),
        HRZone(5, "VO2max", z(0.90), 999),
    ]


def _max_hr_zones(max_hr: int) -> list[HRZone]:
    """Simple 5-zone model as % of max HR. Least accurate, last resort."""
    return [
        HRZone(1, "Recovery", 0, int(max_hr * 0.60)),
        HRZone(2, "Aerobic", int(max_hr * 0.60), int(max_hr * 0.70)),
        HRZone(3, "Tempo", int(max_hr * 0.70), int(max_hr * 0.80)),
        HRZone(4, "Threshold", int(max_hr * 0.80), int(max_hr * 0.90)),
        HRZone(5, "VO2max", int(max_hr * 0.90), 999),
    ]


def compute_hr_zones(
    max_hr: Optional[int],
    resting_hr: Optional[int],
    threshold_hr: Optional[int],
    threshold_hr_source: Optional[str] = None,
) -> Optional[ZoneResult]:
    """
    Returns a ZoneResult using the most accurate method available,
    or None if there is insufficient data for any method.
    """
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
) -> dict[str, Any]:
    """JSON-friendly block for athlete profile API (method, anchor_label, zones)."""
    zr = compute_hr_zones(max_hr, resting_hr, threshold_hr, threshold_hr_source)
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
    )
    return out


def get_athlete_zones(athlete: dict) -> list[HRZone]:
    """
    Dispatches to compute_hr_zones using an athlete dict from the athletes table.
    Priority: lthr (manual) → hrr → max_hr_percent → default LTHR=170.
    Checks both 'lthr' and 'threshold_hr' columns for the LTHR value.
    """
    lthr = athlete.get("lthr") or athlete.get("threshold_hr")
    max_hr = athlete.get("max_hr")
    resting_hr = athlete.get("resting_hr")
    # Treat lthr/threshold_hr as manually confirmed for zone purposes
    threshold_hr_source = "manual" if lthr else athlete.get("threshold_hr_source")

    zr = compute_hr_zones(
        max_hr=max_hr,
        resting_hr=resting_hr,
        threshold_hr=lthr,
        threshold_hr_source=threshold_hr_source,
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
