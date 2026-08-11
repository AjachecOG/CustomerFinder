"""URL/bucket classification and chain detection."""

from __future__ import annotations

from dataclasses import dataclass

from rapidfuzz import fuzz

from customer_finder.models import CandidateBucket, RawOverturePlace
from customer_finder.normalize import ClassifiedUrls, classify_urls, normalize_name
from customer_finder.settings import AppConfig

CHAIN_NAME_SIMILARITY = 95


@dataclass(frozen=True, slots=True)
class Classification:
    bucket: CandidateBucket | None
    """None means permanently_closed — drop before scoring."""
    owned_domains: list[str]
    social_urls: list[str]
    aggregator_urls: list[str]
    other_urls: list[str]
    is_chain: bool
    chain_reason: str | None
    category_alias: str | None
    warnings: list[str]


def detect_chains(
    places: list[RawOverturePlace], config: AppConfig
) -> dict[str, tuple[bool, str | None]]:
    """Return overture_id -> (is_chain, reason) for the current result set."""
    denylist = {normalize_name(name) for name in config.chain_denylist.chains}
    denylist.discard("")

    brand_groups: dict[str, list[str]] = {}
    for place in places:
        brand = normalize_name(place.brand_name)
        if brand:
            brand_groups.setdefault(brand, []).append(place.overture_id)

    # Name similarity clusters with distinct locations (>=3).
    name_chain_ids: set[str] = set()
    normalized_entries = [
        (place.overture_id, normalize_name(place.name), place.lat, place.lon)
        for place in places
        if place.name
    ]
    for i, (id_a, name_a, lat_a, lon_a) in enumerate(normalized_entries):
        if not name_a:
            continue
        similar: list[tuple[str, float, float]] = [(id_a, lat_a, lon_a)]
        for id_b, name_b, lat_b, lon_b in normalized_entries[i + 1 :]:
            if not name_b:
                continue
            if fuzz.ratio(name_a, name_b) >= CHAIN_NAME_SIMILARITY:
                similar.append((id_b, lat_b, lon_b))
        locations = {(round(lat, 5), round(lon, 5)) for _, lat, lon in similar}
        if len(similar) >= 3 and len(locations) >= 3:
            name_chain_ids.update(item[0] for item in similar)

    result: dict[str, tuple[bool, str | None]] = {}
    for place in places:
        name_n = normalize_name(place.name)
        brand_n = normalize_name(place.brand_name)
        if name_n in denylist or brand_n in denylist:
            result[place.overture_id] = (True, "denylist")
            continue
        if brand_n and len(brand_groups.get(brand_n, [])) >= 3:
            result[place.overture_id] = (True, "shared_brand")
            continue
        if place.overture_id in name_chain_ids:
            result[place.overture_id] = (True, "similar_name_locations")
            continue
        result[place.overture_id] = (False, None)
    return result


def classify_bucket(urls: ClassifiedUrls, place: RawOverturePlace) -> CandidateBucket | None:
    """Apply bucket priority rules; None => permanently closed (exclude)."""
    if place.operating_status == "permanently_closed":
        return None
    if urls.owned_domains:
        return CandidateBucket.HAS_OWNED_SITE
    if not place.name or (place.confidence is not None and place.confidence < 0.30):
        return CandidateBucket.UNKNOWN
    if place.operating_status == "temporarily_closed":
        return CandidateBucket.UNKNOWN
    if urls.social_urls:
        return CandidateBucket.SOCIAL_ONLY
    if urls.aggregator_urls:
        return CandidateBucket.AGGREGATOR_ONLY
    if urls.other_urls:
        return CandidateBucket.UNKNOWN
    has_contact = bool(place.address_freeform or place.phones)
    if place.name and has_contact:
        return CandidateBucket.LIKELY_NO_SITE
    return CandidateBucket.UNKNOWN


def classify_place(
    place: RawOverturePlace,
    *,
    config: AppConfig,
    chain_info: tuple[bool, str | None],
) -> Classification:
    combined_urls = list(place.websites) + list(place.socials)
    urls = classify_urls(combined_urls, config)
    bucket = classify_bucket(urls, place)
    alias = config.resolve_category_alias(
        basic_category=place.basic_category,
        taxonomy_primary=place.taxonomy_primary,
        taxonomy_hierarchy=place.taxonomy_hierarchy,
        taxonomy_alternates=place.taxonomy_alternates,
    )
    is_chain, reason = chain_info
    return Classification(
        bucket=bucket,
        owned_domains=urls.owned_domains,
        social_urls=urls.social_urls,
        aggregator_urls=urls.aggregator_urls,
        other_urls=urls.other_urls,
        is_chain=is_chain,
        chain_reason=reason,
        category_alias=alias,
        warnings=urls.warnings,
    )
