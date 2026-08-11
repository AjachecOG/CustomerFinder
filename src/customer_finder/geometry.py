"""Geographic helpers: bounding box prefilter and exact haversine radius."""

from __future__ import annotations

import math
from dataclasses import dataclass

from customer_finder.errors import ArgumentError

_EARTH_RADIUS_M = 6_371_000.0
_KM_PER_DEG_LAT = 111.32
_BBOX_MARGIN = 1.01


@dataclass(frozen=True, slots=True)
class BBox:
    """Axis-aligned prefilter box in lon/lat degrees."""

    xmin: float
    xmax: float
    ymin: float
    ymax: float

    def contains(self, lat: float, lon: float) -> bool:
        return self.xmin <= lon <= self.xmax and self.ymin <= lat <= self.ymax


def haversine_m(lat1: float, lon1: float, lat2: float, lon2: float) -> int:
    """Great-circle distance in whole metres between two WGS84 points."""
    for name, value in (
        ("lat1", lat1),
        ("lat2", lat2),
        ("lon1", lon1),
        ("lon2", lon2),
    ):
        if name.startswith("lat") and not -90.0 <= value <= 90.0:
            raise ArgumentError(f"Invalid latitude {name}={value}")
        if name.startswith("lon") and not -180.0 <= value <= 180.0:
            raise ArgumentError(f"Invalid longitude {name}={value}")

    phi1 = math.radians(lat1)
    phi2 = math.radians(lat2)
    d_phi = math.radians(lat2 - lat1)
    d_lambda = math.radians(lon2 - lon1)
    a = math.sin(d_phi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(d_lambda / 2) ** 2
    c = 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))
    return round(_EARTH_RADIUS_M * c)


def compute_bbox(lat: float, lon: float, radius_km: float) -> BBox:
    """Compute a slightly padded bbox around a circle (Poland MVP, no antimeridian)."""
    if not -90.0 < lat < 90.0:
        raise ArgumentError(f"Invalid center latitude: {lat}")
    if not -180.0 <= lon <= 180.0:
        raise ArgumentError(f"Invalid center longitude: {lon}")
    if radius_km <= 0:
        raise ArgumentError(f"radius_km must be positive, got {radius_km}")

    cos_lat = math.cos(math.radians(lat))
    if abs(cos_lat) < 1e-12:
        raise ArgumentError("Cannot compute bbox near the poles")

    lat_delta = _BBOX_MARGIN * radius_km / _KM_PER_DEG_LAT
    lon_delta = _BBOX_MARGIN * radius_km / (_KM_PER_DEG_LAT * cos_lat)
    bbox = BBox(
        xmin=lon - lon_delta,
        xmax=lon + lon_delta,
        ymin=lat - lat_delta,
        ymax=lat + lat_delta,
    )
    if not (-180.0 <= bbox.xmin < bbox.xmax <= 180.0):
        raise ArgumentError(f"Impossible bbox longitude span: {bbox}")
    if not (-90.0 <= bbox.ymin < bbox.ymax <= 90.0):
        raise ArgumentError(f"Impossible bbox latitude span: {bbox}")
    return bbox


def within_radius_m(
    center_lat: float,
    center_lon: float,
    point_lat: float,
    point_lon: float,
    radius_km: float,
) -> tuple[bool, int]:
    """Return (inside, distance_m) for an exact circular filter."""
    distance_m = haversine_m(center_lat, center_lon, point_lat, point_lon)
    limit_m = round(radius_km * 1000)
    return distance_m <= limit_m, distance_m
