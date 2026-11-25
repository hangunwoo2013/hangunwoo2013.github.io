"""B-ROUTE 1.92 provider adapter regression tests; fixtures only, no upstream/API calls."""
import importlib.util
import os
import sys
import tempfile
from pathlib import Path

TMP = Path(tempfile.mkdtemp(prefix="broute191-provider-test-"))
os.environ.update({
    "APP_ENV": "development",
    "DATA_DIR": str(TMP / "data"),
    "DATABASE_PATH": str(TMP / "data" / "test.sqlite3"),
    "APP_ORIGIN": "https://testserver",
    "GOOGLE_ADMIN_EMAIL": "owner@example.com",
    "GOOGLE_CLIENT_ID": "dummy-client",
    "SESSION_SECRET": "x" * 48,
    "DATA_GO_KR_SERVICE_KEY": "TEST-SECRET-DO-NOT-RETURN",
    "TAGO_TRAIN_SERVICE_NAME": "TrainInfo",
})
ROOT = Path(__file__).resolve().parents[2]
API_PATH = ROOT / "cloud-functions" / "api" / "index.py"
spec = importlib.util.spec_from_file_location("broute191_provider_test_api", API_PATH)
api = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = api
spec.loader.exec_module(api)
api.init_db()

from fastapi.testclient import TestClient
client = TestClient(api.app)
owner_claims = {"sub": "owner-sub", "email": "owner@example.com", "email_verified": True,
                "name": "Owner", "iat": 1, "exp": 9999999999}
owner = TestClient(api.app)
owner.cookies.set(api.SESSION_COOKIE, api._session_token(owner_claims))
headers = {"Origin": "https://testserver"}

calls = []
real_data_go_request = api.data_go_request

async def fake_data_go_request(service, operation, params, *, format_parameter="_type", format_value="json", include_paging=True):
    calls.append((service, operation, dict(params), format_parameter, format_value, include_paging))
    if (service, operation) == ("BusRoute", "getBusRoute"):
        return {"response": {"header": {"resultCode": "00", "resultMsg": "OK"},
            "body": {"totalCount": 2, "items": {"item": [
                {"rte_id": "R100", "rte_no": "100", "rte_nm": "시범 100번", "ctpv_cd": "26"},
                {"rte_id": "R200", "rte_no": "200", "rte_nm": "시범 200번", "ctpv_cd": "26"},
            ]}}}}
    if (service, operation) == ("BusRoutespecificStopInformation", "getBusRoutespecificStopInformation"):
        return {"response": {"header": {"resultCode": "00"}, "body": {"totalCount": 2, "items": {"item": [
            {"node_id": "B002", "node_nm": "두 번째 정류장", "node_ord": "2", "rte_id": "R100"},
            {"node_id": "B001", "node_nm": "첫 번째 정류장", "node_ord": "1", "rte_id": "R100"},
        ]}}}}
    if (service, operation) == ("TrainInfo", "GetCtyCodeList"):
        return {"response": {"header": {"resultCode": "00"}, "body": {"items": {"item": [
            {"citycode": "11", "cityname": "서울특별시"}, {"citycode": "21", "cityname": "부산광역시"}
        ]}}}}
    if (service, operation) == ("TrainInfo", "GetCtyAcctoTrainSttnList"):
        return {"response": {"header": {"resultCode": "00"}, "body": {"totalCount": 1, "items": {"item": {
            "nodeid": "NAT014445", "nodename": "부산", "citycode": "21", "gpslati": "35.1151", "gpslong": "129.0412"
        }}}}}
    if (service, operation) == ("TrainInfo", "GetStrtpntAlocFndTrainInfo"):
        return {"response": {"header": {"resultCode": "00"}, "body": {"totalCount": 1, "items": {"item": {
            "trainid": "T001", "trainno": "001", "traingradename": "KTX",
            "depplacename": "서울", "arrplacename": "부산",
            "depplandtime": "20261124090000", "arrplandtime": "20261124113000", "adultcharge": "59800"
        }}}}}
    if (service, operation) == ("BusSttnInfoInqireService", "getCtyCodeList"):
        return {"response": {"header": {"resultCode": "00"}, "body": {"items": {"item": {"citycode": "21", "cityname": "부산광역시"}}}}}
    if (service, operation) == ("BusSttnInfoInqireService", "getSttnThrghRouteList"):
        return {"response": {"header": {"resultCode": "00"}, "body": {"items": {"item": [
            {"routeid": "R100", "routeno": "100", "routetp": "일반버스", "startnodenm": "부산역", "endnodenm": "서면"},
            {"routeid": "R200", "routeno": "200", "routetp": "일반버스", "startnodenm": "부산역", "endnodenm": "해운대"}
        ]}}}}
    if (service, operation) == ("BusSttnInfoInqireService", "getCrdntPrxmtSttnList"):
        return {"response": {"header": {"resultCode": "00"}, "body": {"totalCount": 2, "items": {"item": [
            {"nodeid": "NEAR", "nodenm": "가까운 정류장", "gpslati": "35.0000", "gpslong": "129.0000", "citycode": "21"},
            {"nodeid": "FAR", "nodenm": "먼 정류장", "gpslati": "35.0060", "gpslong": "129.0000", "citycode": "21"}
        ]}}}}
    if (service, operation) == ("ArvlInfoInqireService", "getSttnAcctoArvlPrearngeInfoList"):
        return {"response": {"header": {"resultCode": "00"}, "body": {"items": {"item": {
            "routeno": "100", "arrtime": "420", "arrprevstationcnt": "3", "vehicletp": "저상버스", "nodenm": "시청앞"
        }}}}}
    raise AssertionError(f"Unexpected provider request: {service}/{operation}")

api.data_go_request = fake_data_go_request

# Public provider status never reveals any credential.
status = client.get("/transit/providers/status").json()
assert status["secrets_exposed"] is False
assert "TEST-SECRET-DO-NOT-RETURN" not in str(status)
assert {x["id"] for x in status["providers"]} == {"tago_bus", "tago_rail"}

# Bus route endpoint follows the documented TAGO BusRoute parameter names.
bus = client.get("/transit/bus/routes?province_code=26&operation_date=20261124&page=1&page_size=20")
assert bus.status_code == 200, bus.text
bus_data = bus.json()
assert bus_data["count"] == 2
assert bus_data["routes"][0]["route_number"] == "100"
assert calls[-1][0:2] == ("BusRoute", "getBusRoute")
assert calls[-1][2]["opr_ymd"] == "20261124" and calls[-1][2]["ctpv_cd"] == "26"
assert calls[-1][3:5] == ("dataType", "JSON")
# Cache should prevent a duplicate upstream call.
num_calls = len(calls)
bus_cached = client.get("/transit/bus/routes?province_code=26&operation_date=20261124&page=1&page_size=20")
assert bus_cached.status_code == 200 and bus_cached.json()["cache_hit"] is True
assert len(calls) == num_calls

# Bus route-specific stop API uses a path parameter and returns ordered stop sequence.
route_stops = client.get("/transit/bus/routes/R100/stops?province_code=26&district_code=26110&operation_date=20261124&page=1&page_size=20")
assert route_stops.status_code == 200, route_stops.text
assert [x["stop_id"] for x in route_stops.json()["stops"]] == ["B001", "B002"]
assert calls[-1][0:2] == ("BusRoutespecificStopInformation", "getBusRoutespecificStopInformation")
assert calls[-1][2]["sgg_cd"] == "26110" and calls[-1][2]["rte_id"] == "R100"

# Owner probe for the bus route-specific stop provider sends all documented filters.
probe_stops = owner.post("/admin/providers/probe", json={
    "provider": "tago_bus_stops", "province_code": "26", "district_code": "26110",
    "operation_date": "20261124", "route_id": "R100"
}, headers=headers)
assert probe_stops.status_code == 200, probe_stops.text
assert probe_stops.json()["result_count"] == 2
assert calls[-1][0:2] == ("BusRoutespecificStopInformation", "getBusRoutespecificStopInformation")
assert calls[-1][2] == {"opr_ymd": "20261124", "rte_id": "R100", "ctpv_cd": "26", "sgg_cd": "26110", "pageNo": 1, "numOfRows": 10}
assert "TEST-SECRET-DO-NOT-RETURN" not in probe_stops.text

# Rail city, station, and train schedule normalization.
cities = client.get("/transit/rail/cities")
assert cities.status_code == 200 and cities.json()["count"] == 2
assert calls[-1][5] is False
assert cities.json()["cities"][1] == {"id": "21", "name": "부산광역시", "mode": "rail"}
stations = client.get("/transit/rail/stations?city_code=21")
assert stations.status_code == 200 and stations.json()["stations"][0]["name"] == "부산"
trains = client.get("/transit/rail/trains?dep_station_id=NAT010000&arr_station_id=NAT014445&departure_date=20261124&train_grade_code=00")
assert trains.status_code == 200, trains.text
train = trains.json()["trains"][0]
assert train["train_type"] == "KTX" and train["duration_minutes"] == 150
assert train["adult_fare_krw"] == 59800
assert calls[-1][2]["depPlaceId"] == "NAT010000"
assert calls[-1][2]["arrPlaceId"] == "NAT014445"
assert calls[-1][2]["depPlandTime"] == "20261124"

# TAGO vicinity API has a fixed 500m upstream search and no radius query arg.
nearby = client.get("/transit/nearby?lat=35.0000&lon=129.0000&radius=300")
assert nearby.status_code == 200, nearby.text
nearby_data = nearby.json()
assert nearby_data["requested_radius_m"] == 300 and nearby_data["provider_max_radius_m"] == 500
assert [x["id"] for x in nearby_data["stops"]] == ["NEAR"]
assert "radius" not in calls[-1][2]
assert calls[-1][2]["gpsLati"] == 35.0 and calls[-1][2]["gpsLong"] == 129.0
assert client.get("/transit/nearby?lat=35&lon=129&radius=700").status_code == 422

# Official TAGO stop-through-route lookup, exact service + lowercase nodeid + pagination.
through_routes = client.get("/transit/stops/DJB8001/routes?city_code=21&page=2&page_size=7")
assert through_routes.status_code == 200, through_routes.text
assert len(through_routes.json()["routes"]) == 2
assert through_routes.json()["stop_id"] == "DJB8001"
assert through_routes.json()["routes"][0] == {
    "id": "R100", "route_number": "100", "route_type": "일반버스",
    "origin": "부산역", "destination": "서면", "mode": "bus",
    "source": "국토교통부 TAGO 정류소별 경유노선"
}
assert calls[-1][0:2] == ("BusSttnInfoInqireService", "getSttnThrghRouteList")
assert calls[-1][2] == {"cityCode": "21", "nodeid": "DJB8001", "pageNo": 2, "numOfRows": 7}
num_route_calls = len(calls)
through_cached = client.get("/transit/stops/DJB8001/routes?city_code=21&page=2&page_size=7")
assert through_cached.status_code == 200 and through_cached.json()["cache_hit"] is True
assert len(calls) == num_route_calls

# Existing TAGO bus arrival endpoint now includes a normalized contract.
arrivals = client.get("/transit/stops/DJB8001/arrivals?city_code=21")
assert arrivals.status_code == 200
normalized = arrivals.json()["normalized_arrivals"][0]
assert normalized["route"] == "100" and normalized["arrival_seconds"] == 420
assert normalized["remaining_stops"] == 3

# Owner-only probes verify each API operation separately, not just the shared API key.
bus_city_probe = owner.post("/admin/providers/probe", json={"provider": "tago_bus_city_codes"}, headers=headers)
assert bus_city_probe.status_code == 200, bus_city_probe.text
assert bus_city_probe.json()["operation"] == "getCtyCodeList"
assert bus_city_probe.json()["sample"][0]["id"] == "21"
assert calls[-1][0:2] == ("BusSttnInfoInqireService", "getCtyCodeList")

bus_route_probe = owner.post("/admin/providers/probe", json={
    "provider": "tago_bus", "province_code": "26", "operation_date": "20261124"
}, headers=headers)
assert bus_route_probe.status_code == 200, bus_route_probe.text
assert bus_route_probe.json()["operation"] == "getBusRoute"
assert bus_route_probe.json()["sample"][0]["route_number"] == "100"
assert calls[-1][0:2] == ("BusRoute", "getBusRoute")
assert calls[-1][2] == {"opr_ymd": "20261124", "ctpv_cd": "26", "pageNo": 1, "numOfRows": 10}

probe = owner.post("/admin/providers/probe", json={"provider": "tago_rail"}, headers=headers)
assert probe.status_code == 200, probe.text
assert probe.json()["ok"] is True and probe.json()["secret_values_returned"] is False
assert probe.json()["service"] == "TrainInfo" and probe.json()["operation"] == "GetCtyCodeList"
assert "TEST-SECRET-DO-NOT-RETURN" not in probe.text

rail_station_probe = owner.post("/admin/providers/probe", json={
    "provider": "tago_rail_stations", "city_code": "21"
}, headers=headers)
assert rail_station_probe.status_code == 200, rail_station_probe.text
assert rail_station_probe.json()["operation"] == "GetCtyAcctoTrainSttnList"
assert rail_station_probe.json()["sample"][0]["id"] == "NAT014445"
assert calls[-1][0:2] == ("TrainInfo", "GetCtyAcctoTrainSttnList")
assert calls[-1][2] == {"cityCode": "21"}

rail_timetable_probe = owner.post("/admin/providers/probe", json={
    "provider": "tago_rail_timetable", "dep_station_id": "NAT010000",
    "arr_station_id": "NAT014445", "operation_date": "20261124", "train_grade_code": "00"
}, headers=headers)
assert rail_timetable_probe.status_code == 200, rail_timetable_probe.text
assert rail_timetable_probe.json()["operation"] == "GetStrtpntAlocFndTrainInfo"
assert rail_timetable_probe.json()["sample"][0]["train_type"] == "KTX"
assert calls[-1][0:2] == ("TrainInfo", "GetStrtpntAlocFndTrainInfo")
assert calls[-1][2] == {"depPlaceId": "NAT010000", "arrPlaceId": "NAT014445",
                        "depPlandTime": "20261124", "trainGradeCode": "00"}

bus_stop_routes_probe = owner.post("/admin/providers/probe", json={
    "provider": "tago_bus_stop_routes", "city_code": "21", "node_id": "DJB8001"
}, headers=headers)
assert bus_stop_routes_probe.status_code == 200, bus_stop_routes_probe.text
assert bus_stop_routes_probe.json()["operation"] == "getSttnThrghRouteList"
assert bus_stop_routes_probe.json()["sample"][0]["route_number"] == "100"
assert calls[-1][0:2] == ("BusSttnInfoInqireService", "getSttnThrghRouteList")
assert calls[-1][2] == {"cityCode": "21", "nodeid": "DJB8001"}

bus_arrival_probe = owner.post("/admin/providers/probe", json={
    "provider": "tago_bus_arrivals", "city_code": "21", "node_id": "DJB8001"
}, headers=headers)
assert bus_arrival_probe.status_code == 200, bus_arrival_probe.text
assert bus_arrival_probe.json()["operation"] == "getSttnAcctoArvlPrearngeInfoList"
assert bus_arrival_probe.json()["sample"][0]["arrival_seconds"] == 420
assert calls[-1][0:2] == ("ArvlInfoInqireService", "getSttnAcctoArvlPrearngeInfoList")
assert calls[-1][2] == {"cityCode": "21", "nodeId": "DJB8001"}

# Required values are validated before an upstream request is attempted.
call_count_before_missing = len(calls)
assert owner.post("/admin/providers/probe", json={"provider": "tago_rail_timetable"}, headers=headers).status_code == 400
assert owner.post("/admin/providers/probe", json={"provider": "tago_bus_arrivals", "city_code": "21"}, headers=headers).status_code == 400
assert len(calls) == call_count_before_missing
friend = TestClient(api.app)
friend.cookies.set(api.SESSION_COOKIE, api._session_token({**owner_claims, "sub": "friend", "email": "friend@example.com"}))
assert friend.post("/admin/providers/probe", json={"provider": "tago_rail"}, headers=headers).status_code == 403
assert friend.post("/admin/providers/probe", json={"provider": "tago_bus_stops", "province_code":"26", "district_code":"26110", "route_id":"R100"}, headers=headers).status_code == 403
assert friend.post("/admin/providers/probe", json={"provider": "tago_rail_timetable", "dep_station_id":"NAT1", "arr_station_id":"NAT2", "operation_date":"20261124"}, headers=headers).status_code == 403

# Invalid date and same station are rejected before contacting provider.
before = len(calls)
assert client.get("/transit/rail/trains?dep_station_id=NAT1&arr_station_id=NAT1&departure_date=20261124").status_code == 400
assert client.get("/transit/bus/routes?province_code=26&operation_date=20261340").status_code == 400
assert len(calls) == before

# No key: provider status is still safe, but live requests fail closed.
old_key = api.DATA_GO_KEY
api.data_go_request = real_data_go_request
api.DATA_GO_KEY = ""
api.PROVIDER_CACHE.clear()
assert client.get("/transit/rail/cities").status_code == 503
api.DATA_GO_KEY = old_key

# Provider failure messages must not leak the service key even if the upstream echoes it.
import asyncio
class FakeResponse:
    status_code = 200
    def json(self):
        return {"response": {"header": {"resultCode": "99", "resultMsg": "invalid key TEST-SECRET-DO-NOT-RETURN"}, "body": {}}}
class FakeHttpClient:
    def __init__(self, *args, **kwargs): pass
    async def __aenter__(self): return self
    async def __aexit__(self, *args): return False
    async def get(self, url, params):
        assert params.get("serviceKey") == "TEST-SECRET-DO-NOT-RETURN"
        assert "TEST-SECRET-DO-NOT-RETURN" not in url
        return FakeResponse()
real_http_client = api.httpx.AsyncClient
api.httpx.AsyncClient = FakeHttpClient
try:
    asyncio.run(api.data_go_request("TrainInfo", "GetCtyCodeList", {}))
    raise AssertionError("Expected an upstream authorization error")
except api.HTTPException as exc:
    assert exc.status_code == 502
    assert "TEST-SECRET-DO-NOT-RETURN" not in str(exc.detail)
    assert "[REDACTED]" in str(exc.detail)
finally:
    api.httpx.AsyncClient = real_http_client

# Per-instance abuse guard returns 429 and Retry-After after the configured limit.
api.data_go_request = fake_data_go_request
api.PROVIDER_CACHE.clear()
api.PROVIDER_RATE_STATE.clear()
old_limit = api.PROVIDER_RATE_LIMIT_PER_MINUTE
api.PROVIDER_RATE_LIMIT_PER_MINUTE = 10
for _ in range(10):
    assert client.get("/transit/rail/cities").status_code == 200
limited = client.get("/transit/rail/cities")
assert limited.status_code == 429 and limited.headers.get("retry-after")
api.PROVIDER_RATE_LIMIT_PER_MINUTE = old_limit

print("PASS: official provider service/operation contracts, eight owner API probes, stop-route parameter casing, bus/rail normalization, cache, authorization, validation, secret redaction and rate limit")
