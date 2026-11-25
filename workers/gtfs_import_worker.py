#!/usr/bin/env python3
"""Long-running GTFS staging worker for B-ROUTE 2.0 Beta Test.

This process is intentionally separate from the web API: it streams
large ZIP members from disk and commits bounded DB batches. It must run in a
trusted server/container with the same PostgreSQL and COS server-side secrets.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import importlib.util
import io
import json
import math
import os
import re
import sqlite3
import sys
import tempfile
import socket
import time
import threading
import uuid
import zipfile
from contextlib import closing
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Iterable

ROOT = Path(__file__).resolve().parents[1]
API_PATH = ROOT / "cloud-functions" / "api" / "index.py"
spec = importlib.util.spec_from_file_location("broute_api", API_PATH)
if spec is None or spec.loader is None:
    raise RuntimeError("B-ROUTE API module을 불러오지 못했습니다.")
api = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = api
spec.loader.exec_module(api)

MAX_COMPRESSED_BYTES = int(os.getenv("GTFS_STAGING_MAX_BYTES", str(2 * 1024 * 1024 * 1024)))
MAX_UNCOMPRESSED_BYTES = int(os.getenv("GTFS_WORKER_MAX_UNCOMPRESSED_BYTES", str(4 * 1024 * 1024 * 1024)))
MAX_MEMBER_BYTES = int(os.getenv("GTFS_WORKER_MAX_MEMBER_BYTES", str(3 * 1024 * 1024 * 1024)))
BATCH_ROWS = max(500, min(20000, int(os.getenv("GTFS_WORKER_BATCH_ROWS", "5000"))))
POLL_SECONDS = max(3, int(os.getenv("GTFS_WORKER_POLL_SECONDS", "15")))

REQUIRED_FILES = {"agency.txt", "stops.txt", "routes.txt", "trips.txt", "stop_times.txt"}
REQUIRED_COLUMNS = {
    "agency.txt": {"agency_name", "agency_url", "agency_timezone"},
    "stops.txt": {"stop_id", "stop_name", "stop_lat", "stop_lon"},
    "routes.txt": {"route_id", "route_type"},
    "trips.txt": {"route_id", "service_id", "trip_id"},
    "stop_times.txt": {"trip_id", "arrival_time", "departure_time", "stop_id", "stop_sequence"},
    "calendar.txt": {"service_id", "monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday", "start_date", "end_date"},
    "calendar_dates.txt": {"service_id", "date", "exception_type"},
}
OPTIONAL_COLUMNS = {
    "transfers.txt": {"from_stop_id", "to_stop_id", "transfer_type"},
    "pathways.txt": {"pathway_id", "from_stop_id", "to_stop_id", "pathway_mode", "is_bidirectional"},
}
TIME_RE = re.compile(r"^(\d{1,2}):([0-5]\d):([0-5]\d)$")


def now_iso() -> str:
    return datetime.now(api.TZ).isoformat()


WORKER_ID = os.getenv("GTFS_WORKER_ID", socket.gethostname() + "-" + uuid.uuid4().hex[:8])
WORKER_STATUS = "starting"
WORKER_LAST_ERROR = ""
CURRENT_JOB_ID = ""


def update_worker_heartbeat(status: str, last_error: str = "") -> None:
    global WORKER_STATUS, WORKER_LAST_ERROR
    WORKER_STATUS = status
    WORKER_LAST_ERROR = last_error[:1000]
    with closing(api.db()) as con:
        con.execute("INSERT INTO gtfs_worker_heartbeats(worker_id,status,last_seen,version,last_error) VALUES(?,?,?,?,?) "
                    "ON CONFLICT(worker_id) DO UPDATE SET status=excluded.status,last_seen=excluded.last_seen,version=excluded.version,last_error=excluded.last_error",
                    (WORKER_ID,status,now_iso(),api.APP_VERSION,WORKER_LAST_ERROR))
        con.commit()


def update_job(job_id: str, **values: Any) -> None:
    allowed = {"status", "progress_percent", "progress_phase", "processed_rows", "updated_at",
               "actual_sha256", "feed_id", "release_id", "completed_at", "error_message"}
    if not values or any(k not in allowed for k in values):
        raise ValueError("허용되지 않은 작업 상태 필드입니다.")
    values.setdefault("updated_at", now_iso())
    sql = "UPDATE gtfs_staging_uploads SET " + ",".join(f"{k}=?" for k in values) + " WHERE job_id=?"
    # Progress updates also refresh the heartbeat, so long imports stay visible
    # even when the worker is busy for longer than the admin dashboard TTL.
    status = values.get("status")
    heartbeat_status = "error" if status == "failed" else ("idle" if status == "completed" else "processing")
    with closing(api.db()) as con:
        con.execute(sql, (*values.values(), job_id))
        con.execute("INSERT INTO gtfs_worker_heartbeats(worker_id,status,last_seen,version,last_error) VALUES(?,?,?,?,?) "
                    "ON CONFLICT(worker_id) DO UPDATE SET status=excluded.status,last_seen=excluded.last_seen,version=excluded.version,last_error=excluded.last_error",
                    (WORKER_ID,heartbeat_status,now_iso(),api.APP_VERSION,str(values.get("error_message", ""))[:1000]))
        con.commit()


def claim_job() -> dict[str, Any] | None:
    with closing(api.db()) as con:
        stale_before = (datetime.now(api.TZ) - timedelta(minutes=15)).isoformat()
        query = "SELECT job_id,source_id,file_name,expected_size,object_key,source_version,effective_date,expected_sha256,feed_id,created_by FROM gtfs_staging_uploads WHERE status='queued' OR (status='processing' AND updated_at<?) ORDER BY created_at LIMIT 1"
        if api.DB_IS_POSTGRES:
            row = con.execute(query + " FOR UPDATE SKIP LOCKED", (stale_before,)).fetchone()
        else:
            row = con.execute(query, (stale_before,)).fetchone()
        if not row:
            return None
        job = {"job_id": row[0], "source_id": row[1], "file_name": row[2], "expected_size": int(row[3]),
               "object_key": row[4], "source_version": row[5], "effective_date": row[6],
               "expected_sha256": row[7], "feed_id": row[8] or uuid.uuid4().hex[:12], "created_by": row[9]}
        con.execute("UPDATE gtfs_staging_uploads SET status='processing',progress_percent=1,progress_phase='download',processed_rows=0,feed_id=?,error_message='',updated_at=? WHERE job_id=?",
                    (job["feed_id"], now_iso(), job["job_id"]))
        con.commit()
        return job


def download_object_to_file(object_key: str, output_path: Path) -> None:
    client = api.cos_client()
    response = client.get_object(Bucket=os.environ["COS_BUCKET"].strip(), Key=object_key)
    body = response.get("Body") if isinstance(response, dict) else None
    if body is None:
        raise RuntimeError("COS 다운로드 응답에 객체 본문이 없습니다.")
    if hasattr(body, "get_stream_to_file"):
        body.get_stream_to_file(str(output_path))
    else:
        stream = body.get_raw_stream() if hasattr(body, "get_raw_stream") else body
        with output_path.open("wb") as target:
            while True:
                chunk = stream.read(1024 * 1024)
                if not chunk:
                    break
                target.write(chunk)


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while True:
            chunk = handle.read(4 * 1024 * 1024)
            if not chunk:
                break
            digest.update(chunk)
    return digest.hexdigest()


def safe_members(zf: zipfile.ZipFile) -> tuple[dict[str, str], int]:
    members: dict[str, str] = {}
    total = 0
    infos = zf.infolist()
    if len(infos) > 300:
        raise ValueError("GTFS ZIP 내부 파일이 너무 많습니다(300개 초과).")
    for info in infos:
        if info.is_dir():
            continue
        name = info.filename.replace("\\", "/")
        parts = name.split("/")
        if name.startswith("/") or any(p in ("", ".", "..") for p in parts):
            raise ValueError("GTFS ZIP에 안전하지 않은 파일 경로가 있습니다.")
        if info.flag_bits & 0x1:
            raise ValueError("암호화된 ZIP은 지원하지 않습니다.")
        if info.compress_type not in (zipfile.ZIP_STORED, zipfile.ZIP_DEFLATED):
            raise ValueError("지원하지 않는 ZIP 압축 방식입니다.")
        mode = (info.external_attr >> 16) & 0o170000
        if mode == 0o120000:
            raise ValueError("ZIP 심볼릭 링크는 허용하지 않습니다.")
        total += info.file_size
        if info.file_size > MAX_MEMBER_BYTES or total > MAX_UNCOMPRESSED_BYTES:
            raise ValueError("GTFS 압축 해제 용량이 Worker 한도를 초과했습니다.")
        if info.compress_size == 0 and info.file_size > 0:
            raise ValueError("비정상 압축 파일이 있습니다.")
        if info.compress_size and info.file_size / info.compress_size > 1000:
            raise ValueError("압축률이 비정상적으로 높습니다.")
        base = parts[-1].lower()
        if base.endswith(".txt"):
            if base in members:
                raise ValueError(f"GTFS 파일명이 중복됩니다: {base}")
            members[base] = info.filename
    return members, total


def iter_csv(zf: zipfile.ZipFile, member: str) -> Iterable[dict[str, str]]:
    with zf.open(member, "r") as raw:
        with io.TextIOWrapper(raw, encoding="utf-8-sig", newline="") as text:
            reader = csv.DictReader(text)
            if not reader.fieldnames:
                raise ValueError(f"{Path(member).name}: CSV 헤더가 없습니다.")
            yield from reader


def get_headers(zf: zipfile.ZipFile, member: str) -> set[str]:
    with zf.open(member, "r") as raw:
        with io.TextIOWrapper(raw, encoding="utf-8-sig", newline="") as text:
            return set(next(csv.reader(text), []))


def validate_archive_streaming(path: Path) -> dict[str, Any]:
    counts: dict[str, int] = {}
    warnings: list[str] = []
    with zipfile.ZipFile(path, "r") as zf, tempfile.TemporaryDirectory(prefix="broute-gtfs-check-") as td:
        members, uncompressed = safe_members(zf)
        missing = sorted(REQUIRED_FILES - set(members))
        if missing:
            raise ValueError("필수 GTFS 파일 누락: " + ", ".join(missing))
        if not ({"calendar.txt", "calendar_dates.txt"} & set(members)):
            raise ValueError("calendar.txt 또는 calendar_dates.txt가 필요합니다.")
        for filename, needed in {**REQUIRED_COLUMNS, **OPTIONAL_COLUMNS}.items():
            if filename in members:
                absent = sorted(needed - get_headers(zf, members[filename]))
                if absent:
                    raise ValueError(f"{filename}: 필수 열 누락 {', '.join(absent)}")
        if "frequencies.txt" in members:
            raise ValueError("frequencies.txt는 현재 B-ROUTE 경로 엔진이 지원하지 않아 대용량 가져오기를 중단했습니다.")
        if any(n in members for n in ("locations.geojson", "booking_rules.txt", "stop_areas.txt", "location_groups.txt")):
            raise ValueError("GTFS Flex 파일은 현재 B-ROUTE 경로 엔진이 지원하지 않습니다.")

        scratch_path = Path(td) / "check.sqlite3"
        check = sqlite3.connect(scratch_path)
        check.execute("PRAGMA journal_mode=OFF")
        check.execute("PRAGMA synchronous=OFF")
        check.execute("PRAGMA temp_store=FILE")
        check.executescript("""
            CREATE TABLE stop_ids(id TEXT PRIMARY KEY, parent_station TEXT DEFAULT '', location_type INTEGER DEFAULT 0, stop_access TEXT DEFAULT '');
            CREATE TABLE route_ids(id TEXT PRIMARY KEY);
            CREATE TABLE service_ids(id TEXT PRIMARY KEY);
            CREATE TABLE trip_refs(id TEXT PRIMARY KEY, route_id TEXT, service_id TEXT);
            CREATE TABLE stop_time_refs(trip_id TEXT, stop_id TEXT, seq INTEGER, PRIMARY KEY(trip_id,seq));
            CREATE TABLE transfer_keys(
                from_stop_id TEXT NOT NULL, to_stop_id TEXT NOT NULL,
                from_trip_id TEXT NOT NULL, to_trip_id TEXT NOT NULL,
                from_route_id TEXT NOT NULL, to_route_id TEXT NOT NULL,
                PRIMARY KEY(from_stop_id,to_stop_id,from_trip_id,to_trip_id,from_route_id,to_route_id)
            );
        """)
        try:
            agency_rows = 0
            zones: set[str] = set()
            for row in iter_csv(zf, members["agency.txt"]):
                agency_rows += 1
                if row.get("agency_timezone"):
                    zones.add(row["agency_timezone"])
            if not agency_rows:
                raise ValueError("agency.txt에 데이터 행이 없습니다.")
            if zones and zones != {"Asia/Seoul"}:
                warnings.append("Asia/Seoul 이외의 시간대가 포함되어 있습니다. 한국 시간대 경로 계산과 별도 검증이 필요합니다.")
            counts["agency.txt"] = agency_rows

            stop_batch = []
            bad_coords = 0
            for row in iter_csv(zf, members["stops.txt"]):
                sid = (row.get("stop_id") or "").strip()
                if not sid:
                    raise ValueError("stops.txt에 빈 stop_id가 있습니다.")
                try:
                    lat = float(row.get("stop_lat", "")); lon = float(row.get("stop_lon", ""))
                    if not (-90 <= lat <= 90 and -180 <= lon <= 180): bad_coords += 1
                except Exception:
                    bad_coords += 1
                try:
                    location_type = int(row.get("location_type") or 0)
                except ValueError as exc:
                    raise ValueError("stops.txt location_type은 정수여야 합니다.") from exc
                if location_type not in range(0, 5):
                    raise ValueError("stops.txt location_type은 0~4만 허용됩니다.")
                stop_batch.append((sid, (row.get("parent_station") or "").strip(), location_type, (row.get("stop_access") or "").strip()))
                if len(stop_batch) >= BATCH_ROWS:
                    try: check.executemany("INSERT INTO stop_ids VALUES(?,?,?,?)", stop_batch)
                    except sqlite3.IntegrityError as exc: raise ValueError("stops.txt에 중복 stop_id가 있습니다.") from exc
                    stop_batch.clear()
            if stop_batch:
                try: check.executemany("INSERT INTO stop_ids VALUES(?,?,?,?)", stop_batch)
                except sqlite3.IntegrityError as exc: raise ValueError("stops.txt에 중복 stop_id가 있습니다.") from exc
            if bad_coords:
                raise ValueError(f"stops.txt 좌표 오류 {bad_coords}개")
            counts["stops.txt"] = check.execute("SELECT COUNT(*) FROM stop_ids").fetchone()[0]
            if not counts["stops.txt"]: raise ValueError("stops.txt에 데이터 행이 없습니다.")
            orphan_parents = check.execute("SELECT COUNT(*) FROM stop_ids s LEFT JOIN stop_ids p ON p.id=s.parent_station WHERE s.parent_station<>'' AND p.id IS NULL").fetchone()[0]
            if orphan_parents:
                raise ValueError(f"stops.txt parent_station 참조 누락 {orphan_parents}개")
            bad_parent_types = check.execute("""
                SELECT COUNT(*) FROM stop_ids s JOIN stop_ids p ON p.id=s.parent_station
                WHERE s.parent_station<>'' AND (
                    s.location_type=1 OR
                    (s.location_type=4 AND p.location_type<>0) OR
                    (s.location_type IN (0,2,3) AND p.location_type<>1)
                )
            """).fetchone()[0]
            if bad_parent_types:
                raise ValueError(f"stops.txt parent_station 유형 관계 오류 {bad_parent_types}개")

            route_batch = []
            route_types: set[int] = set()
            for row in iter_csv(zf, members["routes.txt"]):
                rid = (row.get("route_id") or "").strip()
                if not rid: raise ValueError("routes.txt에 빈 route_id가 있습니다.")
                raw_type = (row.get("route_type") or "").strip()
                if not raw_type.isdigit(): raise ValueError("routes.txt에 숫자가 아닌 route_type이 있습니다.")
                route_types.add(int(raw_type)); route_batch.append((rid,))
                if len(route_batch) >= BATCH_ROWS:
                    try: check.executemany("INSERT INTO route_ids VALUES(?)", route_batch)
                    except sqlite3.IntegrityError as exc: raise ValueError("routes.txt에 중복 route_id가 있습니다.") from exc
                    route_batch.clear()
            if route_batch:
                try: check.executemany("INSERT INTO route_ids VALUES(?)", route_batch)
                except sqlite3.IntegrityError as exc: raise ValueError("routes.txt에 중복 route_id가 있습니다.") from exc
            counts["routes.txt"] = check.execute("SELECT COUNT(*) FROM route_ids").fetchone()[0]
            if not counts["routes.txt"]: raise ValueError("routes.txt에 데이터 행이 없습니다.")
            if route_types - {0,1,2,3,4,5,6,7}:
                warnings.append("기본 route_type 외 확장 교통수단 유형이 포함되어 있습니다.")

            for calendar_file in ("calendar.txt", "calendar_dates.txt"):
                if calendar_file not in members: continue
                batch = []
                for row in iter_csv(zf, members[calendar_file]):
                    service = (row.get("service_id") or "").strip()
                    if not service: raise ValueError(f"{calendar_file}에 빈 service_id가 있습니다.")
                    batch.append((service,))
                    if len(batch) >= BATCH_ROWS:
                        check.executemany("INSERT OR IGNORE INTO service_ids VALUES(?)", batch); batch.clear()
                if batch: check.executemany("INSERT OR IGNORE INTO service_ids VALUES(?)", batch)
            service_count = check.execute("SELECT COUNT(*) FROM service_ids").fetchone()[0]
            if not service_count: raise ValueError("운행 서비스(service_id)가 없습니다.")
            counts["calendar.txt"] = sum(1 for _ in iter_csv(zf, members["calendar.txt"])) if "calendar.txt" in members else 0
            counts["calendar_dates.txt"] = sum(1 for _ in iter_csv(zf, members["calendar_dates.txt"])) if "calendar_dates.txt" in members else 0

            batch = []
            for row in iter_csv(zf, members["trips.txt"]):
                trip = (row.get("trip_id") or "").strip(); route = (row.get("route_id") or "").strip(); service = (row.get("service_id") or "").strip()
                if not trip or not route or not service: raise ValueError("trips.txt에 필수 ID가 비어 있습니다.")
                batch.append((trip, route, service))
                if len(batch) >= BATCH_ROWS:
                    try: check.executemany("INSERT INTO trip_refs VALUES(?,?,?)", batch)
                    except sqlite3.IntegrityError as exc: raise ValueError("trips.txt에 중복 trip_id가 있습니다.") from exc
                    batch.clear()
            if batch:
                try: check.executemany("INSERT INTO trip_refs VALUES(?,?,?)", batch)
                except sqlite3.IntegrityError as exc: raise ValueError("trips.txt에 중복 trip_id가 있습니다.") from exc
            counts["trips.txt"] = check.execute("SELECT COUNT(*) FROM trip_refs").fetchone()[0]
            if not counts["trips.txt"]: raise ValueError("trips.txt에 데이터 행이 없습니다.")
            missing_routes = check.execute("SELECT COUNT(*) FROM trip_refs t LEFT JOIN route_ids r ON r.id=t.route_id WHERE r.id IS NULL").fetchone()[0]
            missing_services = check.execute("SELECT COUNT(*) FROM trip_refs t LEFT JOIN service_ids s ON s.id=t.service_id WHERE s.id IS NULL").fetchone()[0]
            if missing_routes: raise ValueError(f"trips.txt의 route_id 참조 누락 {missing_routes}개")
            if missing_services: raise ValueError(f"trips.txt의 service_id 참조 누락 {missing_services}개")

            batch = []
            bad_times = 0
            for row in iter_csv(zf, members["stop_times.txt"]):
                trip = (row.get("trip_id") or "").strip(); stop = (row.get("stop_id") or "").strip()
                arr = (row.get("arrival_time") or "").strip(); dep = (row.get("departure_time") or "").strip()
                seq_text = (row.get("stop_sequence") or "").strip()
                if not TIME_RE.fullmatch(arr) or not TIME_RE.fullmatch(dep): bad_times += 1
                try:
                    seq = int(seq_text)
                    if seq < 0: raise ValueError()
                except Exception as exc:
                    raise ValueError("stop_times.txt에 잘못된 stop_sequence가 있습니다.") from exc
                batch.append((trip, stop, seq))
                if len(batch) >= BATCH_ROWS:
                    try: check.executemany("INSERT INTO stop_time_refs VALUES(?,?,?)", batch)
                    except sqlite3.IntegrityError as exc: raise ValueError("stop_times.txt에 중복 trip_id + stop_sequence가 있습니다.") from exc
                    batch.clear()
            if batch:
                try: check.executemany("INSERT INTO stop_time_refs VALUES(?,?,?)", batch)
                except sqlite3.IntegrityError as exc: raise ValueError("stop_times.txt에 중복 trip_id + stop_sequence가 있습니다.") from exc
            if bad_times: raise ValueError(f"stop_times.txt에 잘못된 도착/출발 시간 {bad_times}개")
            counts["stop_times.txt"] = check.execute("SELECT COUNT(*) FROM stop_time_refs").fetchone()[0]
            if not counts["stop_times.txt"]: raise ValueError("stop_times.txt에 데이터 행이 없습니다.")
            missing_trip = check.execute("SELECT COUNT(*) FROM stop_time_refs s LEFT JOIN trip_refs t ON t.id=s.trip_id WHERE t.id IS NULL").fetchone()[0]
            missing_stop = check.execute("SELECT COUNT(*) FROM stop_time_refs s LEFT JOIN stop_ids p ON p.id=s.stop_id WHERE p.id IS NULL").fetchone()[0]
            if missing_trip: raise ValueError(f"stop_times.txt의 trip_id 참조 누락 {missing_trip}개")
            if missing_stop: raise ValueError(f"stop_times.txt의 stop_id 참조 누락 {missing_stop}개")
            if "transfers.txt" in members:
                transfer_count = 0
                for row in iter_csv(zf, members["transfers.txt"]):
                    transfer_count += 1
                    transfer_type = int(row.get("transfer_type") or 0)
                    if transfer_type not in range(0, 6):
                        raise ValueError("transfers.txt transfer_type은 0~5만 허용됩니다.")
                    from_stop = (row.get("from_stop_id") or "").strip()
                    to_stop = (row.get("to_stop_id") or "").strip()
                    from_trip = (row.get("from_trip_id") or "").strip()
                    to_trip = (row.get("to_trip_id") or "").strip()
                    if transfer_type in (0,1,2,3) and (not from_stop or not to_stop):
                        raise ValueError("transfers.txt transfer_type 0~3에는 from_stop_id와 to_stop_id가 필요합니다.")
                    if transfer_type in (4,5) and (not from_trip or not to_trip):
                        raise ValueError("transfers.txt transfer_type 4/5에는 from_trip_id와 to_trip_id가 필요합니다.")
                    if from_stop:
                        from_row = check.execute("SELECT location_type,stop_access FROM stop_ids WHERE id=?", (from_stop,)).fetchone()
                        if not from_row:
                            raise ValueError("transfers.txt from_stop_id가 stops.txt에 없습니다.")
                        from_type = int(from_row[0] or 0)
                        if transfer_type in (4,5) and from_type != 0:
                            raise ValueError("transfer_type 4/5의 from_stop_id는 location_type=0이어야 합니다.")
                        if transfer_type in (0,1,2,3) and from_type not in (0,1):
                            raise ValueError("transfer_type 0~3의 from_stop_id는 정류장(0) 또는 역(1)이어야 합니다.")
                    if to_stop:
                        to_row = check.execute("SELECT location_type,stop_access FROM stop_ids WHERE id=?", (to_stop,)).fetchone()
                        if not to_row:
                            raise ValueError("transfers.txt to_stop_id가 stops.txt에 없습니다.")
                        to_type = int(to_row[0] or 0)
                        if transfer_type in (4,5) and to_type != 0:
                            raise ValueError("transfer_type 4/5의 to_stop_id는 location_type=0이어야 합니다.")
                        if transfer_type in (0,1,2,3) and to_type not in (0,1):
                            raise ValueError("transfer_type 0~3의 to_stop_id는 정류장(0) 또는 역(1)이어야 합니다.")
                    if from_trip and not check.execute("SELECT 1 FROM trip_refs WHERE id=?", (from_trip,)).fetchone():
                        raise ValueError("transfers.txt from_trip_id가 trips.txt에 없습니다.")
                    if to_trip and not check.execute("SELECT 1 FROM trip_refs WHERE id=?", (to_trip,)).fetchone():
                        raise ValueError("transfers.txt to_trip_id가 trips.txt에 없습니다.")
                    from_route = (row.get("from_route_id") or "").strip()
                    to_route = (row.get("to_route_id") or "").strip()
                    try:
                        check.execute("INSERT INTO transfer_keys VALUES(?,?,?,?,?,?)",
                                      (from_stop, to_stop, from_trip, to_trip, from_route, to_route))
                    except sqlite3.IntegrityError as exc:
                        raise ValueError("transfers.txt에 중복 환승 규칙 키가 있습니다.") from exc
                    if from_route and not check.execute("SELECT 1 FROM route_ids WHERE id=?", (from_route,)).fetchone():
                        raise ValueError("transfers.txt from_route_id가 routes.txt에 없습니다.")
                    if to_route and not check.execute("SELECT 1 FROM route_ids WHERE id=?", (to_route,)).fetchone():
                        raise ValueError("transfers.txt to_route_id가 routes.txt에 없습니다.")
                    if from_trip and from_route:
                        trip_route = check.execute("SELECT route_id FROM trip_refs WHERE id=?", (from_trip,)).fetchone()
                        if trip_route and trip_route[0] != from_route:
                            raise ValueError("transfers.txt from_trip_id와 from_route_id가 일치하지 않습니다.")
                    if to_trip and to_route:
                        trip_route = check.execute("SELECT route_id FROM trip_refs WHERE id=?", (to_trip,)).fetchone()
                        if trip_route and trip_route[0] != to_route:
                            raise ValueError("transfers.txt to_trip_id와 to_route_id가 일치하지 않습니다.")
                    if transfer_type == 2:
                        value = (row.get("min_transfer_time") or "").strip()
                        if not value.isdigit():
                            raise ValueError("transfer_type=2에는 유효한 min_transfer_time이 필요합니다.")
                counts["transfers.txt"] = transfer_count
            if "pathways.txt" in members:
                pathway_count = 0
                seen_pathway_ids = set()
                for row in iter_csv(zf, members["pathways.txt"]):
                    pathway_count += 1
                    pid = (row.get("pathway_id") or "").strip()
                    if not pid or pid in seen_pathway_ids:
                        raise ValueError("pathways.txt pathway_id가 비어 있거나 중복되었습니다.")
                    seen_pathway_ids.add(pid)
                    from_path = check.execute("SELECT location_type,stop_access FROM stop_ids WHERE id=?", ((row.get("from_stop_id") or "").strip(),)).fetchone()
                    to_path = check.execute("SELECT location_type,stop_access FROM stop_ids WHERE id=?", ((row.get("to_stop_id") or "").strip(),)).fetchone()
                    if not from_path:
                        raise ValueError("pathways.txt from_stop_id가 stops.txt에 없습니다.")
                    if not to_path:
                        raise ValueError("pathways.txt to_stop_id가 stops.txt에 없습니다.")
                    if (int(from_path[0] or 0) == 1 or int(to_path[0] or 0) == 1
                            or str(from_path[1] or "").strip() == "1" or str(to_path[1] or "").strip() == "1"):
                        raise ValueError("pathways.txt는 역 자체(location_type=1) 또는 stop_access=1 노드에 연결할 수 없습니다.")
                    mode = int(row.get("pathway_mode") or 0)
                    if mode not in range(1, 8):
                        raise ValueError("pathways.txt pathway_mode는 1~7이어야 합니다.")
                    raw_direction = (row.get("is_bidirectional") or "").strip()
                    if raw_direction not in ("0", "1"):
                        raise ValueError("pathways.txt is_bidirectional은 필수이며 0 또는 1이어야 합니다.")
                    if mode == 7 and raw_direction == "1":
                        raise ValueError("pathways.txt exit gate(pathway_mode=7)는 양방향일 수 없습니다.")
                    for field in ("length", "traversal_time"):
                        raw = (row.get(field) or "").strip()
                        if raw:
                            try:
                                number = float(raw)
                                if number < 0 or not math.isfinite(number) or (field == "traversal_time" and (not number.is_integer() or number <= 0)):
                                    raise ValueError()
                            except Exception as exc:
                                raise ValueError(f"pathways.txt {field} 값이 유효하지 않습니다.") from exc
                counts["pathways.txt"] = pathway_count
            if "shapes.txt" in members:
                counts["shapes.txt"] = sum(1 for _ in iter_csv(zf, members["shapes.txt"]))
            if "frequencies.txt" in members:
                raise ValueError("현재 B-ROUTE 엔진은 frequencies.txt를 지원하지 않습니다.")
        finally:
            check.close()
    return {"valid": True, "counts": counts, "warnings": warnings,
            "uncompressed_bytes": uncompressed,
            "coverage_note": "구조 및 참조 무결성 검사 통과. 실제 운행 정확도, 모든 노선 포함 여부 및 시간표 현장 정확성은 보증하지 않습니다."}


def read_batches(zf: zipfile.ZipFile, member: str, mapper, batch_rows: int = BATCH_ROWS):
    batch = []
    for row in iter_csv(zf, member):
        value = mapper(row)
        if value is not None:
            batch.append(value)
        if len(batch) >= batch_rows:
            yield batch
            batch = []
    if batch:
        yield batch


def _delete_feed_rows(con, feed_id: str) -> None:
    for table in ("gtfs_transfers", "gtfs_pathways", "stop_times", "shapes", "trips", "routes", "stops", "calendars", "calendar_dates"):
        con.execute(f"DELETE FROM {table} WHERE feed_id=?", (feed_id,))
    con.execute("DELETE FROM data_releases WHERE feed_id=?", (feed_id,))
    con.execute("DELETE FROM data_import_jobs WHERE imported_feed_id=?", (feed_id,))
    con.execute("DELETE FROM feeds WHERE feed_id=?", (feed_id,))
    con.commit()


def import_archive_in_batches(path: Path, job: dict[str, Any], checksum: str, validation: dict[str, Any]) -> dict[str, Any]:
    job_id = job["job_id"]
    feed_id = job["feed_id"]
    actor = {"sub": "gtfs-worker", "email": "gtfs-worker"}
    with zipfile.ZipFile(path, "r") as zf:
        members, _ = safe_members(zf)
        with closing(api.db()) as con:
            source = con.execute("SELECT name,source_url,license_name,active,dataset_type FROM data_sources WHERE source_id=?", (job["source_id"],)).fetchone()
            if not source or not source[3] or source[4] != "gtfs_static":
                raise ValueError("등록된 GTFS 출처가 비활성화되었거나 유형이 변경되었습니다.")
            _delete_feed_rows(con, feed_id)
            now = now_iso()
            agency_name = next(iter_csv(zf, members["agency.txt"])).get("agency_name", "")
            counts = validation["counts"]
            con.execute("INSERT INTO feeds(feed_id,name,agency,imported_at,stop_count,route_count,trip_count,source_id,source_version,effective_date,license_name,source_url,sha256,is_active) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,0)",
                (feed_id, job["file_name"], agency_name, now, int(counts.get("stops.txt",0)), int(counts.get("routes.txt",0)), int(counts.get("trips.txt",0)), job["source_id"], job["source_version"][:80], job["effective_date"][:10], source[2], source[1], checksum))
            con.commit()

        total_rows = max(1, sum(int(v) for v in validation["counts"].values()))
        processed = 0
        def progress(phase: str, amount: int):
            nonlocal processed
            processed += amount
            pct = min(95, 5 + int(processed / total_rows * 90))
            update_job(job_id, progress_percent=pct, progress_phase=phase, processed_rows=processed)

        def map_transfer(x):
            identity = [feed_id, x.get("from_stop_id"), x.get("to_stop_id"), x.get("from_trip_id"),
                        x.get("to_trip_id"), x.get("from_route_id"), x.get("to_route_id"), x.get("transfer_type")]
            row_id = hashlib.sha256(json.dumps(identity, ensure_ascii=False).encode()).hexdigest()
            minimum = x.get("min_transfer_time")
            return (row_id, feed_id, x.get("from_stop_id", ""), x.get("to_stop_id", ""),
                    x.get("from_trip_id", ""), x.get("to_trip_id", ""), x.get("from_route_id", ""),
                    x.get("to_route_id", ""), int(x.get("transfer_type") or 0),
                    int(minimum) if minimum not in (None, "") else None)

        def map_pathway(x):
            return (feed_id, x.get("pathway_id", ""), x.get("from_stop_id", ""),
                    x.get("to_stop_id", ""), int(x.get("pathway_mode") or 1),
                    int(x.get("is_bidirectional") or 0), api._safe_float(x.get("length")),
                    int(x.get("traversal_time") or 0) if x.get("traversal_time") else None)

        specs = [
            ("stops.txt", "INSERT INTO stops(feed_id,stop_id,name,lat,lon,parent_station,location_type,wheelchair_boarding,platform_code) VALUES(?,?,?,?,?,?,?,?,?) ON CONFLICT(feed_id,stop_id) DO UPDATE SET name=excluded.name,lat=excluded.lat,lon=excluded.lon,parent_station=excluded.parent_station,location_type=excluded.location_type,wheelchair_boarding=excluded.wheelchair_boarding,platform_code=excluded.platform_code",
             lambda x: (feed_id,x.get("stop_id", ""),x.get("stop_name", "정류장"),float(x.get("stop_lat") or 0),float(x.get("stop_lon") or 0),x.get("parent_station", ""),int(x.get("location_type") or 0),int(x.get("wheelchair_boarding") or 0),x.get("platform_code", ""))),
            ("routes.txt", "INSERT INTO routes VALUES(?,?,?,?,?,?) ON CONFLICT(feed_id,route_id) DO UPDATE SET short_name=excluded.short_name,long_name=excluded.long_name,route_type=excluded.route_type,color=excluded.color",
             lambda x: (feed_id,x.get("route_id", ""),x.get("route_short_name", ""),x.get("route_long_name", ""),int(x.get("route_type") or 3),x.get("route_color", ""))),
            ("trips.txt", "INSERT INTO trips VALUES(?,?,?,?,?,?,?) ON CONFLICT(feed_id,trip_id) DO UPDATE SET route_id=excluded.route_id,service_id=excluded.service_id,headsign=excluded.headsign,direction_id=excluded.direction_id,shape_id=excluded.shape_id",
             lambda x: (feed_id,x.get("trip_id", ""),x.get("route_id", ""),x.get("service_id", ""),x.get("trip_headsign", ""),x.get("direction_id", ""),x.get("shape_id", ""))),
            ("shapes.txt", "INSERT INTO shapes VALUES(?,?,?,?,?) ON CONFLICT(feed_id,shape_id,sequence) DO UPDATE SET lat=excluded.lat,lon=excluded.lon",
             lambda x: (feed_id,x.get("shape_id", ""),int(x.get("shape_pt_sequence") or 0),float(x.get("shape_pt_lat") or 0),float(x.get("shape_pt_lon") or 0)) if x.get("shape_id") and x.get("shape_pt_lat") and x.get("shape_pt_lon") else None),
            ("stop_times.txt", "INSERT INTO stop_times VALUES(?,?,?,?,?,?) ON CONFLICT(feed_id,trip_id,stop_sequence) DO UPDATE SET stop_id=excluded.stop_id,arrival_secs=excluded.arrival_secs,departure_secs=excluded.departure_secs",
             lambda x: (feed_id,x.get("trip_id", ""),x.get("stop_id", ""),int(x.get("stop_sequence") or 0),api.gtfs_time(x.get("arrival_time", "00:00:00")),api.gtfs_time(x.get("departure_time", x.get("arrival_time", "00:00:00"))))),
            ("transfers.txt", "INSERT INTO gtfs_transfers(transfer_row_id,feed_id,from_stop_id,to_stop_id,from_trip_id,to_trip_id,from_route_id,to_route_id,transfer_type,min_transfer_time) VALUES(?,?,?,?,?,?,?,?,?,?) ON CONFLICT(transfer_row_id) DO UPDATE SET min_transfer_time=excluded.min_transfer_time", map_transfer),
            ("pathways.txt", "INSERT INTO gtfs_pathways(feed_id,pathway_id,from_stop_id,to_stop_id,pathway_mode,is_bidirectional,length_m,traversal_time) VALUES(?,?,?,?,?,?,?,?) ON CONFLICT(feed_id,pathway_id) DO UPDATE SET from_stop_id=excluded.from_stop_id,to_stop_id=excluded.to_stop_id,pathway_mode=excluded.pathway_mode,is_bidirectional=excluded.is_bidirectional,length_m=excluded.length_m,traversal_time=excluded.traversal_time", map_pathway),
            ("calendar.txt", "INSERT INTO calendars VALUES(?,?,?,?,?,?,?,?,?,?,?) ON CONFLICT(feed_id,service_id) DO UPDATE SET monday=excluded.monday,tuesday=excluded.tuesday,wednesday=excluded.wednesday,thursday=excluded.thursday,friday=excluded.friday,saturday=excluded.saturday,sunday=excluded.sunday,start_date=excluded.start_date,end_date=excluded.end_date",
             lambda x: (feed_id,x.get("service_id", ""),*[int(x.get(k) or 0) for k in ("monday","tuesday","wednesday","thursday","friday","saturday","sunday")],x.get("start_date", ""),x.get("end_date", ""))),
            ("calendar_dates.txt", "INSERT INTO calendar_dates VALUES(?,?,?,?) ON CONFLICT(feed_id,service_id,service_date) DO UPDATE SET exception_type=excluded.exception_type",
             lambda x: (feed_id,x.get("service_id", ""),x.get("date", ""),int(x.get("exception_type") or 0))),
        ]
        for filename, sql, mapper in specs:
            if filename not in members:
                continue
            phase = f"import:{filename}"
            with closing(api.db()) as con:
                for batch in read_batches(zf, members[filename], mapper):
                    con.executemany(sql, batch)
                    con.commit()
                    progress(phase, len(batch))

    now = now_iso()
    release_id = uuid.uuid4().hex
    validation_json = json.dumps(validation, ensure_ascii=False)
    with closing(api.db()) as con:
        con.execute("UPDATE feeds SET is_active=0 WHERE source_id=? AND feed_id<>?", (job["source_id"], feed_id))
        con.execute("UPDATE data_releases SET status='archived' WHERE source_id=? AND status='active'", (job["source_id"],))
        con.execute("UPDATE feeds SET is_active=1 WHERE feed_id=?", (feed_id,))
        con.execute("INSERT INTO data_releases(release_id,dataset,version,source,effective_date,notes,status,created_by,created_at,feed_id,source_id,checksum,validation_json,activated_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (release_id,job["source_id"],job["source_version"] or now[:10],"COS staged GTFS",job["effective_date"],"GTFS streaming validation passed", "active",job["created_by"],now,feed_id,job["source_id"],checksum,validation_json,now))
        existing = con.execute("SELECT job_id FROM data_import_jobs WHERE job_id=?", (job_id,)).fetchone()
        if existing:
            con.execute("UPDATE data_import_jobs SET status='imported',validation_json=?,imported_feed_id=?,error_message='' WHERE job_id=?", (validation_json,feed_id,job_id))
        else:
            con.execute("INSERT INTO data_import_jobs(job_id,source_id,file_name,file_size,sha256,status,validation_json,created_by,created_at,imported_feed_id,error_message) VALUES(?,?,?,?,?,?,?,?,?,?,?)",
                (job_id,job["source_id"],job["file_name"],job["expected_size"],checksum,"imported",validation_json,job["created_by"],now,feed_id,""))
        api._audit(con,actor,"gtfs.staging.import","feed",feed_id,None,{"release_id":release_id,"sha256":checksum},"COS staging GTFS 배치 가져오기 완료")
        con.execute("UPDATE gtfs_staging_uploads SET status='completed',progress_percent=100,progress_phase='completed',processed_rows=?,actual_sha256=?,feed_id=?,release_id=?,completed_at=?,updated_at=?,error_message='' WHERE job_id=?",
                    (processed,checksum,feed_id,release_id,now,now,job_id))
        con.commit()
    return {"feed_id": feed_id, "release_id": release_id, "sha256": checksum, "counts": validation["counts"]}


def process_job(job: dict[str, Any]) -> dict[str, Any]:
    job_id = job["job_id"]
    update_job(job_id, status="processing", progress_percent=2, progress_phase="download")
    with tempfile.TemporaryDirectory(prefix="broute-gtfs-worker-") as temp_dir:
        path = Path(temp_dir) / job["file_name"]
        download_object_to_file(job["object_key"], path)
        actual_size = path.stat().st_size
        if actual_size != job["expected_size"]:
            raise ValueError(f"COS 파일 크기 불일치: 예상 {job['expected_size']} / 실제 {actual_size}")
        if actual_size > MAX_COMPRESSED_BYTES:
            raise ValueError("Worker 압축 파일 크기 한도를 초과했습니다.")
        checksum = sha256_file(path)
        if job["expected_sha256"] and checksum.lower() != job["expected_sha256"].lower():
            raise ValueError("SHA-256 체크섬이 업로드 시 전달한 값과 일치하지 않습니다.")
        update_job(job_id, progress_percent=4, progress_phase="validate", actual_sha256=checksum)
        validation = validate_archive_streaming(path)
        update_job(job_id, progress_percent=5, progress_phase="import:starting")
        return import_archive_in_batches(path, job, checksum, validation)


def run_once() -> bool:
    global CURRENT_JOB_ID
    update_worker_heartbeat("idle")
    job = claim_job()
    if not job:
        return False
    job_id = job["job_id"]
    CURRENT_JOB_ID = job_id
    update_worker_heartbeat("processing")
    print(f"[GTFS worker] 시작: {job_id} / {job['file_name']}", flush=True)
    try:
        result = process_job(job)
        update_worker_heartbeat("idle")
        print(f"[GTFS worker] 완료: {job_id} / feed={result['feed_id']} rows={result['counts']}", flush=True)
    except Exception as exc:
        message = str(exc)[:2000]
        try:
            update_job(job_id,status="failed",progress_phase="failed",error_message=message)
            with closing(api.db()) as con:
                con.execute("UPDATE data_import_jobs SET status='failed',error_message=? WHERE job_id=?", (message,job_id))
                con.commit()
            update_worker_heartbeat("error", message)
        except Exception as update_exc:
            print(f"[GTFS worker] 실패 상태 저장 오류: {update_exc}", file=sys.stderr, flush=True)
        print(f"[GTFS worker] 실패: {job_id}: {message}", file=sys.stderr, flush=True)
    finally:
        CURRENT_JOB_ID = ""
    return True


def _heartbeat_loop(stop_event: threading.Event) -> None:
    while not stop_event.wait(30):
        try:
            update_worker_heartbeat(WORKER_STATUS, WORKER_LAST_ERROR)
            # Extend the processing lease while a large download/validation is
            # active. Otherwise another worker could reclaim a healthy job
            # after 15 minutes even though the heartbeat is still alive.
            if CURRENT_JOB_ID:
                with closing(api.db()) as con:
                    con.execute("UPDATE gtfs_staging_uploads SET updated_at=? WHERE job_id=? AND status='processing'",
                                (now_iso(), CURRENT_JOB_ID))
                    con.commit()
        except Exception as exc:
            print(f"[GTFS worker] heartbeat 갱신 실패: {exc}", file=sys.stderr, flush=True)


def main() -> int:
    parser = argparse.ArgumentParser(description="B-ROUTE COS GTFS batch worker")
    parser.add_argument("--once", action="store_true", help="대기열 작업을 최대 1개 처리하고 종료")
    parser.add_argument("--poll-seconds", type=int, default=POLL_SECONDS)
    parser.add_argument("--allow-sqlite", action="store_true", help="로컬 개발/테스트용 SQLite 사용 허용")
    args = parser.parse_args()
    if not api.DB_IS_POSTGRES and not args.allow_sqlite:
        print("운영 Worker는 PostgreSQL DATABASE_URL이 필요합니다. 로컬 테스트에서만 --allow-sqlite를 사용하세요.", file=sys.stderr)
        return 2
    if not api.cos_is_configured():
        print("COS_SECRET_ID/KEY/BUCKET/REGION 설정이 필요합니다.", file=sys.stderr)
        return 2
    api.init_db()
    update_worker_heartbeat("starting")
    if args.once:
        run_once()
        update_worker_heartbeat("stopped")
        return 0
    stop_event = threading.Event()
    heartbeat_thread = threading.Thread(target=_heartbeat_loop, args=(stop_event,), daemon=True)
    heartbeat_thread.start()
    print(f"[GTFS worker] 시작 · id={WORKER_ID} · batch_rows={BATCH_ROWS} poll={args.poll_seconds}s", flush=True)
    try:
        while True:
            did_work = run_once()
            if not did_work:
                update_worker_heartbeat("idle")
                time.sleep(max(3,args.poll_seconds))
    except KeyboardInterrupt:
        update_worker_heartbeat("stopping")
    finally:
        stop_event.set()
        heartbeat_thread.join(timeout=3)
        update_worker_heartbeat("stopped")


if __name__ == "__main__":
    raise SystemExit(main())
