"""Manual Google Maps search URLs are generated, not fetched."""

from __future__ import annotations

from urllib.parse import parse_qs, urlparse

from customer_finder.models import Candidate, CandidateBucket, RawOverturePlace
from customer_finder.verify_links import format_verify_links, maps_search_url


def test_maps_search_url_encodes_name_address_and_locality() -> None:
    candidate = Candidate(
        raw=RawOverturePlace(
            overture_id="id-1",
            version=1,
            name="Cukiernia Ąęć",
            lat=51.1,
            lon=17.0,
            address_freeform="ul. Testowa 1/2",
            locality="Wrocław",
        ),
        distance_m=10,
        normalized_name="cukiernia aec",
        category_alias="pastry",
        bucket=CandidateBucket.LIKELY_NO_SITE,
        score=80,
        score_reasons=["base:+10"],
    )
    url = maps_search_url(candidate)
    parsed = urlparse(url)
    assert parsed.scheme == "https"
    assert parsed.netloc == "www.google.com"
    assert parsed.path == "/maps/search/"
    query = parse_qs(parsed.query)
    assert query["api"] == ["1"]
    assert "query_place_id" not in query
    assert query["query"] == ["Cukiernia Ąęć ul. Testowa 1/2 Wrocław"]


def test_format_verify_links_includes_encoded_url() -> None:
    candidate = Candidate(
        raw=RawOverturePlace(
            overture_id="id-2",
            version=1,
            name="Cafe Test",
            lat=51.1,
            lon=17.0,
            address_freeform="Rynek 1",
            locality="Wrocław",
        ),
        distance_m=5,
        normalized_name="cafe test",
        category_alias="cafe",
        bucket=CandidateBucket.SOCIAL_ONLY,
        score=70,
        score_reasons=["base:+10"],
    )
    text = format_verify_links([candidate], limit=1)
    assert "bucket=social_only" in text
    assert "https://www.google.com/maps/search/?api=1&query=" in text
    assert "Cafe+Test" in text
