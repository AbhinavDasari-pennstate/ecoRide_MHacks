"""Offline tests for app/maps.py: Google is an httpx.MockTransport, the DB test uses local pgserver."""
import json
import os
import re
from pathlib import Path

import httpx
import psycopg
import pytest

from app import config, maps
from app.core import estimate_dist

A, B, C3 = (42.2780, -83.7400), (42.2800, -83.7330), (42.2405, -83.7660)   # Alex, Maya, Meijer


@pytest.fixture(autouse=True)
def clean(monkeypatch):
    maps._dist_mem.clear()
    maps._route_mem.clear()
    monkeypatch.setattr(config, "MAPS_SERVER_KEY", "test-key")
    yield
    maps._dist_mem.clear()
    maps._route_mem.clear()


def mock(monkeypatch, handler):
    """Route every maps HTTP call to handler(request, body); returns the list of requests seen."""
    seen = []

    def wrap(req: httpx.Request):
        seen.append(req)
        out = handler(req, json.loads(req.content) if req.content else None)
        return out if isinstance(out, httpx.Response) else httpx.Response(200, json=out)

    monkeypatch.setattr(maps, "_http", httpx.Client(transport=httpx.MockTransport(wrap)))
    return seen


def matrix_handler(meters=lambda o, d: 1000 * (o + 1) + d):
    """Answers any computeRouteMatrix with every element, omitting zero-valued fields like Google does."""
    def handler(req, body):
        assert req.url == maps.MATRIX_URL
        out = []
        for o in range(len(body["origins"])):
            for d in range(len(body["destinations"])):
                e = {"destinationIndex": d, "distanceMeters": meters(o, d), "duration": "120s",
                     "status": {}, "condition": "ROUTE_EXISTS"}
                if o:
                    e["originIndex"] = o
                out.append(e)
        return out
    return handler


def test_encode_polyline_google_example():
    pts = [(38.5, -120.2), (40.7, -120.95), (43.252, -126.453)]
    assert maps.encode_polyline(pts) == "_p~iF~ps|U_ulLnnqC_mqNvxq`@"


def test_no_key_makes_zero_network_calls(monkeypatch):
    monkeypatch.setattr(config, "MAPS_SERVER_KEY", "")
    seen = mock(monkeypatch, lambda req, body: pytest.fail("network call without a key"))
    m = maps.Maps()
    m.prefetch([A, B, C3])
    assert m.dist(A, B) == pytest.approx(estimate_dist(A, B))
    assert m.dist(A, A) == 0.0
    r = m.route(A, [B], C3)
    assert r["source"] == "estimate" and r["order"] == [0]
    assert r["polyline"] == maps.encode_polyline([A, B, C3])
    assert len(r["legs"]) == 2
    assert r["distance_mi"] == pytest.approx(estimate_dist(A, B) + estimate_dist(B, C3), abs=0.01)
    assert maps.geocode("Meijer Ann Arbor") is None
    assert seen == [] and m.source == "estimate"


def test_matrix_parse_and_request_shape(monkeypatch):
    seen = mock(monkeypatch, matrix_handler())
    m = maps.Maps()
    m.prefetch([A, B])
    assert len(seen) == 1
    req = seen[0]
    assert req.headers["X-Goog-Api-Key"] == "test-key"
    assert req.headers["X-Goog-FieldMask"] == "originIndex,destinationIndex,distanceMeters,duration,condition,status"
    body = json.loads(req.content)
    assert body["travelMode"] == "DRIVE" and "routingPreference" not in body
    assert body["origins"][1] == {"waypoint": {"location": {"latLng": {"latitude": B[0], "longitude": B[1]}}}}
    # origin 0 had originIndex omitted (proto3 default): still parsed as index 0
    assert m.dist(A, B) == pytest.approx(1001 / 1609.344)
    assert m.dist(B, A) == pytest.approx(2000 / 1609.344)
    m.prefetch([A, B])          # fully cached: no new call
    assert len(seen) == 1 and m.source == "google_routes"


def test_route_not_found_falls_back_without_retry(monkeypatch):
    def handler(req, body):
        return [{"destinationIndex": 0, "status": {}, "condition": "ROUTE_NOT_FOUND"}]
    seen = mock(monkeypatch, handler)
    m = maps.Maps()
    assert m.dist(A, B) == pytest.approx(estimate_dist(A, B))
    assert m.dist(A, B) == pytest.approx(estimate_dist(A, B))
    assert len(seen) == 1 and m.source == "estimate"


def test_prefetch_batches_within_625_elements(monkeypatch):
    seen = mock(monkeypatch, matrix_handler(lambda o, d: 5000))
    pts = [(42.20 + i * 0.001, -83.70) for i in range(30)]
    m = maps.Maps()
    m.prefetch(pts)
    sizes = [len(json.loads(r.content)["origins"]) * len(json.loads(r.content)["destinations"]) for r in seen]
    assert len(seen) == 4 and max(sizes) <= 625 and sum(sizes) == 900
    assert m.dist(pts[0], pts[29]) == pytest.approx(5000 / 1609.344)
    assert len(seen) == 4


def test_route_parse_with_optimized_order(monkeypatch):
    def handler(req, body):
        assert req.url == maps.ROUTES_URL
        assert body["optimizeWaypointOrder"] is True and len(body["intermediates"]) == 2
        assert "routingPreference" not in body       # TRAFFIC_AWARE_OPTIMAL can't be combined with optimizing
        return {"routes": [{
            "distanceMeters": 16093, "duration": "900s", "polyline": {"encodedPolyline": "abc"},
            "optimizedIntermediateWaypointIndex": [1, 0],
            "legs": [{"distanceMeters": 1609, "duration": "120s"}, {"distanceMeters": 3218, "duration": "180s"},
                     {"distanceMeters": 11266, "duration": "600s"}],
        }]}
    seen = mock(monkeypatch, handler)
    m = maps.Maps()
    r = m.route(A, [B, (42.2720, -83.7500)], C3)
    mask = seen[0].headers["X-Goog-FieldMask"].split(",")
    for f in ["routes.optimizedIntermediateWaypointIndex", "routes.distanceMeters", "routes.duration",
              "routes.polyline.encodedPolyline", "routes.legs.distanceMeters", "routes.legs.duration"]:
        assert f in mask
    assert r == {"polyline": "abc", "distance_mi": 10.0, "duration_min": 15.0, "order": [1, 0],
                 "legs": [{"distance_mi": 1.0, "duration_min": 2.0}, {"distance_mi": 2.0, "duration_min": 3.0},
                          {"distance_mi": 7.0, "duration_min": 10.0}],
                 "source": "google_routes"}
    r["order"].append(99)                           # callers can't corrupt the cache
    assert m.route(A, [B, (42.2720, -83.7500)], C3)["order"] == [1, 0]
    assert len(seen) == 1


def test_route_without_optimize_is_identity(monkeypatch):
    mock(monkeypatch, lambda req, body: {"routes": [{"distanceMeters": 100, "duration": "60s",
                                                     "polyline": {"encodedPolyline": "x"}, "legs": []}]})
    r = maps.Maps().route(A, [B], C3, optimize=False)
    assert r["order"] == [0] and r["source"] == "google_routes"


@pytest.mark.parametrize("fail", [
    lambda req, body: httpx.Response(500, json={"error": {"message": "boom"}}),
    lambda req, body: httpx.Response(403, json={"error": {"message": "API key test-key not valid"}}),
    lambda req, body: (_ for _ in ()).throw(httpx.ConnectTimeout("slow", request=req)),
    lambda req, body: httpx.Response(200, text="not json"),
])
def test_fallback_on_http_error_or_timeout(monkeypatch, caplog, fail):
    seen = mock(monkeypatch, fail)
    m = maps.Maps()
    m.prefetch([A, B, C3])
    assert m.dist(A, B) == pytest.approx(estimate_dist(A, B))
    r = m.route(A, [B], C3)
    assert r["source"] == "estimate" and r["polyline"] == maps.encode_polyline([A, B, C3])
    assert len(seen) == 1                       # first failure turns the network off for this instance
    assert m.source == "estimate"
    assert "test-key" not in caplog.text


def test_source_transitions(monkeypatch):
    def handler(req, body):   # only A -> B has a route
        o, d = body["origins"][0]["waypoint"]["location"]["latLng"], body["destinations"][0]["waypoint"]["location"]["latLng"]
        ok = (o["latitude"], o["longitude"], d["latitude"], d["longitude"]) == (*A, *B)
        return [{"distanceMeters": 900, "duration": "60s", "status": {},
                 "condition": "ROUTE_EXISTS" if ok else "ROUTE_NOT_FOUND"}]
    mock(monkeypatch, handler)
    m = maps.Maps()
    assert m.source == "estimate"
    m.dist(A, B)
    assert m.source == "google_routes"
    m.dist(A, C3)
    assert m.source == "mixed"


def test_geocode_parse(monkeypatch):
    def handler(req, body):
        assert req.url.params["address"] == "Meijer Ann Arbor"
        assert req.url.params["bounds"].count("|") == 1
        return {"status": "OK", "results": [{"formatted_address": "5645 Jackson Rd, Ann Arbor, MI",
                                              "geometry": {"location": {"lat": 42.29, "lng": -83.82}},
                                              "place_id": "ChIJx"}]}
    mock(monkeypatch, handler)
    assert maps.geocode("Meijer Ann Arbor") == {"lat": 42.29, "lng": -83.82, "place_id": "ChIJx",
                                                "formatted_address": "5645 Jackson Rd, Ann Arbor, MI"}
    mock(monkeypatch, lambda req, body: {"status": "ZERO_RESULTS", "results": []})
    assert maps.geocode("nowhere at all") is None
    mock(monkeypatch, lambda req, body: (_ for _ in ()).throw(httpx.ReadTimeout("slow", request=req)))
    assert maps.geocode("Meijer Ann Arbor") is None


def test_cache_write_failure_on_broken_connection(monkeypatch):
    class Broken:
        def transaction(self):
            raise psycopg.OperationalError("connection is closed")
    mock(monkeypatch, matrix_handler())
    m = maps.Maps(Broken())
    m.prefetch([A, B])
    assert m.dist(A, B) == pytest.approx(1001 / 1609.344)


def test_route_cache_table_roundtrip(monkeypatch, caplog):
    """Real Postgres: writes land in route_cache, a fresh process reads them back, and a failing
    write inside the caller's transaction doesn't abort that transaction."""
    try:
        import pgserver
        uri = pgserver.get_server(os.path.join(os.environ["LOCALAPPDATA"], "campus-rides-pg"), cleanup_mode=None).get_uri()
    except Exception as e:
        pytest.skip(f"local pgserver unavailable: {type(e).__name__}")
    ddl = re.search(r"create table if not exists route_cache .*?\n\);", (Path(__file__).parents[1] / "db" / "schema.sql").read_text(), re.S)
    P, Q = (10.0, 10.0), (10.01, 10.01)          # far from any real data
    with psycopg.connect(uri) as c:
        try:
            c.execute(ddl.group(0))
            mock(monkeypatch, matrix_handler())
            maps.Maps(c).prefetch([P, Q])
            mock(monkeypatch, lambda req, body: {"routes": [{"distanceMeters": 3000, "duration": "300s",
                                                             "polyline": {"encodedPolyline": "pq"}, "legs": [],
                                                             "optimizedIntermediateWaypointIndex": [0]}]})
            maps.Maps(c).route(P, [Q], P)
            # P>Q, Q>P and the route (same-point pairs are never stored)
            assert c.execute("select count(*) from route_cache where key like %s", ("%10.0100,10.0100%",)).fetchone()[0] == 3

            maps._dist_mem.clear()
            maps._route_mem.clear()                   # new process: everything comes from the table
            seen = mock(monkeypatch, lambda req, body: pytest.fail("should be served from route_cache"))
            m = maps.Maps(c)
            assert m.dist(P, Q) == pytest.approx(1001 / 1609.344) and m.source == "google_routes"
            r = m.route(P, [Q], P)
            assert r["order"] == [0] and r["polyline"] == "pq" and r["source"] == "google_routes"
            assert seen == []

            # a temp table shadows route_cache and rejects every insert
            c.execute("create temp table route_cache (key text primary key, distance_mi double precision not null "
                      "check (distance_mi < 0), duration_min double precision not null, polyline text, payload jsonb, "
                      "fetched_at timestamptz not null default now())")
            mock(monkeypatch, matrix_handler())
            m = maps.Maps(c)
            m.prefetch([(10.02, 10.02), (10.03, 10.03)])
            assert m.dist((10.02, 10.02), (10.03, 10.03)) == pytest.approx(1001 / 1609.344)
            assert "route_cache access failed (CheckViolation)" in caplog.text
            assert c.execute("select 1").fetchone()[0] == 1     # caller's transaction still usable
        finally:
            c.rollback()                                       # leave the dev database untouched
