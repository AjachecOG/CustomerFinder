"""Unit tests for Google Places matching and enrichment."""

from __future__ import annotations

import json
from pathlib import Path

import httpx
import pytest
import respx

from customer_finder.errors import ConfigError
from customer_finder.google_places import (
    TEXT_SEARCH_URL,
    enrich_candidates,
    match_text_search_response,
    require_calibration_approval,
)
from customer_finder.models import Candidate, CandidateBucket, RawOverturePlace
from customer_finder.settings import Settings, load_builtin_config

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures"


def _candidate() -> Candidate:
    place = RawOverturePlace(
        overture_id="place_nosite",
        version=1,
        name="Cicha Piekarnia",
        lat=51.10565,
        lon=17.03593,
        address_freeform="ul. Cicha 5",
        locality="Wrocław",
        postcode="50-005",
        country="PL",
        phones=["+48711000004"],
    )
    return Candidate(
        raw=place,
        distance_m=100,
        normalized_name="cicha piekarnia",
        category_alias="bakery",
        bucket=CandidateBucket.LIKELY_NO_SITE,
        score=80,
        score_reasons=["base:+10"],
    )


def test_match_single_qualifying_result() -> None:
    cfg = load_builtin_config()
    payload = json.loads((FIXTURES / "google_text_search_match.json").read_text(encoding="utf-8"))
    result = match_text_search_response(_candidate(), payload, config=cfg)
    assert result.status == "matched"
    assert result.place_id == "ChIJmatch001"
    assert result.website_kind == "owned"


def test_match_ambiguous_when_two_qualify() -> None:
    cfg = load_builtin_config()
    payload = json.loads(
        (FIXTURES / "google_text_search_ambiguous.json").read_text(encoding="utf-8")
    )
    result = match_text_search_response(_candidate(), payload, config=cfg)
    assert result.status == "ambiguous"


def test_match_not_found_on_empty() -> None:
    cfg = load_builtin_config()
    result = match_text_search_response(_candidate(), {"places": []}, config=cfg)
    assert result.status == "not_found"


def test_require_calibration_approval(tmp_path: Path) -> None:
    csv_path = tmp_path / "calibration.csv"
    csv_path.write_text("rank,overture_id\n1,a\n", encoding="utf-8")
    summary_path = tmp_path / "calibration.summary.json"
    summary_path.write_text('{"passed": true}\n', encoding="utf-8")
    digest = __import__("hashlib").sha256(csv_path.read_bytes()).hexdigest()
    summary_digest = __import__("hashlib").sha256(summary_path.read_bytes()).hexdigest()
    approved = tmp_path / "calibration.approved.json"
    approved.write_text(
        json.dumps(
            {
                "passed": True,
                "calibration_csv": str(csv_path),
                "calibration_sha256": digest,
                "summary_json": str(summary_path),
                "summary_sha256": summary_digest,
            }
        ),
        encoding="utf-8",
    )
    require_calibration_approval(approved)
    with pytest.raises(ConfigError):
        require_calibration_approval(tmp_path / "missing.json")
    summary_path.write_text('{"passed": true, "tampered": true}\n', encoding="utf-8")
    with pytest.raises(ConfigError, match="summary"):
        require_calibration_approval(approved)


@respx.mock
def test_enrich_candidates_budget_and_match(tmp_path: Path) -> None:
    cfg = load_builtin_config()
    payload = json.loads((FIXTURES / "google_text_search_match.json").read_text(encoding="utf-8"))
    respx.post(TEXT_SEARCH_URL).mock(return_value=httpx.Response(200, json=payload))
    cand_a = _candidate()
    cand_b = _candidate().model_copy(
        update={"raw": cand_a.raw.model_copy(update={"overture_id": "b"}), "score": 10}
    )
    updated, stats, _warnings = enrich_candidates(
        [cand_a, cand_b],
        config=cfg,
        settings=Settings(google_maps_api_key="test-key"),
        google_max_requests=1,
        require_approval=False,
    )
    assert stats.http_attempts == 1
    assert stats.matched + stats.skipped_budget == 2
    assert any(c.google_place_id for c in updated) or stats.matched == 1
    assert updated[0].google_place_id == "ChIJmatch001"
    assert updated[1].google_place_id is None


@respx.mock
def test_enrich_missing_key_is_config_error() -> None:
    cfg = load_builtin_config()
    with pytest.raises(ConfigError):
        enrich_candidates(
            [_candidate()],
            config=cfg,
            settings=Settings(google_maps_api_key=None),
            require_approval=False,
        )


@respx.mock
def test_enrich_401_is_config_error() -> None:
    cfg = load_builtin_config()
    respx.post(TEXT_SEARCH_URL).mock(return_value=httpx.Response(401, json={"error": "no"}))
    with pytest.raises(ConfigError):
        enrich_candidates(
            [_candidate()],
            config=cfg,
            settings=Settings(google_maps_api_key="bad"),
            require_approval=False,
        )


@respx.mock
def test_enrich_retries_429_then_succeeds() -> None:
    cfg = load_builtin_config()
    payload = json.loads((FIXTURES / "google_text_search_match.json").read_text(encoding="utf-8"))
    respx.post(TEXT_SEARCH_URL).mock(
        side_effect=[
            httpx.Response(429, json={"error": "rate"}),
            httpx.Response(200, json=payload),
        ]
    )
    updated, stats, _ = enrich_candidates(
        [_candidate()],
        config=cfg,
        settings=Settings(google_maps_api_key="test-key"),
        google_max_requests=5,
        require_approval=False,
    )
    assert stats.http_attempts == 2
    assert stats.matched == 1
    assert updated[0].google_place_id == "ChIJmatch001"


def test_building_number_conflict_rejects() -> None:
    cfg = load_builtin_config()
    cand = _candidate()
    payload = {
        "places": [
            {
                "id": "places/x",
                "displayName": {"text": "Cicha Piekarnia"},
                "formattedAddress": "ul. Cicha 9, Wrocław",
                "location": {"latitude": 51.10565, "longitude": 17.03593},
            }
        ]
    }
    result = match_text_search_response(cand, payload, config=cfg)
    assert result.status == "not_found"


def test_website_kind_social_and_none() -> None:
    from customer_finder.google_places import website_kind_from_uri

    cfg = load_builtin_config()
    assert website_kind_from_uri(None, cfg) == "none"
    assert website_kind_from_uri("https://instagram.com/x", cfg) == "social"
    assert website_kind_from_uri("https://pyszne.pl/x", cfg) == "aggregator"


@respx.mock
def test_enrich_does_not_follow_redirects_with_api_key() -> None:
    cfg = load_builtin_config()
    evil = respx.post("https://evil.example/steal").mock(
        return_value=httpx.Response(200, json={"places": []})
    )
    respx.post(TEXT_SEARCH_URL).mock(
        return_value=httpx.Response(302, headers={"location": "https://evil.example/steal"})
    )
    _updated, stats, _warnings = enrich_candidates(
        [_candidate()],
        config=cfg,
        settings=Settings(google_maps_api_key="super-secret-key"),
        require_approval=False,
    )
    assert evil.call_count == 0
    assert stats.errors == 1 or stats.http_attempts >= 1


@respx.mock
def test_enrich_does_not_http_for_candidates_beyond_budget() -> None:
    cfg = load_builtin_config()
    route = respx.post(TEXT_SEARCH_URL).mock(return_value=httpx.Response(200, json={"places": []}))
    high = _candidate()
    mid = _candidate().model_copy(
        update={"raw": high.raw.model_copy(update={"overture_id": "mid"}), "score": 50}
    )
    low = _candidate().model_copy(
        update={"raw": high.raw.model_copy(update={"overture_id": "low"}), "score": 10}
    )
    _updated, stats, _warnings = enrich_candidates(
        [low, high, mid],
        config=cfg,
        settings=Settings(google_maps_api_key="test-key"),
        google_max_requests=1,
        require_approval=False,
    )
    assert route.call_count == 1
    assert stats.skipped_budget == 2
    assert stats.logical_candidates == 3
