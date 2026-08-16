"""Localhost review desk for Milestone 5 calibration (no extra dependencies)."""

from __future__ import annotations

import csv
import json
import logging
import threading
from dataclasses import dataclass, field
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from importlib.resources import files
from pathlib import Path
from typing import Any
from urllib.parse import urlparse
from webbrowser import open as open_browser_tab

from pydantic import ValidationError

from customer_finder.calibration import (
    REVIEW_FIELDS,
    approval_path_for_summary,
    evaluate_calibration,
    inspect_calibration_approval,
    is_complete_review_row,
    load_calibration_rows,
    prepare_calibration,
    update_calibration_review,
)
from customer_finder.errors import ArgumentError, ConfigError, CustomerFinderError
from customer_finder.models import SearchRequest
from customer_finder.pipeline import run_search

logger = logging.getLogger(__name__)

DEFAULT_LAT = 51.1079
DEFAULT_LON = 17.0385
DEFAULT_RADIUS_KM = 3.0
DEFAULT_CATEGORIES = "cafe,bakery,pastry,ice_cream"
DEFAULT_OVERTURE_RELEASE = "latest"
MAX_JSON_BODY_BYTES = 64 * 1024
LOCAL_GUI_HOSTS = frozenset({"127.0.0.1", "localhost", "::1"})
LEAD_CONTEXT_FIELDS = (
    "address",
    "locality",
    "category",
    "bucket",
    "score",
    "owned_domains",
    "socials",
    "aggregators",
    "is_chain",
    "operating_status",
    "brand_name",
    "phones",
)


def display_name(name: str) -> str:
    """Strip CSV formula quoting for on-screen labels only."""
    if name.startswith("'") and name[1:2] in {"=", "+", "-", "@"}:
        return name[1:]
    return name


def _row_status(row: dict[str, str]) -> str:
    try:
        if is_complete_review_row(row):
            return "complete"
    except ConfigError:
        return "invalid"
    if any((row.get(field) or "").strip() for field in REVIEW_FIELDS):
        return "invalid"
    return "empty"


def _has_saved_reviews(rows: list[dict[str, str]]) -> bool:
    return any((row.get(field) or "").strip() for row in rows for field in REVIEW_FIELDS)


def load_leads_context(leads_csv: Path) -> dict[str, dict[str, str]]:
    """Index extra lead columns by overture_id for the review card."""
    if not leads_csv.is_file():
        return {}
    index: dict[str, dict[str, str]] = {}
    with leads_csv.open(encoding="utf-8-sig", newline="") as handle:
        for row in csv.DictReader(handle):
            oid = row.get("overture_id") or ""
            if not oid:
                continue
            index[oid] = {field: row.get(field) or "" for field in LEAD_CONTEXT_FIELDS}
    return index


def build_gui_state(
    *,
    leads_csv: Path,
    calibration_csv: Path,
    summary_path: Path,
    job: dict[str, Any],
    overture_release: str = DEFAULT_OVERTURE_RELEASE,
) -> dict[str, Any]:
    rows = load_calibration_rows(calibration_csv)
    context = load_leads_context(leads_csv)
    payload_rows: list[dict[str, Any]] = []
    complete = 0
    for row in rows:
        status = _row_status(row)
        if status == "complete":
            complete += 1
        extra = context.get(row.get("overture_id") or "", {})
        payload_rows.append(
            {
                **row,
                "display_name": display_name(row.get("name") or ""),
                "status": status,
                "context": extra,
            }
        )
    summary: dict[str, Any] | None = None
    if summary_path.is_file():
        try:
            loaded = json.loads(summary_path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError):
            loaded = None
        if isinstance(loaded, dict):
            summary = loaded
    approval = inspect_calibration_approval(approval_path_for_summary(summary_path))
    if (
        summary is not None
        and approval["valid"]
        and Path(str(approval["summary_json"])).resolve() == summary_path.resolve()
    ):
        summary = {**summary, "approved_path": approval["path"]}
    return {
        "leads_csv": str(leads_csv),
        "calibration_csv": str(calibration_csv),
        "summary_path": str(summary_path),
        "leads_exists": leads_csv.is_file(),
        "calibration_exists": calibration_csv.is_file(),
        "row_count": len(payload_rows),
        "complete_count": complete,
        "has_saved_reviews": _has_saved_reviews(rows),
        "rows": payload_rows,
        "job": job,
        "summary": summary,
        "approval": approval,
        "defaults": {
            "lat": DEFAULT_LAT,
            "lon": DEFAULT_LON,
            "radius_km": DEFAULT_RADIUS_KM,
            "categories": DEFAULT_CATEGORIES,
            "overture_release": overture_release,
        },
    }


@dataclass
class GuiSession:
    leads_csv: Path
    calibration_csv: Path
    summary_path: Path
    overture_release: str = DEFAULT_OVERTURE_RELEASE
    parquet_path: Path | None = None
    limit: int = 30
    _lock: threading.Lock = field(default_factory=threading.Lock)
    job: dict[str, Any] | None = None

    def __post_init__(self) -> None:
        if self.job is None:
            self.job = {"status": "idle", "message": "", "error": None}

    def snapshot(self) -> dict[str, Any]:
        with self._lock:
            job = dict(self.job or {})
        return build_gui_state(
            leads_csv=self.leads_csv,
            calibration_csv=self.calibration_csv,
            summary_path=self.summary_path,
            job=job,
            overture_release=self.overture_release,
        )

    def prepare(self, *, overwrite: bool) -> dict[str, Any]:
        if not self.leads_csv.is_file():
            raise ArgumentError(f"Leads CSV not found: {self.leads_csv}")
        existing = load_calibration_rows(self.calibration_csv)
        if _has_saved_reviews(existing) and not overwrite:
            raise ConfigError(
                "Calibration already has reviews; set confirm_overwrite true to replace them"
            )
        prepare_calibration(
            self.leads_csv,
            self.calibration_csv,
            limit=self.limit,
            overwrite=True,
        )
        return self.snapshot()

    def save_row(self, body: dict[str, Any]) -> dict[str, Any]:
        rank = int(body["rank"])
        update_calibration_review(
            self.calibration_csv,
            rank,
            entity_status=str(body["entity_status"]),
            target_category=str(body["target_category"]),
            operating_status_review=str(body["operating_status_review"]),
            independence=str(body["independence"]),
            site_status=str(body["site_status"]),
            notes=str(body.get("notes") or "") or None,
        )
        return self.snapshot()

    def evaluate(self) -> dict[str, Any]:
        evaluate_calibration(self.calibration_csv, self.summary_path)
        return self.snapshot()

    def start_search(self, body: dict[str, Any]) -> dict[str, Any]:
        with self._lock:
            if (self.job or {}).get("status") == "running":
                raise ConfigError("Search already running")
            existing = load_calibration_rows(self.calibration_csv)
            if _has_saved_reviews(existing) and not bool(body.get("confirm_overwrite")):
                raise ConfigError(
                    "Calibration already has reviews; set confirm_overwrite true to replace them"
                )
            self.job = {
                "status": "running",
                "message": "Searching Overture Places (first run may download DuckDB extensions)…",
                "error": None,
            }
        thread = threading.Thread(target=self._run_search, args=(body,), daemon=True)
        thread.start()
        return self.snapshot()

    def _run_search(self, body: dict[str, Any]) -> None:
        try:
            request = SearchRequest.model_validate(
                {
                    "lat": float(body.get("lat", DEFAULT_LAT)),
                    "lon": float(body.get("lon", DEFAULT_LON)),
                    "radius_km": float(body.get("radius_km", DEFAULT_RADIUS_KM)),
                    "categories": str(body.get("categories") or DEFAULT_CATEGORIES),
                    "output_path": self.leads_csv,
                    "overture_release": str(body.get("overture_release") or self.overture_release),
                    "overwrite": True,
                }
            )
            parquet = str(self.parquet_path) if self.parquet_path is not None else None
            result = run_search(request, parquet_path=parquet)
            prepare_calibration(
                self.leads_csv,
                self.calibration_csv,
                limit=self.limit,
                overwrite=True,
            )
            counts = result.manifest.get("counts", {})
            message = (
                f"Search done. rows={counts.get('output', 0)} "
                f"release={result.manifest.get('overture_release')}"
            )
            with self._lock:
                self.job = {"status": "done", "message": message, "error": None}
        except (CustomerFinderError, ValidationError, ValueError) as exc:
            logger.exception("Calibration GUI search failed")
            with self._lock:
                self.job = {"status": "error", "message": "", "error": str(exc)}
        except Exception as exc:
            logger.exception("Calibration GUI search crashed")
            with self._lock:
                self.job = {
                    "status": "error",
                    "message": "",
                    "error": f"Unexpected error ({type(exc).__name__})",
                }


def _read_html() -> bytes:
    return files("customer_finder").joinpath("static/calibration.html").read_bytes()


def make_handler(session: GuiSession) -> type[BaseHTTPRequestHandler]:
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, fmt: str, *args: object) -> None:
            logger.info("%s - %s", self.address_string(), fmt % args)

        def _send(self, code: int, body: bytes, content_type: str) -> None:
            self.send_response(code)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("Referrer-Policy", "no-referrer")
            self.send_header("X-Frame-Options", "DENY")
            self.send_header("Cross-Origin-Resource-Policy", "same-origin")
            self.send_header("Permissions-Policy", "camera=(), geolocation=(), microphone=()")
            self.send_header(
                "Content-Security-Policy",
                "default-src 'none'; script-src 'unsafe-inline'; "
                "style-src 'unsafe-inline'; connect-src 'self'; img-src 'self' data:; "
                "base-uri 'none'; form-action 'none'; frame-ancestors 'none'",
            )
            self.end_headers()
            self.wfile.write(body)

        def _send_json(self, code: int, payload: dict[str, Any]) -> None:
            body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
            self._send(code, body, "application/json; charset=utf-8")

        def _read_json(self) -> dict[str, Any]:
            length = int(self.headers.get("Content-Length") or "0")
            if length < 0 or length > MAX_JSON_BODY_BYTES:
                raise ConfigError(f"JSON request body exceeds {MAX_JSON_BODY_BYTES} bytes")
            raw = self.rfile.read(length) if length else b"{}"
            content_type = (self.headers.get("Content-Type") or "").lower()
            if not content_type.startswith("application/json"):
                raise ConfigError("POST requests require Content-Type application/json")
            data = json.loads(raw.decode("utf-8") or "{}")
            if not isinstance(data, dict):
                raise ConfigError("JSON body must be an object")
            return data

        def _is_local_request(self, *, require_same_origin: bool) -> bool:
            host_header = self.headers.get("Host") or ""
            host = urlparse(f"//{host_header}").hostname
            if host not in LOCAL_GUI_HOSTS:
                return False
            origin = self.headers.get("Origin")
            if not require_same_origin or not origin:
                return True
            parsed_origin = urlparse(origin)
            return (
                parsed_origin.scheme == "http"
                and parsed_origin.netloc.lower() == host_header.lower()
            )

        def do_GET(self) -> None:
            if not self._is_local_request(require_same_origin=False):
                self._send_json(403, {"error": "localhost Host header required"})
                return
            path = urlparse(self.path).path
            if path in {"/", "/index.html"}:
                self._send(200, _read_html(), "text/html; charset=utf-8")
                return
            if path == "/api/state":
                self._send_json(200, session.snapshot())
                return
            self._send_json(404, {"error": "not found"})

        def do_POST(self) -> None:
            if not self._is_local_request(require_same_origin=True):
                self._send_json(403, {"error": "same-origin localhost request required"})
                return
            path = urlparse(self.path).path
            try:
                body = self._read_json()
                if path == "/api/search":
                    self._send_json(200, session.start_search(body))
                    return
                if path == "/api/prepare":
                    self._send_json(
                        200,
                        session.prepare(overwrite=bool(body.get("confirm_overwrite"))),
                    )
                    return
                if path == "/api/row":
                    self._send_json(200, session.save_row(body))
                    return
                if path == "/api/evaluate":
                    self._send_json(200, session.evaluate())
                    return
                self._send_json(404, {"error": "not found"})
            except CustomerFinderError as exc:
                self._send_json(400, {"error": exc.message, "exit_code": exc.exit_code})
            except (ValidationError, json.JSONDecodeError, KeyError, TypeError, ValueError) as exc:
                self._send_json(400, {"error": str(exc)})

    return Handler


def serve_gui(
    session: GuiSession,
    *,
    host: str = "127.0.0.1",
    port: int = 8765,
    open_browser: bool = True,
) -> None:
    if host not in LOCAL_GUI_HOSTS:
        raise ArgumentError("Calibration GUI must bind to localhost")
    httpd = ThreadingHTTPServer((host, port), make_handler(session))
    url = f"http://127.0.0.1:{port}/"
    logger.info("Calibration GUI at %s", url)
    if open_browser:
        open_browser_tab(url)
    httpd.serve_forever()
