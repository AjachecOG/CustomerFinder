"""Manual verification Google Maps search links."""

from __future__ import annotations

from urllib.parse import urlencode

from customer_finder.models import Candidate

DEFAULT_VERIFY_LINK_LIMIT = 30


def maps_search_url(candidate: Candidate) -> str:
    parts = [
        candidate.raw.name or "",
        candidate.raw.address_freeform or "",
        candidate.raw.locality or "",
    ]
    query = " ".join(part for part in parts if part).strip() or candidate.raw.overture_id
    params: dict[str, str] = {"api": "1", "query": query}
    return "https://www.google.com/maps/search/?" + urlencode(params)


def format_verify_links(
    candidates: list[Candidate], *, limit: int = DEFAULT_VERIFY_LINK_LIMIT
) -> str:
    lines: list[str] = []
    for index, candidate in enumerate(candidates[:limit], start=1):
        name = candidate.raw.name or "(no name)"
        lines.append(
            f"[{index:02d}] {name} — bucket={candidate.bucket.value} — score={candidate.score}"
        )
        lines.append(maps_search_url(candidate))
        lines.append("")
    return "\n".join(lines).rstrip() + ("\n" if lines else "")
