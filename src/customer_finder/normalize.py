"""Name, phone, and URL normalization helpers."""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from urllib.parse import urlsplit

from customer_finder.settings import AppConfig

_PUNCT_RE = re.compile(r"[^\w\s]", re.UNICODE)
_MULTI_SPACE_RE = re.compile(r"\s+")
_PHONE_KEEP_RE = re.compile(r"[^\d+]")


def normalize_name(value: str | None) -> str:
    """NFKC, lowercase, punctuation→space, collapse spaces; keep Polish letters."""
    if value is None:
        return ""
    text = unicodedata.normalize("NFKC", value).lower()
    text = _PUNCT_RE.sub(" ", text)
    text = _MULTI_SPACE_RE.sub(" ", text).strip()
    return text


def normalize_phone(raw: str, *, country: str | None) -> tuple[str, bool]:
    """Return (normalized_or_raw, usable_for_dedupe).

    Ambiguous values are kept as stripped raw text but marked unusable for dedupe.
    """
    if not raw or not raw.strip():
        return "", False
    original = raw.strip()
    keep_plus = original.startswith("+")
    digits = _PHONE_KEEP_RE.sub("", original)
    if keep_plus and not digits.startswith("+"):
        digits = "+" + digits.lstrip("+")
    # Collapse to + and digits only.
    body = digits[1:] if digits.startswith("+") else digits
    if not body.isdigit():
        return original, False
    if digits.startswith("+"):
        if len(body) < 8:
            return original, False
        return f"+{body}", True
    if (country or "").upper() == "PL" and len(body) == 9:
        return f"+48{body}", True
    # Other national formats without + are ambiguous.
    return original, False


@dataclass(frozen=True, slots=True)
class ClassifiedUrls:
    owned_domains: list[str]
    social_urls: list[str]
    aggregator_urls: list[str]
    other_urls: list[str]
    warnings: list[str]


def _normalize_host(host: str) -> str:
    host = host.lower().rstrip(".")
    if host.startswith("www."):
        host = host[4:]
    return host


def _host_matches(host: str, rule_host: str) -> bool:
    return host == rule_host or host.endswith("." + rule_host)


def _is_public_hostname(host: str) -> bool:
    if not host or host == "localhost":
        return False
    # Reject IPv4 / IPv6-like and single-label hosts.
    if ":" in host or host.replace(".", "").isdigit():
        return False
    if "." not in host:
        return False
    try:
        host.encode("idna")
    except UnicodeError:
        return False
    labels = host.split(".")
    return not any(not label or label.startswith("-") or label.endswith("-") for label in labels)


def classify_url(raw: str, config: AppConfig) -> tuple[str, str | None]:
    """Classify one URL into owned|social|aggregator|other; return (kind, normalized)."""
    text = raw.strip()
    if not text:
        return "other", None
    if text[0] in "=+-@":
        return "other", text
    candidate = text if "://" in text else f"https://{text}"
    try:
        parts = urlsplit(candidate)
    except ValueError:
        return "other", text
    host = _normalize_host(parts.hostname or "")
    if not host:
        return "other", text
    for rule in config.domain_rules.ignored_hosts:
        if _host_matches(host, rule):
            return "other", text
    for rule in config.domain_rules.social_hosts:
        if _host_matches(host, rule):
            return "social", candidate
    for rule in config.domain_rules.aggregator_hosts:
        if _host_matches(host, rule):
            return "aggregator", candidate
    if not _is_public_hostname(host):
        return "other", text
    # Owned: store scheme://host[/path] without fragment; keep path for clarity.
    path = parts.path if parts.path not in ("", "/") else ""
    query = f"?{parts.query}" if parts.query else ""
    normalized = f"https://{host}{path}{query}"
    return "owned", normalized


def classify_urls(urls: list[str], config: AppConfig) -> ClassifiedUrls:
    owned: set[str] = set()
    social: set[str] = set()
    aggregator: set[str] = set()
    other: set[str] = set()
    warnings: list[str] = []
    for raw in urls:
        kind, normalized = classify_url(raw, config)
        if normalized is None:
            continue
        if kind == "owned":
            owned.add(normalized)
        elif kind == "social":
            social.add(normalized)
        elif kind == "aggregator":
            aggregator.add(normalized)
        else:
            other.add(normalized)
            if raw.strip() and raw.strip()[0] in "=+-@":
                warnings.append(f"rejected_formula_like_url:{raw[:32]}")
            elif "://" not in raw and "." not in raw:
                warnings.append(f"invalid_url:{raw[:32]}")
    return ClassifiedUrls(
        owned_domains=sorted(owned),
        social_urls=sorted(social),
        aggregator_urls=sorted(aggregator),
        other_urls=sorted(other),
        warnings=warnings,
    )
