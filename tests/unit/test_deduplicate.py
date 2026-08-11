"""Unit tests for deduplication."""

from __future__ import annotations

import random

from customer_finder.deduplicate import deduplicate
from customer_finder.models import RawOverturePlace


def _place(**kwargs: object) -> RawOverturePlace:
    base = {
        "overture_id": "id",
        "version": 1,
        "name": "Cafe",
        "lat": 51.1079,
        "lon": 17.0385,
        "phones": [],
        "websites": [],
        "socials": [],
        "emails": [],
        "confidence": 0.5,
        "country": "PL",
    }
    base.update(kwargs)
    return RawOverturePlace.model_validate(base)


def test_dedupe_same_phone_within_100m() -> None:
    a = _place(overture_id="a", lat=51.1079, lon=17.0385, phones=["711000001"], confidence=0.9)
    b = _place(
        overture_id="b",
        lat=51.1080,
        lon=17.0386,
        phones=["+48 711 000 001"],
        confidence=0.4,
        websites=["https://extra.pl"],
    )
    result = deduplicate([a, b])
    assert result.deduplicated_count == 1
    assert len(result.places) == 1
    assert result.places[0].overture_id == "a"
    assert result.places[0].websites == ["https://extra.pl"]


def test_dedupe_similar_name_within_50m() -> None:
    a = _place(overture_id="a", name="Cluster Cafe Nadodrze", lat=51.1079, lon=17.0385)
    b = _place(overture_id="b", name="Cluster Cafe Nadodrze!", lat=51.10805, lon=17.03855)
    result = deduplicate([a, b])
    assert result.deduplicated_count == 1


def test_dedupe_keeps_far_similar_names() -> None:
    a = _place(overture_id="a", name="Cluster Cafe", lat=51.1079, lon=17.0385)
    b = _place(overture_id="b", name="Cluster Cafe", lat=51.12, lon=17.05)
    result = deduplicate([a, b])
    assert result.deduplicated_count == 0
    assert len(result.places) == 2


def test_dedupe_order_independent() -> None:
    places = [
        _place(overture_id="c", name="X Cafe", lat=51.1079, lon=17.0385, phones=["711000099"]),
        _place(overture_id="a", name="X Cafe", lat=51.1080, lon=17.0386, phones=["711000099"]),
        _place(overture_id="b", name="X Cafe!", lat=51.1081, lon=17.0387, phones=[]),
    ]
    results = []
    for _ in range(3):
        shuffled = places[:]
        random.shuffle(shuffled)
        result = deduplicate(shuffled)
        results.append([p.overture_id for p in result.places])
    assert results[0] == results[1] == results[2]
    assert results[0] == ["a"] or len(results[0]) == 1
