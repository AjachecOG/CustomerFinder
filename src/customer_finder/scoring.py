"""Deterministic scoring with explicit reason codes."""

from __future__ import annotations

from customer_finder.models import Candidate, CandidateBucket, RawOverturePlace
from customer_finder.normalize import normalize_name, normalize_phone
from customer_finder.settings import AppConfig

_BUCKET_SCORE: dict[CandidateBucket, tuple[int, str]] = {
    CandidateBucket.LIKELY_NO_SITE: (30, "likely_no_site"),
    CandidateBucket.SOCIAL_ONLY: (22, "social_only"),
    CandidateBucket.AGGREGATOR_ONLY: (16, "aggregator_only"),
    CandidateBucket.UNKNOWN: (-15, "unknown"),
    CandidateBucket.HAS_OWNED_SITE: (0, "has_owned_site"),
}


def score_candidate(
    place: RawOverturePlace,
    *,
    config: AppConfig,
    bucket: CandidateBucket,
    category_alias: str,
    is_chain: bool,
    chain_reason: str | None,
    owned_domains: list[str],
    social_urls: list[str],
    aggregator_urls: list[str],
    other_urls: list[str],
    distance_m: int,
) -> Candidate:
    score = 10
    reasons: list[str] = ["base:+10"]

    mapping = config.mapping_for(category_alias)
    weight = mapping.score_weight
    score += weight
    reasons.append(f"category:{category_alias}:+{weight}")

    delta, code = _BUCKET_SCORE[bucket]
    if delta:
        score += delta
        sign = "+" if delta > 0 else ""
        reasons.append(f"{code}:{sign}{delta}")

    usable_phones = [
        normalize_phone(p, country=place.country)[0]
        for p in place.phones
        if normalize_phone(p, country=place.country)[1]
    ]
    # Count presence of any phone (usable or raw) for scoring contactability.
    if place.phones:
        score += 8
        reasons.append("phone:+8")
    if place.emails:
        score += 4
        reasons.append("email:+4")
    if place.address_freeform and place.locality:
        score += 5
        reasons.append("address_locality:+5")

    conf = place.confidence
    if conf is not None:
        if conf >= 0.80:
            score += 10
            reasons.append("confidence_high:+10")
        elif conf >= 0.50:
            score += 5
            reasons.append("confidence_mid:+5")
        elif conf < 0.30:
            score -= 15
            reasons.append("confidence_low:-15")

    if place.operating_status == "open":
        score += 5
        reasons.append("open:+5")
    if place.brand_name:
        score -= 5
        reasons.append("brand:-5")
    if is_chain:
        score -= 30
        reasons.append("chain:-30")
    if not place.name:
        score -= 40
        reasons.append("missing_name:-40")

    score = max(0, min(100, score))

    normalized_phones = sorted(
        {
            normalize_phone(p, country=place.country)[0]
            for p in place.phones
            if normalize_phone(p, country=place.country)[0]
        }
    )
    # Prefer usable E.164 forms when available.
    if usable_phones:
        normalized_phones = sorted(set(usable_phones))

    return Candidate(
        raw=place,
        distance_m=distance_m,
        normalized_name=normalize_name(place.name),
        category_alias=category_alias,
        owned_domains=owned_domains,
        social_urls=social_urls,
        aggregator_urls=aggregator_urls,
        other_urls=other_urls,
        normalized_phones=normalized_phones,
        is_chain=is_chain,
        chain_reason=chain_reason,
        bucket=bucket,
        score=score,
        score_reasons=reasons,
    )
