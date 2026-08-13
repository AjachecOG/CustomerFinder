"""Optional Google Places Text Search (New) enrichment."""

from __future__ import annotations

import hashlib
import json
import logging
import random
import re
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import httpx
from rapidfuzz import fuzz

from customer_finder import __version__
from customer_finder.errors import ConfigError, GoogleEnrichmentError
from customer_finder.geometry import haversine_m
from customer_finder.models import Candidate, GoogleMatchResult
from customer_finder.normalize import classify_url, normalize_name
from customer_finder.settings import AppConfig, Settings

logger = logging.getLogger(__name__)

TEXT_SEARCH_URL = "https://places.googleapis.com/v1/places:searchText"
GOOGLE_ALLOWED_HOST = "places.googleapis.com"
FIELD_MASK = (
    "places.id,places.displayName,places.formattedAddress,places.websiteUri,places.location"
)
NAME_SIM_THRESHOLD = 88
ADDRESS_SIM_THRESHOLD = 50
MATCH_DISTANCE_M = 250
BIAS_RADIUS_M = 250.0
MAX_ATTEMPTS = 3
MAX_WORKERS = 3
CONNECT_TIMEOUT_S = 5.0
READ_TIMEOUT_S = 15.0
DEFAULT_APPROVAL_PATH = Path("out/calibration.approved.json")

_BUILDING_NO_RE = re.compile(r"\b(\d+[a-zA-Z]?)\b")


@dataclass
class GoogleEnrichmentStats:
    enabled: bool = True
    request_budget: int = 0
    logical_candidates: int = 0
    http_attempts: int = 0
    matched: int = 0
    ambiguous: int = 0
    not_found: int = 0
    errors: int = 0
    skipped_budget: int = 0
    website_kind_counts: dict[str, int] = field(default_factory=dict)


@dataclass
class _Budget:
    limit: int
    used: int = 0
    _lock: threading.Lock = field(default_factory=threading.Lock)

    def try_acquire(self) -> bool:
        with self._lock:
            if self.used >= self.limit:
                return False
            self.used += 1
            return True


def _sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def require_calibration_approval(path: Path = DEFAULT_APPROVAL_PATH) -> dict[str, Any]:
    """Enforce Milestone 6 entry gate: valid calibration.approved.json."""
    if not path.is_file():
        raise ConfigError(
            "Google enrichment requires calibration.approved.json. "
            f"Missing {path}. Complete Milestone 5 calibration first."
        )
    try:
        loaded = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ConfigError(f"Invalid calibration approval JSON: {path}") from exc
    if not isinstance(loaded, dict):
        raise ConfigError(f"Calibration approval must be a JSON object: {path}")
    payload: dict[str, Any] = loaded
    if not payload.get("passed"):
        raise ConfigError(f"Calibration approval is not passed: {path}")
    csv_path = Path(str(payload.get("calibration_csv", "")))
    expected_hash = payload.get("calibration_sha256")
    if not csv_path.is_file() or not expected_hash:
        raise ConfigError(f"Calibration approval missing calibration_csv/sha256 fields: {path}")
    if _sha256_file(csv_path) != expected_hash:
        raise ConfigError(
            "calibration.approved.json hash does not match current calibration CSV; "
            "re-run calibration evaluate after reviewing the file."
        )
    summary_raw = payload.get("summary_json")
    expected_summary = payload.get("summary_sha256")
    if not summary_raw or not expected_summary:
        raise ConfigError(f"Calibration approval missing summary_json/sha256 fields: {path}")
    summary_path = Path(str(summary_raw))
    if not summary_path.is_file():
        raise ConfigError(f"Calibration approval summary file missing: {summary_path}")
    if _sha256_file(summary_path) != expected_summary:
        raise ConfigError(
            "calibration.approved.json hash does not match current summary JSON; "
            "re-run calibration evaluate after reviewing the file."
        )
    return payload


def _address_tokens(*parts: str | None) -> set[str]:
    text = " ".join(p for p in parts if p)
    text = text.replace(",", " ").lower()
    return {tok for tok in text.split() if tok}


def address_similarity(
    left: tuple[str | None, str | None, str | None],
    right: tuple[str | None, str | None, str | None],
) -> float:
    a = _address_tokens(*left)
    b = _address_tokens(*right)
    if not a or not b:
        return 0.0
    return 100.0 * len(a & b) / len(a | b)


def _building_number(text: str | None) -> str | None:
    if not text:
        return None
    match = _BUILDING_NO_RE.search(text)
    return match.group(1).lower() if match else None


def website_kind_from_uri(uri: str | None, config: AppConfig) -> str:
    if uri is None or not str(uri).strip():
        return "none"
    kind, _ = classify_url(str(uri), config)
    if kind == "owned":
        return "owned"
    if kind == "social":
        return "social"
    if kind == "aggregator":
        return "aggregator"
    return "unknown"


def match_text_search_response(
    candidate: Candidate,
    payload: dict[str, Any],
    *,
    config: AppConfig,
) -> GoogleMatchResult:
    """Apply entity-matching rules to a Text Search response body."""
    places = payload.get("places") or []
    if not isinstance(places, list):
        places = []

    qualifying: list[tuple[dict[str, Any], float, float, int]] = []
    for place in places:
        if not isinstance(place, dict):
            continue
        display = place.get("displayName") or {}
        google_name = display.get("text") if isinstance(display, dict) else None
        formatted = place.get("formattedAddress")
        location = place.get("location") or {}
        if not isinstance(location, dict):
            continue
        lat = location.get("latitude")
        lon = location.get("longitude")
        if lat is None or lon is None:
            continue

        name_sim = float(
            fuzz.ratio(
                normalize_name(candidate.raw.name),
                normalize_name(str(google_name) if google_name else ""),
            )
        )
        addr_sim = address_similarity(
            (
                candidate.raw.address_freeform,
                candidate.raw.locality,
                candidate.raw.postcode,
            ),
            (str(formatted) if formatted else None, None, None),
        )
        distance = haversine_m(candidate.raw.lat, candidate.raw.lon, float(lat), float(lon))
        left_no = _building_number(candidate.raw.address_freeform)
        right_no = _building_number(str(formatted) if formatted else None)
        if left_no and right_no and left_no != right_no:
            continue
        if (
            name_sim >= NAME_SIM_THRESHOLD
            and addr_sim >= ADDRESS_SIM_THRESHOLD
            and distance <= MATCH_DISTANCE_M
        ):
            qualifying.append((place, name_sim, addr_sim, distance))

    if not qualifying:
        return GoogleMatchResult(
            status="not_found",
            place_id=None,
            website_kind="none",
            name_similarity=None,
            address_similarity=None,
            match_distance_m=None,
            warning=None,
        )
    if len(qualifying) > 1:
        return GoogleMatchResult(
            status="ambiguous",
            place_id=None,
            website_kind="unknown",
            name_similarity=None,
            address_similarity=None,
            match_distance_m=None,
            warning="multiple_qualifying_matches",
        )

    place, name_sim, addr_sim, distance = qualifying[0]
    place_id = place.get("id")
    if isinstance(place_id, str) and place_id.startswith("places/"):
        place_id = place_id.removeprefix("places/")
    kind = website_kind_from_uri(
        str(place.get("websiteUri")) if place.get("websiteUri") is not None else None,
        config,
    )
    return GoogleMatchResult(
        status="matched",
        place_id=str(place_id) if place_id else None,
        website_kind=kind,  # type: ignore[arg-type]
        name_similarity=name_sim,
        address_similarity=addr_sim,
        match_distance_m=distance,
        warning=None,
    )


def _backoff_sleep(attempt: int) -> None:
    # attempt is 1-based after a failure; wait before retry 2 and 3.
    base = 0.5 * (2 ** (attempt - 1))
    time.sleep(base + random.uniform(0, 0.25))


def _google_request_hook(request: httpx.Request) -> None:
    """Refuse to send the API key anywhere except Places API (New)."""
    host = (request.url.host or "").lower()
    if request.url.scheme != "https" or host != GOOGLE_ALLOWED_HOST:
        raise ConfigError(f"Refusing Google Places URL host={host!r}")


def _post_text_search(
    client: httpx.Client,
    *,
    api_key: str,
    text_query: str,
    lat: float,
    lon: float,
    budget: _Budget,
    stop: threading.Event,
) -> tuple[dict[str, Any] | None, str | None, int]:
    """Return (payload, fatal_error, attempts_used)."""
    body = {
        "textQuery": text_query,
        "languageCode": "pl",
        "regionCode": "PL",
        "pageSize": 3,
        "locationBias": {
            "circle": {
                "center": {"latitude": lat, "longitude": lon},
                "radius": BIAS_RADIUS_M,
            }
        },
    }
    headers = {
        "Content-Type": "application/json",
        "X-Goog-Api-Key": api_key,
        "X-Goog-FieldMask": FIELD_MASK,
    }
    attempts = 0
    last_error: str | None = None
    for attempt in range(1, MAX_ATTEMPTS + 1):
        if stop.is_set():
            return None, "stopped", attempts
        if not budget.try_acquire():
            return None, "skipped_budget", attempts
        attempts += 1
        try:
            response = client.post(TEXT_SEARCH_URL, headers=headers, json=body)
        except httpx.TimeoutException:
            last_error = "timeout"
            if attempt < MAX_ATTEMPTS and not stop.is_set():
                _backoff_sleep(attempt)
                continue
            return None, last_error, attempts
        except httpx.TransportError as exc:
            last_error = f"transport:{exc.__class__.__name__}"
            if attempt < MAX_ATTEMPTS and not stop.is_set():
                _backoff_sleep(attempt)
                continue
            return None, last_error, attempts

        if response.status_code in {401, 403, 400}:
            stop.set()
            raise ConfigError(
                f"Google Places API rejected request with HTTP {response.status_code}"
            )
        if response.status_code == 429 or response.status_code >= 500:
            last_error = f"http_{response.status_code}"
            if attempt < MAX_ATTEMPTS and not stop.is_set():
                _backoff_sleep(attempt)
                continue
            return None, last_error, attempts
        if response.status_code != 200:
            last_error = f"http_{response.status_code}"
            return None, last_error, attempts
        data = response.json()
        if not isinstance(data, dict):
            return None, "invalid_json", attempts
        return data, None, attempts
    return None, last_error or "error", attempts


def enrich_candidates(
    candidates: list[Candidate],
    *,
    config: AppConfig,
    settings: Settings | None = None,
    google_max_requests: int = 50,
    strict: bool = False,
    client: httpx.Client | None = None,
    require_approval: bool = True,
    approval_path: Path = DEFAULT_APPROVAL_PATH,
) -> tuple[list[Candidate], GoogleEnrichmentStats, list[str]]:
    """Enrich candidates with Google Place IDs only; never mutates bucket/score."""
    warnings: list[str] = []
    if require_approval:
        require_calibration_approval(approval_path)

    env = settings or Settings()
    api_key = (env.google_maps_api_key or "").strip()
    if not api_key:
        raise ConfigError("GOOGLE_MAPS_API_KEY is required for --enrich google")
    if google_max_requests <= 0:
        raise ConfigError("google_max_requests must be > 0 for --enrich google")

    stats = GoogleEnrichmentStats(
        enabled=True,
        request_budget=google_max_requests,
        logical_candidates=len(candidates),
    )
    if not candidates:
        return candidates, stats, warnings

    # Prefer highest score when budget is tight (logical selection before HTTP).
    ordered = sorted(
        enumerate(candidates),
        key=lambda item: (-item[1].score, item[1].distance_m, item[1].raw.overture_id),
    )
    to_fetch = ordered[:google_max_requests]
    skipped_ahead = ordered[google_max_requests:]

    budget = _Budget(limit=google_max_requests)
    stop = threading.Event()
    results: dict[int, GoogleMatchResult] = {}
    fatal_partial = False
    for index, _candidate in skipped_ahead:
        results[index] = GoogleMatchResult(
            status="skipped_budget",
            place_id=None,
            website_kind="none",
            name_similarity=None,
            address_similarity=None,
            match_distance_m=None,
            warning="skipped_budget",
        )
        stats.skipped_budget += 1

    owns_client = client is None
    http = client or httpx.Client(
        timeout=httpx.Timeout(READ_TIMEOUT_S, connect=CONNECT_TIMEOUT_S),
        headers={"User-Agent": f"customer-finder/{__version__}"},
        follow_redirects=False,
        event_hooks={"request": [_google_request_hook]},
    )

    def work(index: int, candidate: Candidate) -> tuple[int, GoogleMatchResult, int]:
        parts = [
            candidate.raw.name or "",
            candidate.raw.address_freeform or "",
            candidate.raw.locality or "",
        ]
        text_query = ", ".join(p for p in parts if p)
        payload, err, attempts = _post_text_search(
            http,
            api_key=api_key,
            text_query=text_query,
            lat=candidate.raw.lat,
            lon=candidate.raw.lon,
            budget=budget,
            stop=stop,
        )
        if err in {"skipped_budget", "stopped"}:
            return (
                index,
                GoogleMatchResult(
                    status="skipped_budget",
                    place_id=None,
                    website_kind="none",
                    name_similarity=None,
                    address_similarity=None,
                    match_distance_m=None,
                    warning="skipped_budget",
                ),
                attempts,
            )
        if payload is None:
            return (
                index,
                GoogleMatchResult(
                    status="error",
                    place_id=None,
                    website_kind="unknown",
                    name_similarity=None,
                    address_similarity=None,
                    match_distance_m=None,
                    warning=err,
                ),
                attempts,
            )
        matched = match_text_search_response(candidate, payload, config=config)
        return index, matched, attempts

    try:
        with ThreadPoolExecutor(max_workers=MAX_WORKERS) as pool:
            futures = [pool.submit(work, idx, cand) for idx, cand in to_fetch]
            for future in as_completed(futures):
                try:
                    index, result, attempts = future.result()
                except ConfigError:
                    stop.set()
                    for pending in futures:
                        pending.cancel()
                    raise
                except Exception as exc:
                    fatal_partial = True
                    warnings.append(f"google_worker_error:{exc.__class__.__name__}")
                    continue
                stats.http_attempts += attempts
                results[index] = result
                if result.status == "matched":
                    stats.matched += 1
                elif result.status == "ambiguous":
                    stats.ambiguous += 1
                elif result.status == "not_found":
                    stats.not_found += 1
                elif result.status == "skipped_budget":
                    stats.skipped_budget += 1
                else:
                    stats.errors += 1
                    fatal_partial = True
                kind = result.website_kind
                stats.website_kind_counts[kind] = stats.website_kind_counts.get(kind, 0) + 1
    finally:
        if owns_client:
            http.close()

    # Mark any missing as skipped_budget if budget exhausted mid-flight.
    for index, _candidate in ordered:
        if index not in results:
            results[index] = GoogleMatchResult(
                status="skipped_budget",
                place_id=None,
                website_kind="none",
                name_similarity=None,
                address_similarity=None,
                match_distance_m=None,
                warning="skipped_budget",
            )
            stats.skipped_budget += 1

    if fatal_partial and strict:
        raise GoogleEnrichmentError(
            "Google enrichment had candidate errors under --strict; refusing final CSV"
        )

    updated: list[Candidate] = []
    for index, candidate in enumerate(candidates):
        result = results[index]
        if result.status == "matched" and result.place_id:
            updated.append(candidate.model_copy(update={"google_place_id": result.place_id}))
        else:
            updated.append(candidate)
    # Do not log secrets or raw Google payloads.
    logger.info(
        "google enrichment matched=%s ambiguous=%s not_found=%s errors=%s skipped=%s attempts=%s",
        stats.matched,
        stats.ambiguous,
        stats.not_found,
        stats.errors,
        stats.skipped_budget,
        stats.http_attempts,
    )
    return updated, stats, warnings
