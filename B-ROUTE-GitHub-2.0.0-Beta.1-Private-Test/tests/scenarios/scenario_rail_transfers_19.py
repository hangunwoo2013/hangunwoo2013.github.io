"""B-ROUTE 1.9 rail transfer graph regression tests (synthetic GTFS; no live API)."""
from __future__ import annotations

import csv
import importlib.util
import io
import os
import sys
import tempfile
import zipfile
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def load_api(tag: str):
    tmp = Path(tempfile.mkdtemp(prefix=f"broute19-{tag}-"))
    os.environ.update({
        "APP_ENV": "development",
        "DATA_DIR": str(tmp / "data"),
        "DATABASE_PATH": str(tmp / "data" / "test.sqlite3"),
        "APP_TIMEZONE": "Asia/Seoul",
        "APP_ORIGIN": "https://testserver",
        "GOOGLE_ADMIN_EMAIL": "owner@example.com",
        "GOOGLE_CLIENT_ID": "dummy-client",
        "SESSION_SECRET": "t" * 48,
        "DATA_GO_KR_SERVICE_KEY": "",
    })
    path = ROOT / "cloud-functions" / "api" / "index.py"
    spec = importlib.util.spec_from_file_location(f"broute19_{tag}_api", path)
    api = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = api
    spec.loader.exec_module(api)
    api.init_db()
    return api, tmp


def make_gtfs_zip(stops, trips, stop_times, transfers=None, pathways=None):
    files = {
        "agency.txt": [
            {"agency_id": "AG", "agency_name": "테스트 철도", "agency_url": "https://example.test", "agency_timezone": "Asia/Seoul"}
        ],
        "stops.txt": stops,
        "routes.txt": [
            {"route_id": "R1", "route_short_name": "1호선", "route_long_name": "테스트 1호선", "route_type": "1"},
            {"route_id": "R2", "route_short_name": "2호선", "route_long_name": "테스트 2호선", "route_type": "1"},
        ],
        "trips.txt": trips,
        "stop_times.txt": stop_times,
        "calendar.txt": [
            {"service_id": "WK", "monday": "0", "tuesday": "1", "wednesday": "0", "thursday": "0", "friday": "0", "saturday": "0", "sunday": "0", "start_date": "20261124", "end_date": "20261124"}
        ],
    }
    if transfers is not None:
        files["transfers.txt"] = transfers
    if pathways is not None:
        files["pathways.txt"] = pathways
    out = io.BytesIO()
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as zf:
        for filename, rows in files.items():
            columns = list(dict.fromkeys(k for row in rows for k in row.keys()))
            text = io.StringIO()
            writer = csv.DictWriter(text, fieldnames=columns, lineterminator="\n")
            writer.writeheader()
            writer.writerows(rows)
            zf.writestr(filename, text.getvalue())
    return out.getvalue()


def base_stops_station():
    return [
        {"stop_id": "A", "stop_name": "출발역", "stop_lat": "37.0000", "stop_lon": "127.0000", "location_type": "0"},
        {"stop_id": "STN", "stop_name": "환승역", "stop_lat": "37.0010", "stop_lon": "127.0000", "location_type": "1"},
        {"stop_id": "P1", "stop_name": "1호선 승강장", "stop_lat": "37.0010", "stop_lon": "127.0000", "parent_station": "STN", "location_type": "0", "platform_code": "1"},
        {"stop_id": "P2", "stop_name": "2호선 승강장", "stop_lat": "37.0012", "stop_lon": "127.0000", "parent_station": "STN", "location_type": "0", "platform_code": "2"},
        {"stop_id": "D", "stop_name": "도착역", "stop_lat": "37.0020", "stop_lon": "127.0000", "location_type": "0"},
    ]


def route(api, start, end, depart="2026-11-24T08:50:00+09:00"):
    return api.transit_leg(
        api.Waypoint(name="출발", lat=start[0], lon=start[1]),
        api.Waypoint(name="도착", lat=end[0], lon=end[1]),
        datetime.fromisoformat(depart), 80, "fast", None, mode="rail"
    )


# 1. Stop-pair transfer rule at the parent station must apply to child platforms.
api, _ = load_api("min-transfer")
blob = make_gtfs_zip(
    base_stops_station(),
    [
        {"route_id": "R1", "service_id": "WK", "trip_id": "T1"},
        {"route_id": "R2", "service_id": "WK", "trip_id": "T2_EARLY"},
        {"route_id": "R2", "service_id": "WK", "trip_id": "T2_OK"},
    ],
    [
        {"trip_id": "T1", "arrival_time": "09:00:00", "departure_time": "09:00:00", "stop_id": "A", "stop_sequence": "1"},
        {"trip_id": "T1", "arrival_time": "09:10:00", "departure_time": "09:10:00", "stop_id": "P1", "stop_sequence": "2"},
        {"trip_id": "T2_EARLY", "arrival_time": "09:18:00", "departure_time": "09:18:00", "stop_id": "P2", "stop_sequence": "1"},
        {"trip_id": "T2_EARLY", "arrival_time": "09:30:00", "departure_time": "09:30:00", "stop_id": "D", "stop_sequence": "2"},
        {"trip_id": "T2_OK", "arrival_time": "09:21:00", "departure_time": "09:21:00", "stop_id": "P2", "stop_sequence": "1"},
        {"trip_id": "T2_OK", "arrival_time": "09:33:00", "departure_time": "09:33:00", "stop_id": "D", "stop_sequence": "2"},
    ],
    transfers=[{"from_stop_id": "STN", "to_stop_id": "STN", "transfer_type": "2", "min_transfer_time": "600"}],
    pathways=[{"pathway_id": "P1-P2", "from_stop_id": "P1", "to_stop_id": "P2", "pathway_mode": "1", "is_bidirectional": "1", "length": "50", "traversal_time": "120"}],
)
validation = api.validate_gtfs_bytes(blob)
assert validation["valid"], validation["errors"]
imported = api.import_gtfs_bytes(blob, "rail-min-transfer.zip")
result = route(api, (37.0000, 127.0000), (37.0020, 127.0000))
assert result is not None
rail = [s for s in result["steps"] if s.get("mode") == "rail"]
walk = [s for s in result["steps"] if s.get("mode") == "walk"]
assert [s["trip_id"] for s in rail] == ["T1", "T2_OK"], [s.get("trip_id") for s in rail]
assert len(walk) >= 1 and any("1호선 승강장" in (s.get("from", "") + s.get("to", "")) or "2호선 승강장" in (s.get("from", "") + s.get("to", "")) for s in walk)
assert result["transfers"] == 1
assert result["gtfs_transfer_rules_applied"] == 1
assert rail[-1]["departure_time"] == "09:21"

# 2. Explicit prohibited transfer_type=3 must block the connection.
api2, _ = load_api("prohibited")
blob2 = make_gtfs_zip(
    base_stops_station(),
    [{"route_id": "R1", "service_id": "WK", "trip_id": "T1"}, {"route_id": "R2", "service_id": "WK", "trip_id": "T2"}],
    [
        {"trip_id": "T1", "arrival_time": "09:00:00", "departure_time": "09:00:00", "stop_id": "A", "stop_sequence": "1"},
        {"trip_id": "T1", "arrival_time": "09:10:00", "departure_time": "09:10:00", "stop_id": "P1", "stop_sequence": "2"},
        {"trip_id": "T2", "arrival_time": "09:20:00", "departure_time": "09:20:00", "stop_id": "P2", "stop_sequence": "1"},
        {"trip_id": "T2", "arrival_time": "09:30:00", "departure_time": "09:30:00", "stop_id": "D", "stop_sequence": "2"},
    ],
    transfers=[{"from_stop_id": "P1", "to_stop_id": "P2", "transfer_type": "3"}],
    pathways=[{"pathway_id": "P1-P2", "from_stop_id": "P1", "to_stop_id": "P2", "pathway_mode": "1", "is_bidirectional": "1", "traversal_time": "60"}],
)
assert api2.validate_gtfs_bytes(blob2)["valid"]
api2.import_gtfs_bytes(blob2, "rail-prohibited.zip")
assert route(api2, (37.0000,127.0000), (37.0020,127.0000)) is None

# 3. Linked transfer_type=4 keeps passengers on the same vehicle and does not count a transfer.
api3, _ = load_api("inseat")
stops3 = [
    {"stop_id": "A", "stop_name": "출발", "stop_lat": "37.0000", "stop_lon": "127.0000", "location_type": "0"},
    {"stop_id": "X", "stop_name": "연결역", "stop_lat": "37.0010", "stop_lon": "127.0000", "location_type": "0"},
    {"stop_id": "D", "stop_name": "도착", "stop_lat": "37.0020", "stop_lon": "127.0000", "location_type": "0"},
]
blob3 = make_gtfs_zip(
    stops3,
    [{"route_id": "R1", "service_id": "WK", "trip_id": "T1"}, {"route_id": "R2", "service_id": "WK", "trip_id": "T2"}],
    [
        {"trip_id": "T1", "arrival_time": "09:00:00", "departure_time": "09:00:00", "stop_id": "A", "stop_sequence": "1"},
        {"trip_id": "T1", "arrival_time": "09:10:00", "departure_time": "09:10:00", "stop_id": "X", "stop_sequence": "2"},
        {"trip_id": "T2", "arrival_time": "09:10:00", "departure_time": "09:10:00", "stop_id": "X", "stop_sequence": "1"},
        {"trip_id": "T2", "arrival_time": "09:20:00", "departure_time": "09:20:00", "stop_id": "D", "stop_sequence": "2"},
    ],
    transfers=[{"from_stop_id": "X", "to_stop_id": "X", "from_trip_id": "T1", "to_trip_id": "T2", "transfer_type": "4"}],
)
assert api3.validate_gtfs_bytes(blob3)["valid"]
api3.import_gtfs_bytes(blob3, "rail-in-seat.zip")
result3 = route(api3, (37.0000,127.0000), (37.0020,127.0000))
assert result3 is not None
assert result3["transfers"] == 0
assert result3["gtfs_transfer_rules_applied"] == 1
assert [s["transfer_rule_type"] for s in result3["steps"] if s.get("mode") == "rail" and "transfer_rule_type" in s] == [4]

# 3b. Linked in-seat trips may use different stop IDs when they are adjacent
# platform records in the same station; the passenger must not be forced to walk.
api3b, _ = load_api("inseat-different-platform-ids")
stops3b = [
    {"stop_id": "A", "stop_name": "출발", "stop_lat": "37.0000", "stop_lon": "127.0000", "location_type": "0"},
    {"stop_id": "STN", "stop_name": "연결역", "stop_lat": "37.0010", "stop_lon": "127.0000", "location_type": "1"},
    {"stop_id": "P1", "stop_name": "1번 승강장", "stop_lat": "37.0010", "stop_lon": "127.0000", "location_type": "0", "parent_station": "STN"},
    {"stop_id": "P2", "stop_name": "2번 승강장", "stop_lat": "37.0011", "stop_lon": "127.0000", "location_type": "0", "parent_station": "STN"},
    {"stop_id": "D", "stop_name": "도착", "stop_lat": "37.0020", "stop_lon": "127.0000", "location_type": "0"},
]
blob3b = make_gtfs_zip(
    stops3b,
    [{"route_id": "R1", "service_id": "WK", "trip_id": "T1"}, {"route_id": "R2", "service_id": "WK", "trip_id": "T2"}],
    [
        {"trip_id": "T1", "arrival_time": "09:00:00", "departure_time": "09:00:00", "stop_id": "A", "stop_sequence": "1"},
        {"trip_id": "T1", "arrival_time": "09:10:00", "departure_time": "09:10:00", "stop_id": "P1", "stop_sequence": "2"},
        {"trip_id": "T2", "arrival_time": "09:10:00", "departure_time": "09:10:00", "stop_id": "P2", "stop_sequence": "1"},
        {"trip_id": "T2", "arrival_time": "09:20:00", "departure_time": "09:20:00", "stop_id": "D", "stop_sequence": "2"},
    ],
    transfers=[{"from_stop_id": "P1", "to_stop_id": "P2", "from_trip_id": "T1", "to_trip_id": "T2", "transfer_type": "4"}],
)
assert api3b.validate_gtfs_bytes(blob3b)["valid"]
api3b.import_gtfs_bytes(blob3b, "rail-inseat-platforms.zip")
result3b = route(api3b, (37.0000,127.0000), (37.0020,127.0000))
assert result3b is not None, "linked in-seat trip across adjacent platform IDs should work"
assert result3b["transfers"] == 0
assert [s["mode"] for s in result3b["steps"] if s["mode"] == "rail"] == ["rail", "rail"]
assert not any(s.get("mode") == "walk" and s.get("source") == "GTFS pathways" for s in result3b["steps"])

# Linked trip rules must not allow a passenger to jump onto the next trip at
# an intermediate stop; they apply only at the incoming last/outgoing first stop.
api3c, _ = load_api("inseat-boundary-only")
stops3c = [
    {"stop_id": "A", "stop_name": "출발", "stop_lat": "37.0000", "stop_lon": "127.0000", "location_type": "0"},
    {"stop_id": "X", "stop_name": "중간역", "stop_lat": "37.0010", "stop_lon": "127.0000", "location_type": "0"},
    {"stop_id": "D", "stop_name": "기존 노선 종점", "stop_lat": "37.0020", "stop_lon": "127.0000", "location_type": "0"},
    {"stop_id": "E", "stop_name": "다른 노선 도착", "stop_lat": "37.0030", "stop_lon": "127.0000", "location_type": "0"},
]
blob3c = make_gtfs_zip(
    stops3c,
    [{"route_id": "R1", "service_id": "WK", "trip_id": "T1"}, {"route_id": "R2", "service_id": "WK", "trip_id": "T2"}],
    [
        {"trip_id": "T1", "arrival_time": "09:00:00", "departure_time": "09:00:00", "stop_id": "A", "stop_sequence": "1"},
        {"trip_id": "T1", "arrival_time": "09:05:00", "departure_time": "09:05:00", "stop_id": "X", "stop_sequence": "2"},
        {"trip_id": "T1", "arrival_time": "09:10:00", "departure_time": "09:10:00", "stop_id": "D", "stop_sequence": "3"},
        {"trip_id": "T2", "arrival_time": "09:05:00", "departure_time": "09:05:00", "stop_id": "X", "stop_sequence": "1"},
        {"trip_id": "T2", "arrival_time": "09:15:00", "departure_time": "09:15:00", "stop_id": "E", "stop_sequence": "2"},
    ],
    transfers=[{"from_stop_id": "X", "to_stop_id": "X", "from_trip_id": "T1", "to_trip_id": "T2", "transfer_type": "4"}],
)
assert api3c.validate_gtfs_bytes(blob3c)["valid"]
api3c.import_gtfs_bytes(blob3c, "rail-inseat-intermediate.zip")
assert route(api3c, (37.0000,127.0000), (37.0030,127.0000)) is None

# 4. Linked transfer_type=5 requires alighting/reboarding and applies a conservative 4-minute floor.
api4, _ = load_api("must-reboard")
blob4 = make_gtfs_zip(
    stops3,
    [{"route_id": "R1", "service_id": "WK", "trip_id": "T1"}, {"route_id": "R2", "service_id": "WK", "trip_id": "T2"}],
    [
        {"trip_id": "T1", "arrival_time": "09:00:00", "departure_time": "09:00:00", "stop_id": "A", "stop_sequence": "1"},
        {"trip_id": "T1", "arrival_time": "09:10:00", "departure_time": "09:10:00", "stop_id": "X", "stop_sequence": "2"},
        {"trip_id": "T2", "arrival_time": "09:12:00", "departure_time": "09:12:00", "stop_id": "X", "stop_sequence": "1"},
        {"trip_id": "T2", "arrival_time": "09:22:00", "departure_time": "09:22:00", "stop_id": "D", "stop_sequence": "2"},
    ],
    transfers=[{"from_trip_id": "T1", "to_trip_id": "T2", "transfer_type": "5"}],
)
assert api4.validate_gtfs_bytes(blob4)["valid"]
api4.import_gtfs_bytes(blob4, "rail-reboard-too-early.zip")
assert route(api4, (37.0000,127.0000), (37.0020,127.0000)) is None

# 5. Specificity precedence follows GTFS order: both trips > trip+route > one trip > routes.
api5, _ = load_api("specificity")
rules = [
    {"from_trip_id":"T1", "to_route_id":"R2", "transfer_type":2},
    {"from_trip_id":"T1", "transfer_type":0},
    {"from_trip_id":"T1", "to_trip_id":"T2", "transfer_type":3},
]
best = api5._best_gtfs_transfer_rule(rules, "T1", "T2", "R1", "R2")
assert best is rules[2] and best["transfer_type"] == 3


# GTFS validation must reject transfer rules referencing an entrance as a stop pair.
api_bad_transfer, _ = load_api("bad-transfer-location")
bad_transfer_blob = make_gtfs_zip(
    [
        {"stop_id": "STN", "stop_name": "역", "stop_lat": "37.0", "stop_lon": "127.0", "location_type": "1"},
        {"stop_id": "ENT", "stop_name": "출입구", "stop_lat": "37.0", "stop_lon": "127.0", "location_type": "2", "parent_station": "STN"},
        {"stop_id": "PLAT", "stop_name": "승강장", "stop_lat": "37.0", "stop_lon": "127.0", "location_type": "0", "parent_station": "STN"},
    ],
    [{"route_id": "R1", "service_id": "WK", "trip_id": "T1"}],
    [{"trip_id": "T1", "arrival_time": "09:00:00", "departure_time": "09:00:00", "stop_id": "PLAT", "stop_sequence": "1"}],
    transfers=[{"from_stop_id": "ENT", "to_stop_id": "PLAT", "transfer_type": "2", "min_transfer_time": "60"}],
)
bad_transfer_validation = api_bad_transfer.validate_gtfs_bytes(bad_transfer_blob)
assert not bad_transfer_validation["valid"]
assert any("transfer_type" in error and "위치 유형" in error for error in bad_transfer_validation["errors"])

# Exit gates are one-way; a bidirectional mode-7 pathway is invalid GTFS.
api_bad_gate, _ = load_api("bad-exit-gate")
bad_gate_blob = make_gtfs_zip(
    [
        {"stop_id": "A", "stop_name": "A", "stop_lat": "37.0", "stop_lon": "127.0", "location_type": "0"},
        {"stop_id": "D", "stop_name": "D", "stop_lat": "37.001", "stop_lon": "127.0", "location_type": "0"},
    ],
    [{"route_id": "R1", "service_id": "WK", "trip_id": "T1"}],
    [
        {"trip_id": "T1", "arrival_time": "09:00:00", "departure_time": "09:00:00", "stop_id": "A", "stop_sequence": "1"},
        {"trip_id": "T1", "arrival_time": "09:10:00", "departure_time": "09:10:00", "stop_id": "D", "stop_sequence": "2"},
    ],
    pathways=[{"pathway_id": "EXIT", "from_stop_id": "A", "to_stop_id": "D", "pathway_mode": "7", "is_bidirectional": "1", "traversal_time": "30"}],
)
bad_gate_validation = api_bad_gate.validate_gtfs_bytes(bad_gate_blob)
assert not bad_gate_validation["valid"]
assert any("pathways.txt" in error for error in bad_gate_validation["errors"])

# 6. A real multimodal graph can stitch a bus feed to a rail feed through a
# station entrance and explicit in-station GTFS pathway, without a false direct
# geometric walk between same-feed stops.
api6, _ = load_api("cross-feed-bus-rail")
bus_blob = make_gtfs_zip(
    [
        {"stop_id": "B_START", "stop_name": "버스 출발", "stop_lat": "37.0000", "stop_lon": "127.0000", "location_type": "0"},
        {"stop_id": "B_HUB", "stop_name": "버스 환승정류장", "stop_lat": "37.0040", "stop_lon": "127.0000", "location_type": "0"},
    ],
    [{"route_id": "R1", "service_id": "WK", "trip_id": "BUS1"}],
    [
        {"trip_id": "BUS1", "arrival_time": "09:00:00", "departure_time": "09:00:00", "stop_id": "B_START", "stop_sequence": "1"},
        {"trip_id": "BUS1", "arrival_time": "09:10:00", "departure_time": "09:10:00", "stop_id": "B_HUB", "stop_sequence": "2"},
    ],
)
# Make the first feed bus-only (helper's default route_type is rail).
with zipfile.ZipFile(io.BytesIO(bus_blob), "r") as zin:
    bus_files = {n: zin.read(n) for n in zin.namelist()}
    routes_text = bus_files["routes.txt"].decode("utf-8-sig").replace(",1\n", ",3\n")
    bus_files["routes.txt"] = routes_text.encode("utf-8")
bus_buf = io.BytesIO()
with zipfile.ZipFile(bus_buf, "w", zipfile.ZIP_DEFLATED) as zout:
    for name, content in bus_files.items(): zout.writestr(name, content)
api6.import_gtfs_bytes(bus_buf.getvalue(), "bus-feed.zip")

rail_stops = [
    {"stop_id": "STN", "stop_name": "철도역", "stop_lat": "37.0040", "stop_lon": "127.0000", "location_type": "1"},
    {"stop_id": "ENT", "stop_name": "역 출입구", "stop_lat": "37.0040", "stop_lon": "127.0000", "location_type": "2", "parent_station": "STN"},
    {"stop_id": "PLAT", "stop_name": "철도 승강장", "stop_lat": "37.0040", "stop_lon": "127.0000", "location_type": "0", "parent_station": "STN"},
    {"stop_id": "RAIL_DEST", "stop_name": "철도 도착역", "stop_lat": "37.0500", "stop_lon": "127.0000", "location_type": "0"},
]
rail_blob = make_gtfs_zip(
    rail_stops,
    [{"route_id": "R1", "service_id": "WK", "trip_id": "RAIL1"}],
    [
        {"trip_id": "RAIL1", "arrival_time": "09:16:00", "departure_time": "09:16:00", "stop_id": "PLAT", "stop_sequence": "1"},
        {"trip_id": "RAIL1", "arrival_time": "09:30:00", "departure_time": "09:30:00", "stop_id": "RAIL_DEST", "stop_sequence": "2"},
    ],
    pathways=[{"pathway_id": "ENT-PLAT", "from_stop_id": "ENT", "to_stop_id": "PLAT", "pathway_mode": "1", "is_bidirectional": "1", "traversal_time": "60"}],
)
api6.import_gtfs_bytes(rail_blob, "rail-feed.zip")
result6 = api6.transit_leg(
    api6.Waypoint(name="버스 출발지", lat=37.0000, lon=127.0000),
    api6.Waypoint(name="철도 도착지", lat=37.0500, lon=127.0000),
    datetime.fromisoformat("2026-11-24T08:50:00+09:00"), 80, "fast", None, mode="transit"
)
assert result6 is not None, "cross-feed bus-to-rail path should be found"
assert any(step.get("mode") == "bus" for step in result6["steps"])
assert any(step.get("mode") == "rail" for step in result6["steps"])
assert result6["transfers"] == 1
assert any(step.get("source") == "nearby stop walk" for step in result6["steps"] if step.get("mode") == "walk")
assert any(step.get("source") == "GTFS pathways" for step in result6["steps"] if step.get("mode") == "walk")
assert [step.get("mode") for step in result6["steps"] if step.get("mode") in ("bus", "rail")] == ["bus", "rail"]
assert api6.transit_leg(
    api6.Waypoint(name="버스 출발지", lat=37.0000, lon=127.0000),
    api6.Waypoint(name="철도 도착지", lat=37.0500, lon=127.0000),
    datetime.fromisoformat("2026-11-24T08:50:00+09:00"), 80, "fast", None, mode="bus"
) is None
assert api6.transit_leg(
    api6.Waypoint(name="버스 출발지", lat=37.0000, lon=127.0000),
    api6.Waypoint(name="철도 도착지", lat=37.0500, lon=127.0000),
    datetime.fromisoformat("2026-11-24T08:50:00+09:00"), 80, "fast", None, mode="rail"
) is None

print("PASS: GTFS rail transfers, transfer precedence, min/prohibited/in-seat (including distinct platform IDs)/reboard rules, trip-boundary enforcement, pathway routing, cross-feed bus-to-rail transfer, mode filters, and all-walk route rejection")
