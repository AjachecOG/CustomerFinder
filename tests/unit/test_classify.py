"""Unit tests for classification and chain detection."""

from __future__ import annotations

from customer_finder.classify import classify_place, detect_chains
from customer_finder.models import CandidateBucket, RawOverturePlace
from customer_finder.settings import load_builtin_config


def _place(**kwargs: object) -> RawOverturePlace:
    base = {
        "overture_id": "id",
        "version": 1,
        "name": "Lokal",
        "lat": 51.1,
        "lon": 17.0,
        "phones": ["+48711000000"],
        "websites": [],
        "socials": [],
        "emails": [],
        "confidence": 0.8,
        "operating_status": "open",
        "address_freeform": "ul. Test 1",
        "locality": "Wrocław",
        "country": "PL",
        "basic_category": "cafe",
        "taxonomy_primary": "cafe",
        "taxonomy_hierarchy": ["cafe"],
    }
    base.update(kwargs)
    return RawOverturePlace.model_validate(base)


def test_buckets_priority_and_closed() -> None:
    cfg = load_builtin_config()
    chains = detect_chains([], cfg)

    owned = classify_place(
        _place(websites=["https://own.pl"], socials=["https://instagram.com/x"]),
        config=cfg,
        chain_info=(False, None),
    )
    assert owned.bucket == CandidateBucket.HAS_OWNED_SITE

    social = classify_place(
        _place(socials=["https://instagram.com/x"]),
        config=cfg,
        chain_info=(False, None),
    )
    assert social.bucket == CandidateBucket.SOCIAL_ONLY

    agg = classify_place(
        _place(websites=["https://pyszne.pl/r"]),
        config=cfg,
        chain_info=(False, None),
    )
    assert agg.bucket == CandidateBucket.AGGREGATOR_ONLY

    nosite = classify_place(_place(), config=cfg, chain_info=(False, None))
    assert nosite.bucket == CandidateBucket.LIKELY_NO_SITE

    unknown = classify_place(
        _place(name=None),
        config=cfg,
        chain_info=(False, None),
    )
    assert unknown.bucket == CandidateBucket.UNKNOWN

    closed = classify_place(
        _place(operating_status="permanently_closed"),
        config=cfg,
        chain_info=(False, None),
    )
    assert closed.bucket is None
    _ = chains


def test_denylist_chain_detection() -> None:
    cfg = load_builtin_config()
    place = _place(overture_id="s", name="Starbucks Nadodrze", brand_name="Starbucks")
    info = detect_chains([place], cfg)
    assert info["s"][0] is True
    assert info["s"][1] == "denylist"


def test_three_similar_locations_mark_chain() -> None:
    cfg = load_builtin_config()
    places = [
        _place(overture_id="1", name="Same Cafe", lat=51.10, lon=17.00),
        _place(overture_id="2", name="Same Cafe", lat=51.11, lon=17.01),
        _place(overture_id="3", name="Same Cafe", lat=51.12, lon=17.02),
    ]
    info = detect_chains(places, cfg)
    assert all(info[p.overture_id][0] for p in places)
