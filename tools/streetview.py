# tools/streetview.py
from __future__ import annotations

import urllib.parse
from typing import Any, Dict, Optional

import httpx

import config

GOOGLE_MAPS_API_KEY = config.get_google_maps_api_key()
SV_IMAGE_ENDPOINT = "https://maps.googleapis.com/maps/api/streetview"
SV_META_ENDPOINT  = "https://maps.googleapis.com/maps/api/streetview/metadata"

class StreetViewError(Exception):
    """Raised for Street View API errors or missing key."""

async def streetview_metadata(
    lat: float,
    lng: float,
    *,
    radius_m: Optional[int] = None,
    source: Optional[str] = None,  # e.g., "outdoor"
    timeout_s: int = 10,
) -> Dict[str, Any]:
    """
    Query Street View metadata near (lat,lng).
    Returns JSON with 'status' (OK|ZERO_RESULTS|NOT_FOUND) and pano info if available.
    """
    if not GOOGLE_MAPS_API_KEY:
        raise StreetViewError("GOOGLE_MAPS_API_KEY is not set")

    params = {
        "key": GOOGLE_MAPS_API_KEY,
        "location": f"{lat},{lng}",
    }
    if radius_m:
        params["radius"] = str(int(radius_m))
    if source:
        params["source"] = source

    async with httpx.AsyncClient(timeout=timeout_s) as client:
        r = await client.get(SV_META_ENDPOINT, params=params)
        if r.status_code >= 400:
            raise StreetViewError(f"Street View metadata {r.status_code}: {r.text[:400]}")
        return r.json()

def streetview_image_url(
    lat: float,
    lng: float,
    *,
    size: str = "640x400",
    heading: Optional[float] = None,  # camera compass direction
    pitch: int = 0,
    fov: int = 90,                    # 0–120; 90 is “normal”
    radius_m: Optional[int] = None,
    source: Optional[str] = None,     # "outdoor" hints outdoors-only
) -> str:
    """
    Build a Street View Static API image URL for (lat,lng).
    Return the URL as a string; render it server-side (don’t expose raw keys client-side).
    """
    if not GOOGLE_MAPS_API_KEY:
        raise StreetViewError("GOOGLE_MAPS_API_KEY is not set")

    q = {
        "key": GOOGLE_MAPS_API_KEY,
        "location": f"{lat},{lng}",
        "size": size,
        "pitch": str(int(pitch)),
        "fov": str(int(fov)),
    }
    if heading is not None:
        q["heading"] = str(float(heading))
    if radius_m:
        q["radius"] = str(int(radius_m))
    if source:
        q["source"] = source

    return f"{SV_IMAGE_ENDPOINT}?{urllib.parse.urlencode(q)}"

async def best_streetview_url_if_available(
    lat: float,
    lng: float,
    *,
    default_heading: Optional[float] = None,
    radius_m: int = 50,
    source: Optional[str] = None,
) -> Optional[str]:
    """
    Convenience helper: check metadata first; if a pano exists, return an image URL,
    else return None so callers can hide the tile or fall back to a standard photo.
    """
    meta = await streetview_metadata(lat, lng, radius_m=radius_m, source=source)
    if str(meta.get("status", "")).upper() == "OK":
        return streetview_image_url(lat, lng, heading=default_heading)
    return None
