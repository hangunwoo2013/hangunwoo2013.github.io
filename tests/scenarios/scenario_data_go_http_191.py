"""B-ROUTE 1.92 TAGO HTTP contract tests. No live upstream/API credentials used."""
from __future__ import annotations

import asyncio
import importlib.util
import os
import sys
import tempfile
from pathlib import Path

TMP = Path(tempfile.mkdtemp(prefix="broute191-http-"))
os.environ.update({
    "APP_ENV": "development",
    "DATA_DIR": str(TMP / "data"),
    "DATABASE_PATH": str(TMP / "data" / "test.sqlite3"),
    "APP_ORIGIN": "https://testserver",
    "GOOGLE_ADMIN_EMAIL": "owner@example.com",
    "GOOGLE_CLIENT_ID": "test-client",
    "SESSION_SECRET": "s" * 48,
    "DATA_GO_KR_SERVICE_KEY": "SERVER-ONLY-TEST-KEY",
})

ROOT = Path(__file__).resolve().parents[2]
API_PATH = ROOT / "cloud-functions" / "api" / "index.py"
spec = importlib.util.spec_from_file_location("broute191_http_api", API_PATH)
api = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = api
spec.loader.exec_module(api)

calls = []
next_response = {"response": {"header": {"resultCode": "00", "resultMsg": "NORMAL SERVICE."}, "body": {"items": {"item": []}}}}
next_status = 200
next_exception = None


class FakeResponse:
    def __init__(self, status_code, payload):
        self.status_code = status_code
        self.payload = payload

    def json(self):
        if isinstance(self.payload, Exception):
            raise self.payload
        return self.payload


class FakeAsyncClient:
    def __init__(self, *args, **kwargs):
        self.kwargs = kwargs

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return False

    async def get(self, url, params):
        global next_status, next_response, next_exception
        calls.append({"url": url, "params": dict(params), "headers": self.kwargs.get("headers", {})})
        if next_exception is not None:
            raise next_exception
        return FakeResponse(next_status, next_response)


original_client = api.httpx.AsyncClient
api.httpx.AsyncClient = FakeAsyncClient

# Exact service root, operation, encoding parameter and required bus stop fields.
params = {
    "opr_ymd": "20261124", "rte_id": "BUS100", "ctpv_cd": "26", "sgg_cd": "26110",
    "pageNo": 1, "numOfRows": 100,
}
payload = asyncio.run(api.data_go_request(
    "BusRoutespecificStopInformation", "getBusRoutespecificStopInformation", params,
    format_parameter="dataType", format_value="JSON"
))
assert payload["response"]["header"]["resultCode"] == "00"
assert calls[-1]["url"] == "https://apis.data.go.kr/1613000/BusRoutespecificStopInformation/getBusRoutespecificStopInformation"
assert calls[-1]["params"]["serviceKey"] == "SERVER-ONLY-TEST-KEY"
assert calls[-1]["params"]["dataType"] == "JSON"
assert {k: calls[-1]["params"][k] for k in params} == params
assert "SERVER-ONLY-TEST-KEY" not in str(payload)
assert calls[-1]["headers"]["User-Agent"].startswith("B-ROUTE/1.94")

# TAGO TrainInfo request uses documented station IDs and date query names.
train_params = {"depPlaceId": "NAT010000", "arrPlaceId": "NAT014445", "depPlandTime": "20261124", "pageNo": 1, "numOfRows": 100}
asyncio.run(api.data_go_request("TrainInfo", "GetStrtpntAlocFndTrainInfo", train_params))
assert calls[-1]["url"] == "https://apis.data.go.kr/1613000/TrainInfo/GetStrtpntAlocFndTrainInfo"
assert calls[-1]["params"]["_type"] == "json"
assert calls[-1]["params"]["depPlaceId"] == "NAT010000"
assert calls[-1]["params"]["arrPlaceId"] == "NAT014445"

# Official TAGO stop-through-route operation: service root and `nodeid` spelling.
asyncio.run(api.data_go_request("BusSttnInfoInqireService", "getSttnThrghRouteList",
                                {"cityCode": "21", "nodeid": "DJB8001"}))
assert calls[-1]["url"] == "https://apis.data.go.kr/1613000/BusSttnInfoInqireService/getSttnThrghRouteList"
assert calls[-1]["params"]["cityCode"] == "21"
assert calls[-1]["params"]["nodeid"] == "DJB8001"
assert "nodeId" not in calls[-1]["params"]

# City-code endpoint documents only serviceKey and _type (no paging params).
asyncio.run(api.data_go_request("TrainInfo", "GetCtyCodeList", {}, include_paging=False))
assert calls[-1]["url"].endswith("/TrainInfo/GetCtyCodeList")
assert calls[-1]["params"] == {"serviceKey": "SERVER-ONLY-TEST-KEY", "_type": "json"}

# data.go.kr resultCode=03 is a successful no-data response, not a gateway error.
next_response = {"response": {"header": {"resultCode": "03", "resultMsg": "NODATA_ERROR"}, "body": {"totalCount": 0, "items": {}}}}
empty_payload = asyncio.run(api.data_go_request("TrainInfo", "GetCtyCodeList", {}, include_paging=False))
assert api.parse_data_go_items(empty_payload) == []

# Provider-level authentication failure is translated and the secret is redacted.
next_response = {"response": {"header": {"resultCode": "30", "resultMsg": "Invalid key SERVER-ONLY-TEST-KEY"}, "body": {}}}
try:
    asyncio.run(api.data_go_request("TrainInfo", "GetCtyCodeList", {}))
    raise AssertionError("API auth error should fail closed")
except api.HTTPException as exc:
    assert exc.status_code == 503
    assert "SERVER-ONLY-TEST-KEY" not in str(exc.detail)

# Provider quota and upstream HTTP errors map to clear gateway errors.
next_status = 429
next_response = {}
try:
    asyncio.run(api.data_go_request("TrainInfo", "GetCtyCodeList", {}))
    raise AssertionError("429 should be surfaced")
except api.HTTPException as exc:
    assert exc.status_code == 429

next_status = 502
try:
    asyncio.run(api.data_go_request("TrainInfo", "GetCtyCodeList", {}))
    raise AssertionError("upstream 5xx should map to 502")
except api.HTTPException as exc:
    assert exc.status_code == 502

next_status = 200
next_response = {"response": {"header": {"resultCode": "23", "resultMsg": "per-second quota"}, "body": {}}}
try:
    asyncio.run(api.data_go_request("TrainInfo", "GetCtyCodeList", {}))
    raise AssertionError("per-second quota should map to 429")
except api.HTTPException as exc:
    assert exc.status_code == 429

# Timeout and non-JSON upstream body are handled without leaking URL/key.
next_status = 200
next_exception = api.httpx.TimeoutException("secret url should not be shown")
try:
    asyncio.run(api.data_go_request("TrainInfo", "GetCtyCodeList", {}))
    raise AssertionError("timeout should fail")
except api.HTTPException as exc:
    assert exc.status_code == 504
    assert "SERVER-ONLY-TEST-KEY" not in str(exc.detail)
next_exception = None
next_response = ValueError("bad JSON")
try:
    asyncio.run(api.data_go_request("TrainInfo", "GetCtyCodeList", {}))
    raise AssertionError("invalid JSON should fail")
except api.HTTPException as exc:
    assert exc.status_code == 502

api.httpx.AsyncClient = original_client
print("PASS: TAGO HTTP URL/parameter contracts (including stop-through-route casing), server-only key handling, resultCode mapping, quota/HTTP errors, timeout and JSON handling")
