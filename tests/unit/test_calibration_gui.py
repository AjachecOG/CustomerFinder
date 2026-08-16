"""Tests for the localhost calibration review desk."""

from __future__ import annotations

import csv
import json
import threading
import time
from http.client import HTTPConnection
from http.server import ThreadingHTTPServer
from pathlib import Path
from types import SimpleNamespace

import pytest

from customer_finder.calibration import (
    load_calibration_rows,
    prepare_calibration,
    save_calibration_rows,
    update_calibration_review,
)
from customer_finder.calibration_gui import (
    GuiSession,
    display_name,
    make_handler,
    serve_gui,
)
from customer_finder.errors import ArgumentError, ConfigError
from customer_finder.models import SearchRequest


def _write_leads(path: Path, n: int = 25) -> None:
    fields = [
        "overture_id",
        "name",
        "lat",
        "lon",
        "distance_m",
        "category",
        "bucket",
        "score",
        "address",
        "locality",
    ]
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        for i in range(n):
            writer.writerow(
                {
                    "overture_id": f"id{i}",
                    "name": f"Cafe {i}",
                    "lat": "51.1",
                    "lon": "17.0",
                    "distance_m": str(i),
                    "category": "cafe",
                    "bucket": "likely_no_site",
                    "score": str(90 - i),
                    "address": f"ul. {i}",
                    "locality": "Wrocław",
                }
            )


def _session(tmp_path: Path, n: int = 5) -> GuiSession:
    leads = tmp_path / "leads.csv"
    calib = tmp_path / "calibration.csv"
    summary = tmp_path / "calibration.summary.json"
    _write_leads(leads, n)
    prepare_calibration(leads, calib, limit=n)
    return GuiSession(leads_csv=leads, calibration_csv=calib, summary_path=summary, limit=n)


def _passing_review(rank: int) -> dict[str, object]:
    return {
        "rank": rank,
        "entity_status": "valid",
        "target_category": "yes",
        "operating_status_review": "open",
        "independence": "independent",
        "site_status": "no_owned_site",
        "notes": "",
    }


def test_display_name_strips_formula_quote() -> None:
    assert display_name("'=HYPERLINK") == "=HYPERLINK"
    assert display_name("Cafe Alfa") == "Cafe Alfa"


def test_gui_state_lists_empty_reviews(tmp_path: Path) -> None:
    session = _session(tmp_path)
    state = session.snapshot()
    assert state["row_count"] == 5
    assert state["complete_count"] == 0
    assert state["rows"][0]["status"] == "empty"
    assert "google_maps_url" in state["rows"][0]
    assert state["rows"][0]["context"]["locality"] == "Wrocław"
    assert state["defaults"]["overture_release"] == "latest"
    assert state["approval"]["exists"] is False


def test_gui_marks_partial_row_invalid(tmp_path: Path) -> None:
    session = _session(tmp_path, n=2)
    rows = load_calibration_rows(session.calibration_csv)
    rows[0]["entity_status"] = "valid"
    save_calibration_rows(session.calibration_csv, rows)
    assert session.snapshot()["rows"][0]["status"] == "invalid"


def test_gui_corrupt_summary_is_ignored(tmp_path: Path) -> None:
    session = _session(tmp_path, n=1)
    session.summary_path.write_text("{not json", encoding="utf-8")
    assert session.snapshot()["summary"] is None
    session.summary_path.write_bytes(b"\xff\xfe")
    assert session.snapshot()["summary"] is None


def test_gui_save_row_and_evaluate(tmp_path: Path) -> None:
    session = _session(tmp_path, n=20)
    for rank in range(1, 21):
        session.save_row(_passing_review(rank))
    state = session.evaluate()
    assert state["complete_count"] == 20
    assert state["summary"] is not None
    assert state["summary"]["passed"] is True
    assert Path(state["summary"]["approved_path"]).exists()
    assert state["approval"]["valid"] is True


def test_gui_prepare_refuses_to_clobber_reviews(tmp_path: Path) -> None:
    session = _session(tmp_path, n=2)
    session.save_row(_passing_review(1))
    with pytest.raises(ConfigError, match="already has reviews"):
        session.prepare(overwrite=False)
    with pytest.raises(ConfigError, match="already has reviews"):
        session.start_search({})


def test_gui_prepare_overwrite_and_missing_leads(tmp_path: Path) -> None:
    session = _session(tmp_path, n=2)
    session.save_row(_passing_review(1))
    state = session.prepare(overwrite=True)
    assert state["complete_count"] == 0
    session.leads_csv.unlink()
    with pytest.raises(ArgumentError, match="Leads CSV not found"):
        session.prepare(overwrite=True)


def test_update_calibration_review_missing_rank(tmp_path: Path) -> None:
    session = _session(tmp_path, n=1)
    with pytest.raises(ArgumentError, match="rank 9"):
        update_calibration_review(
            session.calibration_csv,
            9,
            entity_status="valid",
            target_category="yes",
            operating_status_review="open",
            independence="independent",
            site_status="owned_site",
        )
    with pytest.raises(ArgumentError, match="not found"):
        update_calibration_review(
            tmp_path / "missing.csv",
            1,
            entity_status="valid",
            target_category="yes",
            operating_status_review="open",
            independence="independent",
            site_status="owned_site",
        )


def test_gui_search_from_parquet_fixture(tmp_path: Path) -> None:
    parquet = Path(__file__).resolve().parents[1] / "fixtures" / "overture_places.parquet"
    session = GuiSession(
        leads_csv=tmp_path / "leads.csv",
        calibration_csv=tmp_path / "calibration.csv",
        summary_path=tmp_path / "calibration.summary.json",
        parquet_path=parquet,
        limit=10,
    )
    session.job = {"status": "running", "message": "hold", "error": None}
    with pytest.raises(ConfigError, match="already running"):
        session.start_search({"confirm_overwrite": True})
    session.job = {"status": "idle", "message": "", "error": None}
    session.start_search(
        {
            "lat": 51.1079,
            "lon": 17.0385,
            "radius_km": 3,
            "categories": "cafe,bakery,pastry,ice_cream",
            "confirm_overwrite": True,
        }
    )
    state = session.snapshot()
    for _ in range(80):
        if state["job"]["status"] != "running":
            break
        time.sleep(0.25)
        state = session.snapshot()
    assert state["job"]["status"] == "done", state["job"]
    assert state["row_count"] > 0


def test_gui_search_passes_explicit_overture_release(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    captured: dict[str, str] = {}

    def fake_run_search(request: SearchRequest, **_kwargs: object) -> SimpleNamespace:
        output_path = request.output_path
        _write_leads(output_path, n=2)
        captured["release"] = request.overture_release
        return SimpleNamespace(
            manifest={"counts": {"output": 2}, "overture_release": captured["release"]}
        )

    monkeypatch.setattr("customer_finder.calibration_gui.run_search", fake_run_search)
    session = GuiSession(
        leads_csv=tmp_path / "leads.csv",
        calibration_csv=tmp_path / "calibration.csv",
        summary_path=tmp_path / "calibration.summary.json",
        overture_release="2026-07-22.0",
        limit=2,
    )

    session._run_search({})

    assert captured["release"] == "2026-07-22.0"
    assert session.snapshot()["job"]["status"] == "done"


def test_gui_search_reports_validation_error(tmp_path: Path) -> None:
    session = GuiSession(
        leads_csv=tmp_path / "leads.csv",
        calibration_csv=tmp_path / "calibration.csv",
        summary_path=tmp_path / "calibration.summary.json",
    )
    session.start_search({"lat": 1.0, "lon": 17.0, "radius_km": 3, "categories": "cafe"})
    state = session.snapshot()
    for _ in range(40):
        if state["job"]["status"] != "running":
            break
        time.sleep(0.05)
        state = session.snapshot()
    assert state["job"]["status"] == "error"
    assert state["job"]["error"]


def test_gui_refuses_non_localhost() -> None:
    session = GuiSession(
        leads_csv=Path("out/leads.csv"),
        calibration_csv=Path("out/calibration.csv"),
        summary_path=Path("out/calibration.summary.json"),
    )
    with pytest.raises(ArgumentError, match="localhost"):
        serve_gui(session, host="0.0.0.0", open_browser=False)


def test_serve_gui_binds_localhost(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    called: dict[str, object] = {}

    class FakeServer:
        def __init__(self, addr: tuple[str, int], _handler: object) -> None:
            called["addr"] = addr

        def serve_forever(self) -> None:
            called["served"] = True

    monkeypatch.setattr("customer_finder.calibration_gui.ThreadingHTTPServer", FakeServer)
    monkeypatch.setattr(
        "customer_finder.calibration_gui.open_browser_tab",
        lambda url: called.setdefault("url", url),
    )
    session = _session(tmp_path, n=1)
    serve_gui(session, host="127.0.0.1", port=8765, open_browser=True)
    assert called["addr"] == ("127.0.0.1", 8765)
    assert called["served"] is True
    assert called["url"] == "http://127.0.0.1:8765/"


def _http_json(
    conn: HTTPConnection, method: str, path: str, body: dict[str, object] | None = None
) -> tuple[int, dict[str, object]]:
    raw = json.dumps(body).encode("utf-8") if body is not None else None
    headers = {"Content-Type": "application/json"} if raw is not None else {}
    conn.request(method, path, body=raw, headers=headers)
    response = conn.getresponse()
    payload = json.loads(response.read().decode("utf-8"))
    assert isinstance(payload, dict)
    return response.status, payload


def test_gui_http_state_and_html(tmp_path: Path) -> None:
    session = _session(tmp_path, n=2)
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), make_handler(session))
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    try:
        port = int(httpd.server_address[1])
        conn = HTTPConnection("127.0.0.1", port, timeout=5)
        status, payload = _http_json(conn, "GET", "/api/state")
        assert status == 200
        assert payload["row_count"] == 2
        conn.request("GET", "/")
        page_response = conn.getresponse()
        assert page_response.getheader("X-Content-Type-Options") == "nosniff"
        assert page_response.getheader("X-Frame-Options") == "DENY"
        assert "connect-src 'self'" in str(page_response.getheader("Content-Security-Policy"))
        page = page_response.read().decode("utf-8")
        assert "btn-save-next" in page
        assert "field-site_status-owned_site" in page
        assert 'api("/api/evaluate", {})' in page
        assert 'id="overture-release"' in page
        assert "innerHTML" not in page
        status, saved = _http_json(conn, "POST", "/api/row", _passing_review(1))
        assert status == 200
        assert saved["complete_count"] == 1
        status, saved = _http_json(conn, "POST", "/api/row", _passing_review(2))
        assert status == 200
        status, evaluated = _http_json(conn, "POST", "/api/evaluate", {})
        assert status == 400
        assert "Need at least 20" in str(evaluated["error"])
        status, missing = _http_json(conn, "POST", "/api/nope", {})
        assert status == 404
        status, missing_get = _http_json(conn, "GET", "/missing")
        assert missing_get["error"] == "not found"
        status, prepared = _http_json(conn, "POST", "/api/prepare", {"confirm_overwrite": True})
        assert status == 200
        assert prepared["complete_count"] == 0
        conn.request(
            "POST", "/api/row", body=b"not-json", headers={"Content-Type": "application/json"}
        )
        bad = conn.getresponse()
        assert bad.status == 400
        bad.read()
        conn.close()
        conn = HTTPConnection("127.0.0.1", port, timeout=5)
        conn.request("POST", "/api/row", body=b"{}", headers={"Content-Type": "text/plain"})
        wrong_type = conn.getresponse()
        assert wrong_type.status == 400
        wrong_type_payload = json.loads(wrong_type.read().decode("utf-8"))
        assert "Content-Type application/json" in wrong_type_payload["error"]
        conn.close()

        conn = HTTPConnection("127.0.0.1", port, timeout=5)
        conn.request("GET", "/api/state", headers={"Host": "evil.example"})
        hostile_host = conn.getresponse()
        assert hostile_host.status == 403
        hostile_host.read()
        conn.close()

        conn = HTTPConnection("127.0.0.1", port, timeout=5)
        conn.request(
            "POST",
            "/api/row",
            body=json.dumps(_passing_review(1)).encode("utf-8"),
            headers={
                "Content-Type": "application/json",
                "Origin": "https://evil.example",
            },
        )
        hostile_origin = conn.getresponse()
        assert hostile_origin.status == 403
        hostile_origin.read()
        conn.close()
    finally:
        httpd.shutdown()
        httpd.server_close()


def test_gui_save_does_not_fetch_maps(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    import httpx

    def boom(
        self: httpx.Client,
        method: str,
        url: httpx.URL | str,
        *args: object,
        **kwargs: object,
    ) -> httpx.Response:
        raise AssertionError(f"review desk requested {url}")

    monkeypatch.setattr(httpx.Client, "request", boom)
    session = _session(tmp_path, n=1)
    saved = session.save_row(_passing_review(1))
    assert saved["complete_count"] == 1
    assert "google_maps_url" in saved["rows"][0]
    maps_url = str(saved["rows"][0]["google_maps_url"])
    assert maps_url.startswith("https://www.google.com/maps/search/")
