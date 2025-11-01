# tools/routes.py
from __future__ import annotations

import asyncio
import os
from typing import Any, Dict, Optional, Sequence, Tuple

import httpx

# Read the key from environment only (do NOT hardcode)
GOOGLE_MAPS_API_KEY = os.environ.get("GOOGLE_MAPS_API_KEY")
ROUTES_ENDPOINT = "https://routes.googleapis.com/directions/v2:computeRoutes"

class RoutesAPIError(Exception):
    """Raised when the Routes API returns an error."""

def _latlng(lat: float, lng: float) -> Dict[str, Any]:
    return {"location": {"latLng": {"latitude": float(lat), "longitude": float(lng)}}}

def _duration_to_seconds(proto_duration: str) -> int:
    # Duration strings look like "123s" or "3.5s"
    s = proto_duration.strip().rstrip("s")
    try:
        return int(float(s))
    except ValueError:
        return 0

async def compute_route(
    origin: Tuple[float, float],
    waypoints: Sequence[Tuple[float, float]] = (),
    destination: Optional[Tuple[float, float]] = None,
    *,
    travel_mode: str = "DRIVE",                 # DRIVE | BICYCLE | WALK | TWO_WHEELER | TRANSIT
    routing_preference: str = "TRAFFIC_AWARE",  # TRAFFIC_AWARE | TRAFFIC_AWARE_OPTIMAL | TRAFFIC_UNAWARE
    optimize_waypoint_order: bool = False,
    polyline_quality: str = "OVERVIEW",         # OVERVIEW | HIGH_QUALITY
    polyline_encoding: str = "ENCODED_POLYLINE",# ENCODED_POLYLINE | GEO_JSON_LINESTRING
    timeout_s: int = 20,
) -> Dict[str, Any]:
    """
    Compute a daily route with optional waypoint optimization and return:
    {
      "distance_m": int,
      "duration_s": int,
      "polyline": str,                 # encoded polyline
      "legs": [ ... ],                 # raw legs from API
      "optimized_order": List[int]     # mapping for intermediates (empty if not optimized)
    }
    """
    if not GOOGLE_MAPS_API_KEY:
        raise RoutesAPIError("GOOGLE_MAPS_API_KEY is not set")

    if destination is None:
        # If no explicit destination, use last waypoint as destination and drop from intermediates
        if not waypoints:
            raise RoutesAPIError("destination or at least one waypoint is required")
        destination = waypoints[-1]
        waypoints = waypoints[:-1]

    # Build request body
    body: Dict[str, Any] = {
        "origin": _latlng(*origin),
        "destination": _latlng(*destination),
        "travelMode": travel_mode,
        "routingPreference": routing_preference,
        "polylineQuality": polyline_quality,
        "polylineEncoding": polyline_encoding,
    }
    if waypoints:
        body["intermediates"] = [_latlng(*p) for p in waypoints]
    if optimize_waypoint_order:
        body["optimizeWaypointOrder"] = True

    # Field mask is REQUIRED for Routes API responses.
    # Keep it minimal for performance and cost.
    fieldmask_parts = [
        "routes.distanceMeters",
        "routes.duration",
        "routes.polyline.encodedPolyline",
        "routes.legs",
    ]
    # If optimizing, you MUST request optimizedIntermediateWaypointIndex
    if optimize_waypoint_order:
        fieldmask_parts.append("routes.optimizedIntermediateWaypointIndex")
    fieldmask = ",".join(fieldmask_parts)

    headers = {
        "Content-Type": "application/json",
        "X-Goog-Api-Key": GOOGLE_MAPS_API_KEY,
        "X-Goog-FieldMask": fieldmask,
    }

    try:
        async with httpx.AsyncClient(timeout=timeout_s) as client:
            resp = await client.post(ROUTES_ENDPOINT, headers=headers, json=body)
            # Print short diagnostic on failure
            if resp.status_code >= 400:
                snippet = resp.text[:800]
                raise RoutesAPIError(f"Routes API {resp.status_code}: {snippet}")
            data = resp.json()
    except httpx.HTTPError as e:
        raise RoutesAPIError(f"HTTP error calling Routes API: {e}") from e

    routes = data.get("routes", [])
    if not routes:
        raise RoutesAPIError("No route returned")

    route = routes[0]
    distance_m = int(route.get("distanceMeters", 0))
    duration_s = _duration_to_seconds(route.get("duration", "0s"))
    polyline = (route.get("polyline") or {}).get("encodedPolyline", "")
    legs = route.get("legs", [])
    optimized_order = route.get("optimizedIntermediateWaypointIndex", []) or []

    return {
        "distance_m": distance_m,
        "duration_s": duration_s,
        "polyline": polyline,
        "legs": legs,
        "optimized_order": optimized_order,
    }

def compute_route_sync(*args, **kwargs) -> Dict[str, Any]:
    """Synchronous helper for environments without an event loop."""
    return asyncio.run(compute_route(*args, **kwargs))
