"""Unit tests for normalize helpers."""

from __future__ import annotations

from customer_finder.normalize import classify_url, classify_urls, normalize_name, normalize_phone
from customer_finder.settings import load_builtin_config


def test_normalize_name_keeps_polish_and_strips_punct() -> None:
    assert normalize_name("  Kawiarnia „Świetlica”!!! ") == "kawiarnia świetlica"


def test_normalize_phone_poland_national() -> None:
    assert normalize_phone("71 100-00-01", country="PL") == ("+48711000001", True)
    assert normalize_phone("71 100-00-01", country="pl") == ("+48711000001", True)
    assert normalize_phone("+48 711 000 001", country="PL") == ("+48711000001", True)
    phone, usable = normalize_phone("123", country="PL")
    assert phone == "123"
    assert usable is False


def test_classify_url_subdomain_social_and_owned() -> None:
    cfg = load_builtin_config()
    assert classify_url("m.facebook.com/page", cfg)[0] == "social"
    assert classify_url("facebook.com.example.org", cfg)[0] == "owned"
    kind, normalized = classify_url("cafewlasna.pl", cfg)
    assert kind == "owned"
    assert normalized == "https://cafewlasna.pl"


def test_classify_urls_sorts_and_dedupes() -> None:
    cfg = load_builtin_config()
    result = classify_urls(
        [
            "https://instagram.com/a",
            "instagram.com/a",
            "https://pyszne.pl/x",
            "https://own.pl",
            "=HYPERLINK(1)",
        ],
        cfg,
    )
    assert result.social_urls == ["https://instagram.com/a"]
    assert result.aggregator_urls == ["https://pyszne.pl/x"]
    assert result.owned_domains == ["https://own.pl"]
    assert any(u.startswith("=") for u in result.other_urls)
