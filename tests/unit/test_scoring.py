"""Unit tests for scoring."""

from __future__ import annotations

from customer_finder.models import CandidateBucket, RawOverturePlace
from customer_finder.scoring import score_candidate
from customer_finder.settings import load_builtin_config


def test_scoring_formula_and_clamp() -> None:
    cfg = load_builtin_config()
    place = RawOverturePlace(
        overture_id="x",
        version=1,
        name="Cukiernia Test",
        lat=51.1,
        lon=17.0,
        phones=["+48711"],
        emails=["a@b.pl"],
        address_freeform="ul. 1",
        locality="Wrocław",
        country="PL",
        confidence=0.9,
        operating_status="open",
        brand_name=None,
        taxonomy_primary="patisserie_cake_shop",
        taxonomy_hierarchy=["patisserie_cake_shop"],
    )
    # base 10 + pastry 25 + likely_no_site 30 + phone 8 + email 4 + addr 5
    # + conf 10 + open 5 = 97
    candidate = score_candidate(
        place,
        config=cfg,
        bucket=CandidateBucket.LIKELY_NO_SITE,
        category_alias="pastry",
        is_chain=False,
        chain_reason=None,
        owned_domains=[],
        social_urls=[],
        aggregator_urls=[],
        other_urls=[],
        distance_m=100,
    )
    assert candidate.score == 97
    assert "category:pastry:+25" in candidate.score_reasons
    assert "likely_no_site:+30" in candidate.score_reasons

    chained = score_candidate(
        place.model_copy(update={"name": None, "brand_name": "X", "confidence": 0.1}),
        config=cfg,
        bucket=CandidateBucket.UNKNOWN,
        category_alias="pastry",
        is_chain=True,
        chain_reason="denylist",
        owned_domains=[],
        social_urls=[],
        aggregator_urls=[],
        other_urls=[],
        distance_m=100,
    )
    assert chained.score == 0
    assert any(r.startswith("chain:") for r in chained.score_reasons)
