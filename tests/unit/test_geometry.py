"""Unit tests for geometry helpers."""

from __future__ import annotations

import math

import pytest

from customer_finder.errors import ArgumentError
from customer_finder.geometry import compute_bbox, haversine_m, within_radius_m

# Wroclaw Rynek vs Glowny - local reference pair for haversine tolerance.
WROCLAW_RYNEK = (51.1095, 17.0325)
WROCLAW_GLOWNY = (51.0989, 17.0364)


def test_haversine_same_point_is_zero() -> None:
    assert haversine_m(51.1, 17.0, 51.1, 17.0) == 0


def test_haversine_wroclaw_known_points_within_1_percent() -> None:
    # Approximate reference via local equirectangular projection.
    lat1, lon1 = WROCLAW_RYNEK
    lat2, lon2 = WROCLAW_GLOWNY
    mean_lat = math.radians((lat1 + lat2) / 2)
    dx = math.radians(lon2 - lon1) * math.cos(mean_lat) * 6_371_000
    dy = math.radians(lat2 - lat1) * 6_371_000
    expected = math.hypot(dx, dy)
    got = haversine_m(lat1, lon1, lat2, lon2)
    assert abs(got - expected) / expected <= 0.01


def test_haversine_rejects_invalid_coordinates() -> None:
    with pytest.raises(ArgumentError):
        haversine_m(100.0, 17.0, 51.0, 17.0)
    with pytest.raises(ArgumentError):
        haversine_m(51.0, 200.0, 51.0, 17.0)


def test_point_exactly_on_radius_boundary_included() -> None:
    center_lat, center_lon = 51.1079, 17.0385
    point_lat = center_lat + (1000.0 / 111_320.0)
    distance_m = haversine_m(center_lat, center_lon, point_lat, center_lon)
    radius_km = distance_m / 1000.0
    inside, got = within_radius_m(
        center_lat, center_lon, point_lat, center_lon, radius_km=radius_km
    )
    assert inside
    assert got == distance_m
    # One metre farther must be excluded.
    outside, _ = within_radius_m(
        center_lat,
        center_lon,
        point_lat + (1.0 / 111_320.0),
        center_lon,
        radius_km=radius_km,
    )
    assert not outside


def test_bbox_contains_cardinal_boundary_points() -> None:
    center_lat, center_lon = 51.1079, 17.0385
    radius_km = 3.0
    bbox = compute_bbox(center_lat, center_lon, radius_km)
    radius_m = radius_km * 1000
    m_per_deg_lat = 111_320.0
    m_per_deg_lon = 111_320.0 * math.cos(math.radians(center_lat))

    north = (center_lat + radius_m / m_per_deg_lat, center_lon)
    south = (center_lat - radius_m / m_per_deg_lat, center_lon)
    east = (center_lat, center_lon + radius_m / m_per_deg_lon)
    west = (center_lat, center_lon - radius_m / m_per_deg_lon)

    for lat, lon in (north, south, east, west):
        assert bbox.contains(lat, lon), (lat, lon, bbox)
        inside, _ = within_radius_m(center_lat, center_lon, lat, lon, radius_km)
        assert inside


def test_bbox_rejects_impossible_inputs() -> None:
    with pytest.raises(ArgumentError):
        compute_bbox(51.1, 17.0, 0)
    with pytest.raises(ArgumentError):
        compute_bbox(90.0, 17.0, 1.0)
