"""Offline geocoding (US ZIP centroids from the `zipcodes` package) and distance math.

The live ClinicalTrials.gov API returns site coordinates (`geoPoint`), which are preferred.
ZIP centroids are a fallback for snapshot data and for the patient's own location, so the
patient's address never has to be sent to a third-party geocoder.
"""

from __future__ import annotations

import math
from functools import lru_cache

import zipcodes

US_NAMES = {"united states", "usa", "us", "united states of america"}


@lru_cache(maxsize=20000)
def zip_centroid(postal_code: str | None) -> tuple[float, float] | None:
    if not postal_code:
        return None
    z = postal_code.strip()[:5]
    if len(z) != 5 or not z.isdigit():
        return None
    try:
        rows = zipcodes.matching(z)
    except (ValueError, TypeError):
        return None
    if not rows:
        return None
    try:
        return float(rows[0]["lat"]), float(rows[0]["long"])
    except (KeyError, ValueError):
        return None


@lru_cache(maxsize=5000)
def city_centroid(city: str | None, state: str | None) -> tuple[float, float] | None:
    if not city or not state:
        return None
    st = state.strip()
    if len(st) != 2:
        st = _STATE_ABBR.get(st.lower(), st)
    try:
        rows = zipcodes.filter_by(city=city.strip().title(), state=st.upper())
    except Exception:  # noqa: BLE001 - library raises various errors on bad input
        return None
    pts = [(float(r["lat"]), float(r["long"])) for r in rows if r.get("lat") and r.get("long")]
    if not pts:
        return None
    return sum(p[0] for p in pts) / len(pts), sum(p[1] for p in pts) / len(pts)


def lookup_zip(postal_code: str) -> dict | None:
    try:
        rows = zipcodes.matching(postal_code.strip()[:5])
    except (ValueError, TypeError):
        return None
    if not rows:
        return None
    r = rows[0]
    return {"city": r["city"].title(), "state": r["state"], "latitude": float(r["lat"]), "longitude": float(r["long"])}


def haversine_miles(a: tuple[float, float], b: tuple[float, float]) -> float:
    lat1, lon1, lat2, lon2 = map(math.radians, (a[0], a[1], b[0], b[1]))
    h = math.sin((lat2 - lat1) / 2) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin((lon2 - lon1) / 2) ** 2
    return 3958.8 * 2 * math.asin(math.sqrt(h))


_STATE_ABBR = {
    "alabama": "AL", "alaska": "AK", "arizona": "AZ", "arkansas": "AR", "california": "CA", "colorado": "CO",
    "connecticut": "CT", "delaware": "DE", "district of columbia": "DC", "florida": "FL", "georgia": "GA",
    "hawaii": "HI", "idaho": "ID", "illinois": "IL", "indiana": "IN", "iowa": "IA", "kansas": "KS",
    "kentucky": "KY", "louisiana": "LA", "maine": "ME", "maryland": "MD", "massachusetts": "MA",
    "michigan": "MI", "minnesota": "MN", "mississippi": "MS", "missouri": "MO", "montana": "MT",
    "nebraska": "NE", "nevada": "NV", "new hampshire": "NH", "new jersey": "NJ", "new mexico": "NM",
    "new york": "NY", "north carolina": "NC", "north dakota": "ND", "ohio": "OH", "oklahoma": "OK",
    "oregon": "OR", "pennsylvania": "PA", "rhode island": "RI", "south carolina": "SC", "south dakota": "SD",
    "tennessee": "TN", "texas": "TX", "utah": "UT", "vermont": "VT", "virginia": "VA", "washington": "WA",
    "west virginia": "WV", "wisconsin": "WI", "wyoming": "WY", "puerto rico": "PR",
}


def fill_location_geo(loc) -> None:
    """Populate lat/lon on a LocationRecord from ZIP/city when the registry did not supply it."""
    if loc.latitude is not None and loc.longitude is not None:
        loc.geo_source = loc.geo_source or "registry"
        return
    if (loc.country or "").strip().lower() not in US_NAMES:
        return
    pt = zip_centroid(loc.postal_code) or city_centroid(loc.city, loc.state)
    if pt:
        loc.latitude, loc.longitude = pt
        loc.geo_source = "postal_centroid"
