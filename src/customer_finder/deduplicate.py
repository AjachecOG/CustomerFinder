"""Deterministic graph-based deduplication of Overture candidates."""

from __future__ import annotations

from dataclasses import dataclass

from rapidfuzz import fuzz

from customer_finder.geometry import haversine_m
from customer_finder.models import RawOverturePlace, SourceRef
from customer_finder.normalize import normalize_name, normalize_phone

NAME_SIMILARITY_THRESHOLD = 92
PHONE_DISTANCE_M = 100
NAME_DISTANCE_M = 50


@dataclass(frozen=True, slots=True)
class DedupResult:
    places: list[RawOverturePlace]
    deduplicated_count: int
    merged_groups: list[list[str]]


def _unique_sorted_strs(values: list[str]) -> list[str]:
    return sorted(set(values))


def _merge_source_refs(refs: list[SourceRef]) -> list[SourceRef]:
    seen: set[tuple[str, str | None, str | None, str | None]] = set()
    out: list[SourceRef] = []
    for ref in refs:
        key = (
            ref.dataset,
            ref.license,
            ref.property_path,
            ref.update_time.isoformat() if ref.update_time else None,
        )
        if key in seen:
            continue
        seen.add(key)
        out.append(ref)
    out.sort(key=lambda r: (r.dataset, r.property_path or "", r.license or ""))
    return out


def _usable_phones(place: RawOverturePlace) -> set[str]:
    usable: set[str] = set()
    for phone in place.phones:
        normalized, ok = normalize_phone(phone, country=place.country)
        if ok and normalized:
            usable.add(normalized)
    return usable


def _should_link(a: RawOverturePlace, b: RawOverturePlace) -> bool:
    if a.overture_id == b.overture_id:
        return True
    distance = haversine_m(a.lat, a.lon, b.lat, b.lon)
    phones_a = _usable_phones(a)
    phones_b = _usable_phones(b)
    if phones_a and phones_b and phones_a & phones_b and distance <= PHONE_DISTANCE_M:
        return True
    name_a = normalize_name(a.name)
    name_b = normalize_name(b.name)
    if name_a and name_b:
        similarity = fuzz.ratio(name_a, name_b)
        if similarity >= NAME_SIMILARITY_THRESHOLD and distance <= NAME_DISTANCE_M:
            return True
    return False


def _merge_component(places: list[RawOverturePlace]) -> RawOverturePlace:
    def sort_key(place: RawOverturePlace) -> tuple[float, str]:
        conf = place.confidence if place.confidence is not None else -1.0
        # Highest confidence first; smallest overture_id on tie.
        return (-conf, place.overture_id)

    base = sorted(places, key=sort_key)[0]

    websites = _unique_sorted_strs([u for p in places for u in p.websites])
    socials = _unique_sorted_strs([u for p in places for u in p.socials])
    emails = _unique_sorted_strs([u for p in places for u in p.emails])
    phones = _unique_sorted_strs([u for p in places for u in p.phones])
    sources = _merge_source_refs([s for p in places for s in p.source_refs])

    address_freeform = base.address_freeform
    locality = base.locality
    postcode = base.postcode
    country = base.country
    for place in places:
        if address_freeform:
            break
        if place.address_freeform:
            address_freeform = place.address_freeform
            locality = place.locality
            postcode = place.postcode
            country = place.country

    brand_name = base.brand_name
    if not brand_name:
        for place in places:
            if place.brand_name:
                brand_name = place.brand_name
                break

    name = base.name
    if not name:
        for place in places:
            if place.name:
                name = place.name
                break

    return base.model_copy(
        update={
            "name": name,
            "websites": websites,
            "socials": socials,
            "emails": emails,
            "phones": phones,
            "source_refs": sources,
            "address_freeform": address_freeform,
            "locality": locality,
            "postcode": postcode,
            "country": country,
            "brand_name": brand_name,
        }
    )


def deduplicate(places: list[RawOverturePlace]) -> DedupResult:
    """Merge connected components; result is deterministic across input shuffles."""
    ordered = sorted(places, key=lambda p: p.overture_id)
    n = len(ordered)
    parent = list(range(n))

    def find(i: int) -> int:
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i

    def union(i: int, j: int) -> None:
        ri, rj = find(i), find(j)
        if ri == rj:
            return
        # Keep smaller root id for stability.
        if ri < rj:
            parent[rj] = ri
        else:
            parent[ri] = rj

    for i in range(n):
        for j in range(i + 1, n):
            if _should_link(ordered[i], ordered[j]):
                union(i, j)

    components: dict[int, list[RawOverturePlace]] = {}
    for idx, place in enumerate(ordered):
        root = find(idx)
        components.setdefault(root, []).append(place)

    merged_groups: list[list[str]] = []
    merged_places: list[RawOverturePlace] = []
    for group in components.values():
        ids = sorted(p.overture_id for p in group)
        if len(group) > 1:
            merged_groups.append(ids)
        merged_places.append(_merge_component(group))

    merged_places.sort(key=lambda p: p.overture_id)
    deduplicated_count = len(places) - len(merged_places)
    return DedupResult(
        places=merged_places,
        deduplicated_count=deduplicated_count,
        merged_groups=sorted(merged_groups, key=lambda g: g[0]),
    )
