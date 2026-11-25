from __future__ import annotations

import base64
import csv
import hashlib
import hmac
import html as html_lib
import io
import json
import math
import os
import re
import sqlite3
import time
import uuid
import secrets
import zipfile
from bisect import bisect_left
from collections import defaultdict
from contextlib import asynccontextmanager, closing
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any, Literal
from urllib.parse import urlencode
from zoneinfo import ZoneInfo

import httpx
from dotenv import load_dotenv
from fastapi import FastAPI, File, Form, Header, HTTPException, Query, Request, Response, UploadFile
from fastapi.responses import RedirectResponse
from pydantic import BaseModel, Field

load_dotenv()
BASE_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = Path(os.getenv("DATA_DIR", "/tmp/broute-data"))
DATA_DIR.mkdir(parents=True, exist_ok=True)
DB_PATH = Path(os.getenv("DATABASE_PATH", DATA_DIR / "broute.sqlite3"))
DATABASE_URL = os.getenv("DATABASE_URL", "").strip()
APP_ENV = os.getenv("APP_ENV", "production").strip().lower()
APP_VERSION = os.getenv("APP_VERSION", "2.0.0-beta.1").strip() or "2.0.0-beta.1"
DB_IS_POSTGRES = DATABASE_URL.startswith(("postgresql://", "postgres://"))
TZ = ZoneInfo(os.getenv("APP_TIMEZONE", "Asia/Seoul"))
DATA_GO_KEY = os.getenv("DATA_GO_KR_SERVICE_KEY", "").strip()
# Official current TAGO TrainInfo service root; can be overridden if the portal
# account is provisioned against a legacy service path.
TAGO_TRAIN_SERVICE_NAME = os.getenv("TAGO_TRAIN_SERVICE_NAME", "TrainInfo").strip() or "TrainInfo"
# Exact operation casing published in the current data.go.kr TrainInfo OpenAPI.
TAGO_TRAIN_OP_CITY_CODES = "GetCtyCodeList"
TAGO_TRAIN_OP_STATIONS = "GetCtyAcctoTrainSttnList"
TAGO_TRAIN_OP_TIMETABLE = "GetStrtpntAlocFndTrainInfo"
PROVIDER_CACHE: dict[str, tuple[float, dict[str, Any]]] = {}
PROVIDER_CACHE_MAX = 512
PROVIDER_RATE_STATE: dict[str, list[float]] = {}
PROVIDER_RATE_LIMIT_PER_MINUTE = max(10, min(120, int(os.getenv("PROVIDER_RATE_LIMIT_PER_MINUTE", "60"))))
KAKAO_REST_KEY = os.getenv("KAKAO_REST_API_KEY", "").strip()
ADMIN_TOKEN = os.getenv("ADMIN_TOKEN", "").strip()
GOOGLE_CLIENT_ID = os.getenv("GOOGLE_CLIENT_ID", "").strip()
GOOGLE_ADMIN_SUB = os.getenv("GOOGLE_ADMIN_SUB", "").strip()
GOOGLE_ADMIN_EMAIL = os.getenv("GOOGLE_ADMIN_EMAIL", "").strip().lower()
SESSION_SECRET = os.getenv("SESSION_SECRET", "").strip()
APP_ORIGIN = os.getenv("APP_ORIGIN", "").strip().rstrip("/")
# Transactional project invitations. The sender key is server-only; it is
# never returned by /auth/config, /health, or administrator status endpoints.
RESEND_API_KEY = os.getenv("RESEND_API_KEY", "").strip()
INVITE_FROM_EMAIL = os.getenv("INVITE_FROM_EMAIL", "").strip().lower()
# Business contact mailbox is used as Reply-To; Resend From must be a verified domain.
INVITE_REPLY_TO_EMAIL = os.getenv("INVITE_REPLY_TO_EMAIL", "broute.site.app@gmail.com").strip().lower()
RESEND_WEBHOOK_SECRET = os.getenv("RESEND_WEBHOOK_SECRET", "").strip()
RESEND_WEBHOOK_TOLERANCE_SECONDS = max(60, min(900, int(os.getenv("RESEND_WEBHOOK_TOLERANCE_SECONDS", "300"))))
INVITE_FROM_NAME = os.getenv("INVITE_FROM_NAME", "B-ROUTE").strip()[:80] or "B-ROUTE"
INVITE_EMAIL_DAILY_LIMIT = max(1, min(100, int(os.getenv("INVITE_EMAIL_DAILY_LIMIT", "80"))))
RESEND_HTTP_TRANSPORT = None  # Injected only by isolated tests; production uses normal HTTPS.
NAVER_CLIENT_ID = os.getenv("NAVER_CLIENT_ID", "").strip()
NAVER_CLIENT_SECRET = os.getenv("NAVER_CLIENT_SECRET", "").strip()
NAVER_REDIRECT_URI = os.getenv("NAVER_REDIRECT_URI", "").strip()
MICROSOFT_CLIENT_ID = os.getenv("MICROSOFT_CLIENT_ID", "").strip()
MICROSOFT_CLIENT_SECRET = os.getenv("MICROSOFT_CLIENT_SECRET", "").strip()
MICROSOFT_TENANT = os.getenv("MICROSOFT_TENANT", "common").strip() or "common"
MICROSOFT_REDIRECT_URI = os.getenv("MICROSOFT_REDIRECT_URI", "").strip()
OAUTH_STATE_COOKIE = "broute_oauth_state"
SESSION_COOKIE = "broute_session"
SESSION_TTL_SECONDS = 7 * 24 * 60 * 60
BETA_RELEASE_APPROVED = os.getenv("BETA_RELEASE_APPROVED", "false").strip().lower() == "true"
CLOUD_QUOTA_DEFAULT_MB = 1000
CLOUD_FILE_MAX_BYTES = 5 * 1024 * 1024
PHOTON_URL = os.getenv("PHOTON_URL", "https://photon.komoot.io/api/")

@asynccontextmanager
async def lifespan(_app: FastAPI):
    init_db()
    yield


GTFS_STAGING_MAX_BYTES = int(os.getenv("GTFS_STAGING_MAX_BYTES", str(2 * 1024 * 1024 * 1024)))
GTFS_STAGING_PART_SIZE = max(8, int(os.getenv("GTFS_STAGING_PART_SIZE_MB", "16"))) * 1024 * 1024
GTFS_STAGING_URL_TTL = 900

app = FastAPI(title="B-ROUTE API", version=APP_VERSION, description="B-ROUTE multimodal routing, collaboration and read-only sharing", lifespan=lifespan)


@app.middleware("http")
async def apply_security_headers(request: Request, call_next):
    response = await call_next(request)
    response.headers.setdefault("Referrer-Policy", "no-referrer")
    response.headers.setdefault("X-Content-Type-Options", "nosniff")
    if "/project-invites/" in request.url.path:
        response.headers["Cache-Control"] = "no-store, max-age=0"
        response.headers["X-Robots-Tag"] = "noindex, nofollow"
    return response


class CompatRow(dict):
    """Mapping row that also supports SQLite-style numeric indexing."""
    def __getitem__(self, key):
        if isinstance(key, int):
            return list(self.values())[key]
        return super().__getitem__(key)


def _pg_row_factory(cursor):
    names = [column.name for column in cursor.description]
    return lambda values: CompatRow(zip(names, values))


class PostgresConnectionAdapter:
    """Small adapter for qmark SQL shared by local SQLite and PostgreSQL."""
    def __init__(self, connection):
        self.connection = connection

    @staticmethod
    def _sql(statement: str) -> str:
        return statement.replace("?", "%s")

    def execute(self, statement, params=()):
        if statement.lstrip().upper().startswith("PRAGMA"):
            return self.connection.execute("SELECT 1")
        return self.connection.execute(self._sql(statement), params)

    def executemany(self, statement, seq):
        return self.connection.cursor().executemany(self._sql(statement), seq)

    def executescript(self, script):
        for statement in script.split(";"):
            sql = statement.strip()
            if sql and not sql.upper().startswith("PRAGMA"):
                self.connection.execute(sql)

    def commit(self):
        self.connection.commit()

    def close(self):
        self.connection.close()


def db():
    if DB_IS_POSTGRES:
        try:
            import psycopg
            url = DATABASE_URL.replace("postgres://", "postgresql://", 1)
            return PostgresConnectionAdapter(psycopg.connect(url, row_factory=_pg_row_factory, connect_timeout=8))
        except ImportError as exc:
            raise RuntimeError("PostgreSQL 사용을 위해 psycopg[binary] 설치가 필요합니다.") from exc
    con = sqlite3.connect(DB_PATH, timeout=15)
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA foreign_keys=ON")
    return con


def durable_database_ready() -> bool:
    return DB_IS_POSTGRES


def require_durable_database() -> None:
    if APP_ENV == "production" and not durable_database_ready():
        raise HTTPException(503, "영구 데이터베이스가 연결되지 않았습니다. 운영 환경의 DATABASE_URL 설정 후 이용할 수 있습니다.")


def require_user(request: Request) -> dict[str, Any]:
    claims = _read_session(request)
    if not claims:
        raise HTTPException(401, "이 기능은 지원 계정으로 로그인한 뒤 이용할 수 있습니다.")
    return claims


def _setting_value(con, key: str, default):
    row = con.execute("SELECT value_json FROM app_settings WHERE setting_key=?", (key,)).fetchone()
    if not row:
        return default
    try:
        return json.loads(row[0])
    except Exception:
        return default


def _audit(con, actor: dict[str, Any], action: str, target_type: str, target_id: str,
           before: Any, after: Any, reason: str = "") -> None:
    con.execute("INSERT INTO admin_audit_logs(log_id,actor_sub,actor_email,action,target_type,target_id,before_json,after_json,reason,created_at) VALUES(?,?,?,?,?,?,?,?,?,?)",
        (uuid.uuid4().hex, str(actor.get("sub", "")), str(actor.get("email", "")), action,
         target_type, target_id, json.dumps(before, ensure_ascii=False) if before is not None else None,
         json.dumps(after, ensure_ascii=False) if after is not None else None, reason[:500], datetime.now(TZ).isoformat()))


def cos_is_configured() -> bool:
    required = ("COS_SECRET_ID", "COS_SECRET_KEY", "COS_BUCKET", "COS_REGION")
    return all(os.getenv(key, "").strip() for key in required)


def cos_client():
    if not cos_is_configured():
        raise HTTPException(503, "클라우드 저장소(COS)가 아직 설정되지 않았습니다.")
    try:
        from qcloud_cos import CosConfig, CosS3Client
        kwargs = {"Region": os.environ["COS_REGION"].strip(), "SecretId": os.environ["COS_SECRET_ID"].strip(),
                  "SecretKey": os.environ["COS_SECRET_KEY"].strip(), "Scheme": "https"}
        token = os.getenv("COS_SESSION_TOKEN", "").strip()
        if token:
            kwargs["Token"] = token
        return CosS3Client(CosConfig(**kwargs))
    except ImportError as exc:
        raise HTTPException(503, "COS SDK가 설치되지 않았습니다. requirements.txt를 확인하세요.") from exc


def safe_filename(name: str) -> str:
    name = Path(name or "route.broute").name
    name = re.sub(r"[^0-9A-Za-z가-힣._ -]", "_", name).strip(" .")
    if not name:
        name = "route.broute"
    if not name.lower().endswith(".broute"):
        name += ".broute"
    return name[:120]


def init_db() -> None:
    with closing(db()) as con:
        con.executescript("""
        PRAGMA journal_mode=WAL;
        CREATE TABLE IF NOT EXISTS feeds (
          feed_id TEXT PRIMARY KEY, name TEXT NOT NULL, agency TEXT, imported_at TEXT NOT NULL,
          stop_count INTEGER NOT NULL DEFAULT 0, route_count INTEGER NOT NULL DEFAULT 0, trip_count INTEGER NOT NULL DEFAULT 0,
          source_id TEXT, source_version TEXT NOT NULL DEFAULT '', effective_date TEXT NOT NULL DEFAULT '',
          license_name TEXT NOT NULL DEFAULT '', source_url TEXT NOT NULL DEFAULT '', sha256 TEXT NOT NULL DEFAULT '',
          is_active INTEGER NOT NULL DEFAULT 1
        );
        CREATE TABLE IF NOT EXISTS stops (
          feed_id TEXT NOT NULL, stop_id TEXT NOT NULL, name TEXT, lat REAL NOT NULL, lon REAL NOT NULL,
          parent_station TEXT NOT NULL DEFAULT '', location_type INTEGER NOT NULL DEFAULT 0,
          wheelchair_boarding INTEGER NOT NULL DEFAULT 0, platform_code TEXT NOT NULL DEFAULT '',
          PRIMARY KEY(feed_id, stop_id), FOREIGN KEY(feed_id) REFERENCES feeds(feed_id) ON DELETE CASCADE
        );
        CREATE INDEX IF NOT EXISTS idx_stops_latlon ON stops(lat, lon);
        CREATE TABLE IF NOT EXISTS routes (
          feed_id TEXT NOT NULL, route_id TEXT NOT NULL, short_name TEXT, long_name TEXT, route_type INTEGER,
          color TEXT, PRIMARY KEY(feed_id, route_id)
        );
        CREATE TABLE IF NOT EXISTS trips (
          feed_id TEXT NOT NULL, trip_id TEXT NOT NULL, route_id TEXT NOT NULL, service_id TEXT NOT NULL,
          headsign TEXT, direction_id TEXT, shape_id TEXT, PRIMARY KEY(feed_id, trip_id)
        );
        CREATE TABLE IF NOT EXISTS shapes (
          feed_id TEXT NOT NULL, shape_id TEXT NOT NULL, sequence INTEGER NOT NULL, lat REAL NOT NULL, lon REAL NOT NULL,
          PRIMARY KEY(feed_id, shape_id, sequence)
        );
        CREATE INDEX IF NOT EXISTS idx_shapes_id ON shapes(feed_id, shape_id, sequence);
        CREATE INDEX IF NOT EXISTS idx_trips_service ON trips(feed_id, service_id);
        CREATE TABLE IF NOT EXISTS stop_times (
          feed_id TEXT NOT NULL, trip_id TEXT NOT NULL, stop_id TEXT NOT NULL,
          stop_sequence INTEGER NOT NULL, arrival_secs INTEGER NOT NULL, departure_secs INTEGER NOT NULL,
          PRIMARY KEY(feed_id, trip_id, stop_sequence)
        );
        CREATE INDEX IF NOT EXISTS idx_stop_times_stop ON stop_times(feed_id, stop_id, departure_secs);
        CREATE INDEX IF NOT EXISTS idx_stop_times_trip ON stop_times(feed_id, trip_id, stop_sequence);
        CREATE TABLE IF NOT EXISTS gtfs_transfers (
          transfer_row_id TEXT PRIMARY KEY, feed_id TEXT NOT NULL,
          from_stop_id TEXT NOT NULL, to_stop_id TEXT NOT NULL,
          from_trip_id TEXT NOT NULL DEFAULT '', to_trip_id TEXT NOT NULL DEFAULT '',
          from_route_id TEXT NOT NULL DEFAULT '', to_route_id TEXT NOT NULL DEFAULT '',
          transfer_type INTEGER NOT NULL DEFAULT 0, min_transfer_time INTEGER,
          FOREIGN KEY(feed_id) REFERENCES feeds(feed_id) ON DELETE CASCADE
        );
        CREATE INDEX IF NOT EXISTS idx_gtfs_transfers_stops ON gtfs_transfers(feed_id,from_stop_id,to_stop_id);
        CREATE TABLE IF NOT EXISTS gtfs_pathways (
          feed_id TEXT NOT NULL, pathway_id TEXT NOT NULL,
          from_stop_id TEXT NOT NULL, to_stop_id TEXT NOT NULL,
          pathway_mode INTEGER NOT NULL, is_bidirectional INTEGER NOT NULL DEFAULT 0,
          length_m REAL, traversal_time INTEGER,
          PRIMARY KEY(feed_id,pathway_id), FOREIGN KEY(feed_id) REFERENCES feeds(feed_id) ON DELETE CASCADE
        );
        CREATE INDEX IF NOT EXISTS idx_gtfs_pathways_from ON gtfs_pathways(feed_id,from_stop_id);
        CREATE INDEX IF NOT EXISTS idx_gtfs_pathways_to ON gtfs_pathways(feed_id,to_stop_id);
        CREATE TABLE IF NOT EXISTS calendars (
          feed_id TEXT NOT NULL, service_id TEXT NOT NULL, monday INTEGER, tuesday INTEGER, wednesday INTEGER,
          thursday INTEGER, friday INTEGER, saturday INTEGER, sunday INTEGER, start_date TEXT, end_date TEXT,
          PRIMARY KEY(feed_id, service_id)
        );
        CREATE TABLE IF NOT EXISTS calendar_dates (
          feed_id TEXT NOT NULL, service_id TEXT NOT NULL, service_date TEXT NOT NULL, exception_type INTEGER,
          PRIMARY KEY(feed_id, service_id, service_date)
        );
        CREATE TABLE IF NOT EXISTS shares (
          share_id TEXT PRIMARY KEY, plan_json TEXT NOT NULL, created_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS route_shares (
          share_id TEXT PRIMARY KEY, token_hash TEXT NOT NULL UNIQUE, owner_sub TEXT NOT NULL,
          plan_json TEXT NOT NULL, result_json TEXT NOT NULL DEFAULT '{}',
          created_at TEXT NOT NULL, expires_at TEXT NOT NULL, revoked_at TEXT,
          view_count INTEGER NOT NULL DEFAULT 0, max_views INTEGER NOT NULL DEFAULT 100
        );
        CREATE INDEX IF NOT EXISTS idx_route_shares_owner ON route_shares(owner_sub, created_at);
        CREATE TABLE IF NOT EXISTS projects (
          project_id TEXT PRIMARY KEY, owner_sub TEXT NOT NULL, name TEXT NOT NULL,
          description TEXT NOT NULL DEFAULT '', created_at TEXT NOT NULL, updated_at TEXT NOT NULL,
          archived_at TEXT
        );
        CREATE INDEX IF NOT EXISTS idx_projects_owner ON projects(owner_sub, updated_at);
        CREATE TABLE IF NOT EXISTS project_members (
          project_id TEXT NOT NULL, user_sub TEXT NOT NULL, email TEXT NOT NULL DEFAULT '',
          role TEXT NOT NULL CHECK(role IN ('owner','editor','viewer')),
          invited_by TEXT NOT NULL DEFAULT '', joined_at TEXT NOT NULL,
          PRIMARY KEY(project_id,user_sub),
          FOREIGN KEY(project_id) REFERENCES projects(project_id) ON DELETE CASCADE
        );
        CREATE INDEX IF NOT EXISTS idx_project_members_user ON project_members(user_sub, project_id);
        CREATE TABLE IF NOT EXISTS project_invites (
          invite_id TEXT PRIMARY KEY, project_id TEXT NOT NULL, invite_email TEXT NOT NULL,
          role TEXT NOT NULL CHECK(role IN ('editor','viewer')), token_hash TEXT NOT NULL UNIQUE,
          created_by TEXT NOT NULL, created_at TEXT NOT NULL, expires_at TEXT NOT NULL,
          accepted_by TEXT, accepted_at TEXT, revoked_at TEXT,
          FOREIGN KEY(project_id) REFERENCES projects(project_id) ON DELETE CASCADE
        );
        CREATE INDEX IF NOT EXISTS idx_project_invites_project ON project_invites(project_id, created_at);
        CREATE TABLE IF NOT EXISTS project_invite_email_events (
          event_id TEXT PRIMARY KEY, invite_id TEXT NOT NULL, project_id TEXT NOT NULL,
          recipient_email TEXT NOT NULL, provider TEXT NOT NULL DEFAULT 'resend',
          status TEXT NOT NULL, provider_message_id TEXT NOT NULL DEFAULT '',
          error_code TEXT NOT NULL DEFAULT '', actor_sub TEXT NOT NULL DEFAULT '',
          created_at TEXT NOT NULL,
          FOREIGN KEY(invite_id) REFERENCES project_invites(invite_id) ON DELETE CASCADE,
          FOREIGN KEY(project_id) REFERENCES projects(project_id) ON DELETE CASCADE
        );
        CREATE INDEX IF NOT EXISTS idx_project_invite_email_events_day ON project_invite_email_events(created_at, status);
        CREATE INDEX IF NOT EXISTS idx_project_invite_email_events_invite ON project_invite_email_events(invite_id, created_at);
        CREATE TABLE IF NOT EXISTS provider_webhook_events (
          event_id TEXT PRIMARY KEY, provider TEXT NOT NULL, event_type TEXT NOT NULL,
          provider_message_id TEXT NOT NULL DEFAULT '', received_at TEXT NOT NULL,
          payload_sha256 TEXT NOT NULL DEFAULT ''
        );
        CREATE INDEX IF NOT EXISTS idx_provider_webhook_message ON provider_webhook_events(provider, provider_message_id);
        CREATE TABLE IF NOT EXISTS project_routes (
          route_id TEXT PRIMARY KEY, project_id TEXT NOT NULL, title TEXT NOT NULL,
          plan_json TEXT NOT NULL, result_json TEXT NOT NULL DEFAULT '{}', version INTEGER NOT NULL DEFAULT 1,
          created_by TEXT NOT NULL, updated_by TEXT NOT NULL, created_at TEXT NOT NULL, updated_at TEXT NOT NULL,
          FOREIGN KEY(project_id) REFERENCES projects(project_id) ON DELETE CASCADE
        );
        CREATE INDEX IF NOT EXISTS idx_project_routes_project ON project_routes(project_id, updated_at);
        CREATE TABLE IF NOT EXISTS project_route_versions (
          version_id TEXT PRIMARY KEY, project_id TEXT NOT NULL, route_id TEXT NOT NULL,
          version INTEGER NOT NULL, title TEXT NOT NULL DEFAULT '',
          plan_json TEXT NOT NULL, result_json TEXT NOT NULL DEFAULT '{}',
          saved_by TEXT NOT NULL, created_at TEXT NOT NULL,
          FOREIGN KEY(project_id) REFERENCES projects(project_id) ON DELETE CASCADE,
          FOREIGN KEY(route_id) REFERENCES project_routes(route_id) ON DELETE CASCADE
        );
        CREATE INDEX IF NOT EXISTS idx_project_route_versions ON project_route_versions(route_id, version);
        CREATE TABLE IF NOT EXISTS project_route_shares (
          share_id TEXT PRIMARY KEY, project_id TEXT NOT NULL, route_id TEXT NOT NULL,
          token_hash TEXT NOT NULL UNIQUE, created_by TEXT NOT NULL, created_at TEXT NOT NULL,
          expires_at TEXT NOT NULL, revoked_at TEXT, view_count INTEGER NOT NULL DEFAULT 0,
          max_views INTEGER NOT NULL DEFAULT 100,
          FOREIGN KEY(project_id) REFERENCES projects(project_id) ON DELETE CASCADE,
          FOREIGN KEY(route_id) REFERENCES project_routes(route_id) ON DELETE CASCADE
        );
        CREATE INDEX IF NOT EXISTS idx_project_route_shares_route ON project_route_shares(route_id, created_at);
        CREATE TABLE IF NOT EXISTS feedback (
          feedback_id TEXT PRIMARY KEY, payload_json TEXT NOT NULL, created_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS users (
          user_sub TEXT PRIMARY KEY, email TEXT NOT NULL, name TEXT NOT NULL DEFAULT '',
          storage_used_bytes INTEGER NOT NULL DEFAULT 0, created_at TEXT NOT NULL, last_login_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS cloud_files (
          file_id TEXT PRIMARY KEY, owner_sub TEXT NOT NULL, file_name TEXT NOT NULL,
          object_key TEXT NOT NULL UNIQUE, size_bytes INTEGER NOT NULL, content_type TEXT NOT NULL,
          created_at TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_cloud_files_owner ON cloud_files(owner_sub, created_at);
        CREATE TABLE IF NOT EXISTS admin_audit_logs (
          log_id TEXT PRIMARY KEY, actor_sub TEXT NOT NULL, actor_email TEXT NOT NULL,
          action TEXT NOT NULL, target_type TEXT NOT NULL, target_id TEXT NOT NULL,
          before_json TEXT, after_json TEXT, reason TEXT NOT NULL DEFAULT '', created_at TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_admin_audit_created ON admin_audit_logs(created_at);
        CREATE TABLE IF NOT EXISTS app_settings (
          setting_key TEXT PRIMARY KEY, value_json TEXT NOT NULL, updated_by TEXT NOT NULL,
          updated_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS data_releases (
          release_id TEXT PRIMARY KEY, dataset TEXT NOT NULL, version TEXT NOT NULL,
          source TEXT NOT NULL, effective_date TEXT NOT NULL, notes TEXT NOT NULL DEFAULT '',
          status TEXT NOT NULL, created_by TEXT NOT NULL, created_at TEXT NOT NULL,
          feed_id TEXT, source_id TEXT, checksum TEXT NOT NULL DEFAULT '',
          validation_json TEXT NOT NULL DEFAULT '{}', activated_at TEXT
        );
        CREATE TABLE IF NOT EXISTS data_sources (
          source_id TEXT PRIMARY KEY, name TEXT NOT NULL, provider TEXT NOT NULL,
          dataset_type TEXT NOT NULL, transport_modes_json TEXT NOT NULL DEFAULT '[]',
          country TEXT NOT NULL DEFAULT 'KR', region TEXT NOT NULL DEFAULT '',
          source_url TEXT NOT NULL DEFAULT '', license_name TEXT NOT NULL DEFAULT '',
          update_frequency TEXT NOT NULL DEFAULT 'manual', notes TEXT NOT NULL DEFAULT '',
          active INTEGER NOT NULL DEFAULT 1, created_by TEXT NOT NULL,
          created_at TEXT NOT NULL, updated_at TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_data_sources_active ON data_sources(active, dataset_type);
        CREATE TABLE IF NOT EXISTS data_import_jobs (
          job_id TEXT PRIMARY KEY, source_id TEXT, file_name TEXT NOT NULL,
          file_size INTEGER NOT NULL, sha256 TEXT NOT NULL, status TEXT NOT NULL,
          validation_json TEXT NOT NULL, created_by TEXT NOT NULL,
          created_at TEXT NOT NULL, imported_feed_id TEXT, error_message TEXT NOT NULL DEFAULT ''
        );
        CREATE INDEX IF NOT EXISTS idx_data_import_jobs_created ON data_import_jobs(created_at);
        CREATE TABLE IF NOT EXISTS gtfs_staging_uploads (
          job_id TEXT PRIMARY KEY, source_id TEXT NOT NULL, file_name TEXT NOT NULL,
          expected_size INTEGER NOT NULL, object_key TEXT NOT NULL UNIQUE,
          cos_upload_id TEXT NOT NULL DEFAULT '', source_version TEXT NOT NULL DEFAULT '',
          effective_date TEXT NOT NULL DEFAULT '', expected_sha256 TEXT NOT NULL DEFAULT '',
          actual_sha256 TEXT NOT NULL DEFAULT '', status TEXT NOT NULL,
          progress_percent INTEGER NOT NULL DEFAULT 0, progress_phase TEXT NOT NULL DEFAULT 'uploading',
          processed_rows INTEGER NOT NULL DEFAULT 0, created_by TEXT NOT NULL,
          created_at TEXT NOT NULL, updated_at TEXT NOT NULL, completed_at TEXT,
          feed_id TEXT NOT NULL DEFAULT '', release_id TEXT NOT NULL DEFAULT '',
          error_message TEXT NOT NULL DEFAULT ''
        );
        CREATE INDEX IF NOT EXISTS idx_gtfs_staging_status_created ON gtfs_staging_uploads(status,created_at);
        CREATE TABLE IF NOT EXISTS gtfs_worker_heartbeats (
          worker_id TEXT PRIMARY KEY, status TEXT NOT NULL, last_seen TEXT NOT NULL,
          version TEXT NOT NULL DEFAULT '2.0.0-beta.1', last_error TEXT NOT NULL DEFAULT ''
        );
        CREATE INDEX IF NOT EXISTS idx_gtfs_worker_heartbeat_seen ON gtfs_worker_heartbeats(last_seen);
        """)
        _ensure_feedback_columns(con)
        _ensure_data_columns(con)
        _ensure_gtfs_routing_columns(con)
        _ensure_project_columns(con)
        _ensure_project_invite_columns(con)
        _ensure_invite_email_event_columns(con)
        defaults = {
            "cloud_quota_mb": CLOUD_QUOTA_DEFAULT_MB,
            "max_cloud_file_mb": 5,
            "maintenance_mode": False,
            "feedback_enabled": True,
            "route_search_enabled": True,
        }
        for key, value in defaults.items():
            con.execute("INSERT INTO app_settings(setting_key,value_json,updated_by,updated_at) VALUES(?,?,?,?) ON CONFLICT(setting_key) DO NOTHING",
                        (key, json.dumps(value), "system", datetime.now(TZ).isoformat()))
        con.commit()


def _ensure_feedback_columns(con) -> None:
    if DB_IS_POSTGRES:
        rows = con.execute("SELECT column_name FROM information_schema.columns WHERE table_name=?", ("feedback",)).fetchall()
        existing = {r[0] for r in rows}
    else:
        existing = {r[1] for r in con.execute("PRAGMA table_info(feedback)").fetchall()}
    migrations = {
        "user_sub": "TEXT NOT NULL DEFAULT ''",
        "user_email": "TEXT NOT NULL DEFAULT ''",
        "status": "TEXT NOT NULL DEFAULT 'received'",
        "admin_reply": "TEXT NOT NULL DEFAULT ''",
        "reviewed_at": "TEXT",
    }
    for column, definition in migrations.items():
        if column not in existing:
            con.execute(f"ALTER TABLE feedback ADD COLUMN {column} {definition}")


def _ensure_data_columns(con) -> None:
    migrations = {
        "feeds": {
            "source_id": "TEXT", "source_version": "TEXT NOT NULL DEFAULT ''",
            "effective_date": "TEXT NOT NULL DEFAULT ''", "license_name": "TEXT NOT NULL DEFAULT ''",
            "source_url": "TEXT NOT NULL DEFAULT ''", "sha256": "TEXT NOT NULL DEFAULT ''",
            "is_active": "INTEGER NOT NULL DEFAULT 1",
        },
        "data_releases": {
            "feed_id": "TEXT", "source_id": "TEXT", "checksum": "TEXT NOT NULL DEFAULT ''",
            "validation_json": "TEXT NOT NULL DEFAULT '{}'", "activated_at": "TEXT",
        },
    }
    for table, columns in migrations.items():
        if DB_IS_POSTGRES:
            rows = con.execute("SELECT column_name FROM information_schema.columns WHERE table_name=?", (table,)).fetchall()
            existing = {r[0] for r in rows}
        else:
            existing = {r[1] for r in con.execute(f"PRAGMA table_info({table})").fetchall()}
        for column, definition in columns.items():
            if column not in existing:
                con.execute(f"ALTER TABLE {table} ADD COLUMN {column} {definition}")


def _ensure_gtfs_routing_columns(con) -> None:
    """Add GTFS station hierarchy fields to existing 1.5+ databases."""
    if DB_IS_POSTGRES:
        rows = con.execute("SELECT column_name FROM information_schema.columns WHERE table_name=?", ("stops",)).fetchall()
        existing = {r[0] for r in rows}
    else:
        existing = {r[1] for r in con.execute("PRAGMA table_info(stops)").fetchall()}
    migrations = {
        "parent_station": "TEXT NOT NULL DEFAULT ''",
        "location_type": "INTEGER NOT NULL DEFAULT 0",
        "wheelchair_boarding": "INTEGER NOT NULL DEFAULT 0",
        "platform_code": "TEXT NOT NULL DEFAULT ''",
    }
    for column, definition in migrations.items():
        if column not in existing:
            con.execute(f"ALTER TABLE stops ADD COLUMN {column} {definition}")


def _ensure_project_columns(con) -> None:
    """Backward-compatible project schema upgrades for collaborative route history."""
    table = "project_route_versions"
    if DB_IS_POSTGRES:
        rows = con.execute("SELECT column_name FROM information_schema.columns WHERE table_name=?", (table,)).fetchall()
        existing = {r[0] for r in rows}
    else:
        existing = {r[1] for r in con.execute(f"PRAGMA table_info({table})").fetchall()}
    if "title" not in existing:
        con.execute(f"ALTER TABLE {table} ADD COLUMN title TEXT NOT NULL DEFAULT ''")


class Waypoint(BaseModel):
    id: str | None = None
    name: str
    address: str | None = ""
    lat: float = Field(ge=-90, le=90)
    lon: float = Field(ge=-180, le=180)
    stay_minutes: int = Field(default=0, ge=0, le=10080)


class PlanRequest(BaseModel):
    waypoints: list[Waypoint] = Field(min_length=2)
    departure_time: str | None = None
    preference: Literal["fast", "transfer", "walk"] = "fast"
    required_route: str | None = None
    max_walk_m: int = Field(default=1800, ge=200, le=5000)
    mode: Literal["bus", "rail", "transit"] = "transit"


class DataSourceCreate(BaseModel):
    name: str = Field(min_length=2, max_length=160)
    provider: str = Field(min_length=2, max_length=120)
    dataset_type: Literal["gtfs_static", "gtfs_realtime", "rail_timetable", "bus_api", "other"] = "gtfs_static"
    transport_modes: list[Literal["bus", "rail", "ferry", "tram", "other"]] = Field(default_factory=lambda: ["bus"])
    country: str = Field(default="KR", min_length=2, max_length=2)
    region: str = Field(default="", max_length=160)
    source_url: str = Field(default="", max_length=1000)
    license_name: str = Field(default="", max_length=300)
    update_frequency: str = Field(default="manual", max_length=100)
    notes: str = Field(default="", max_length=1000)


class DataSourcePatch(BaseModel):
    active: bool
    reason: str = Field(min_length=3, max_length=500)


class GtfsStagingInit(BaseModel):
    source_id: str = Field(min_length=4, max_length=100)
    file_name: str = Field(min_length=5, max_length=180)
    file_size: int = Field(gt=1024, le=2 * 1024 * 1024 * 1024)
    source_version: str = Field(default="", max_length=80)
    effective_date: str = Field(default="", max_length=10)
    sha256: str = Field(default="", pattern=r"^$|^[0-9a-fA-F]{64}$")


class GtfsStagingSignParts(BaseModel):
    job_id: str = Field(min_length=20, max_length=64)
    part_numbers: list[int] = Field(min_length=1, max_length=20)


class ShareRequest(BaseModel):
    plan: dict[str, Any]
    result: dict[str, Any] = Field(default_factory=dict)
    expires_days: int = Field(default=7, ge=1, le=30)
    max_views: int = Field(default=100, ge=1, le=500)


class FeedbackRequest(BaseModel):
    rating: int = Field(ge=1, le=5)
    good: str = Field(default="", max_length=2000)
    improve: str = Field(default="", max_length=4000)
    feature: str = Field(default="", max_length=2000)
    region: str = Field(default="", max_length=200)
    device: str = Field(default="", max_length=500)


class FeedbackUpdateRequest(BaseModel):
    status: Literal["received", "reviewing", "need_info", "in_progress", "completed"]
    admin_reply: str = Field(default="", max_length=4000)


class AdminSettingsPatch(BaseModel):
    values: dict[str, Any]
    reason: str = Field(min_length=3, max_length=500)


class ProviderProbeRequest(BaseModel):
    provider: Literal[
        "tago_bus", "tago_bus_city_codes", "tago_bus_stops", "tago_bus_stop_routes", "tago_bus_arrivals",
        "tago_rail", "tago_rail_stations", "tago_rail_timetable"
    ]
    province_code: str = Field(default="", max_length=5, pattern=r"^$|^[0-9]{2,5}$")
    district_code: str = Field(default="", max_length=5, pattern=r"^$|^[0-9]{2,5}$")
    operation_date: str = Field(default="", max_length=8, pattern=r"^$|^[0-9]{8}$")
    route_id: str = Field(default="", max_length=80)
    city_code: str = Field(default="", max_length=5, pattern=r"^$|^[0-9]{1,5}$")
    node_id: str = Field(default="", max_length=30)
    dep_station_id: str = Field(default="", max_length=80)
    arr_station_id: str = Field(default="", max_length=80)
    train_grade_code: str = Field(default="", max_length=10)


class GoogleLoginRequest(BaseModel):
    credential: str = Field(min_length=40, max_length=12000)


class ProjectCreateRequest(BaseModel):
    name: str = Field(min_length=2, max_length=80)
    description: str = Field(default="", max_length=500)


class ProjectUpdateRequest(BaseModel):
    name: str = Field(min_length=2, max_length=80)
    description: str = Field(default="", max_length=500)


class ProjectInviteRequest(BaseModel):
    email: str = Field(min_length=5, max_length=254, pattern=r"^[^\s@]+@[^\s@]+\.[^\s@]+$")
    role: Literal["editor", "viewer"] = "viewer"


class ProjectInvitePreviewRequest(BaseModel):
    # The raw one-time token is sent in a same-origin POST body, never in the
    # API URL where reverse-proxy/access logs could retain it.
    token: str = Field(min_length=32, max_length=160)


class ProjectInviteAcceptRequest(BaseModel):
    # New clients send the capability token in the POST body. Optional keeps
    # the old /{token}/accept endpoint compatible during the 1.9x migration.
    token: str | None = Field(default=None, min_length=32, max_length=160)
    # Possession of the one-time link delivered to the mailbox is the email
    # verification step. This flag only confirms which signed-in B-ROUTE
    # identity should receive membership when its profile email differs.
    confirm_current_account: bool = False


class ProjectRoleUpdateRequest(BaseModel):
    role: Literal["editor", "viewer"]


class ProjectRouteCreateRequest(BaseModel):
    title: str = Field(min_length=1, max_length=120)
    plan: dict[str, Any]
    result: dict[str, Any] = Field(default_factory=dict)


class ProjectRouteUpdateRequest(BaseModel):
    title: str = Field(min_length=1, max_length=120)
    plan: dict[str, Any]
    result: dict[str, Any] = Field(default_factory=dict)
    # Optimistic concurrency: every editor must submit the version they opened.
    expected_version: int = Field(ge=1)


class ProjectShareRequest(BaseModel):
    expires_days: int = Field(default=7, ge=1, le=30)
    max_views: int = Field(default=100, ge=1, le=500)


def _ensure_project_invite_columns(con) -> None:
    """Add transactional-email state to invitation rows from 1.92/1.93 databases."""
    if DB_IS_POSTGRES:
        rows = con.execute(
            "SELECT column_name FROM information_schema.columns WHERE table_name=?",
            ("project_invites",),
        ).fetchall()
        existing = {r[0] for r in rows}
    else:
        existing = {r[1] for r in con.execute("PRAGMA table_info(project_invites)").fetchall()}
    migrations = {
        "email_status": "TEXT NOT NULL DEFAULT 'legacy_link'",
        "email_message_id": "TEXT NOT NULL DEFAULT ''",
        "email_sent_at": "TEXT",
        "email_error_code": "TEXT NOT NULL DEFAULT ''",
        "send_attempts": "INTEGER NOT NULL DEFAULT 0",
        "current_email_event_id": "TEXT NOT NULL DEFAULT ''",
    }
    for column, definition in migrations.items():
        if column not in existing:
            con.execute(f"ALTER TABLE project_invites ADD COLUMN {column} {definition}")


def _ensure_invite_email_event_columns(con) -> None:
    """Add delivery-state columns to existing 1.94 email-event tables."""
    if DB_IS_POSTGRES:
        rows = con.execute("SELECT column_name FROM information_schema.columns WHERE table_name=?", ("project_invite_email_events",)).fetchall()
        existing = {r[0] for r in rows}
    else:
        existing = {r[1] for r in con.execute("PRAGMA table_info(project_invite_email_events)").fetchall()}
    migrations = {"last_event_type": "TEXT NOT NULL DEFAULT ''", "delivered_at": "TEXT", "bounced_at": "TEXT", "complained_at": "TEXT"}
    for column, definition in migrations.items():
        if column not in existing:
            con.execute(f"ALTER TABLE project_invite_email_events ADD COLUMN {column} {definition}")


def _b64url(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def _session_token(claims: dict[str, Any]) -> str:
    if not SESSION_SECRET or len(SESSION_SECRET) < 32:
        raise HTTPException(503, "로그인 세션 보안키(SESSION_SECRET)가 서버에 설정되지 않았습니다.")
    payload = _b64url(json.dumps(claims, separators=(",", ":"), ensure_ascii=False).encode("utf-8"))
    signature = hmac.new(SESSION_SECRET.encode("utf-8"), payload.encode("ascii"), hashlib.sha256).digest()
    return payload + "." + _b64url(signature)


def _read_session(request: Request) -> dict[str, Any] | None:
    token = request.cookies.get(SESSION_COOKIE, "")
    if not token or not SESSION_SECRET or "." not in token:
        return None
    payload, supplied_sig = token.rsplit(".", 1)
    expected_sig = _b64url(hmac.new(SESSION_SECRET.encode("utf-8"), payload.encode("ascii"), hashlib.sha256).digest())
    if not hmac.compare_digest(supplied_sig, expected_sig):
        return None
    try:
        raw = payload + "=" * (-len(payload) % 4)
        claims = json.loads(base64.urlsafe_b64decode(raw.encode("ascii")))
        if not isinstance(claims, dict) or int(claims.get("exp", 0)) <= int(time.time()):
            return None
        if not claims.get("sub"):
            return None
        return claims
    except Exception:
        return None


def _is_owner(claims: dict[str, Any] | None) -> bool:
    # The global owner identity is always a Google subject, never an email
    # string supplied by another identity provider.
    if not claims or claims.get("provider", "google") != "google":
        return False
    if GOOGLE_ADMIN_SUB:
        return hmac.compare_digest(str(claims.get("sub", "")), GOOGLE_ADMIN_SUB)
    return bool(GOOGLE_ADMIN_EMAIL and claims.get("email_verified") is True and
                str(claims.get("email", "")).lower() == GOOGLE_ADMIN_EMAIL)


def _require_same_origin(request: Request) -> None:
    origin = request.headers.get("origin", "").rstrip("/")
    if not origin:
        raise HTTPException(403, "요청 출처를 확인할 수 없습니다.")
    expected = APP_ORIGIN
    if not expected and os.getenv("APP_ENV", "").lower() == "production":
        raise HTTPException(503, "운영 환경의 APP_ORIGIN 설정이 필요합니다.")
    if not expected:
        host = request.headers.get("host", "")
        proto = request.headers.get("x-forwarded-proto", request.url.scheme).split(",")[0].strip()
        expected = f"{proto}://{host}".rstrip("/")
    if not host_origin_matches(origin, expected):
        raise HTTPException(403, "허용되지 않은 사이트에서 보낸 요청입니다.")


def host_origin_matches(origin: str, expected: str) -> bool:
    return hmac.compare_digest(origin.lower(), expected.lower())


def _cookie_secure(request: Request) -> bool:
    forwarded = request.headers.get("x-forwarded-proto", "").split(",")[0].strip().lower()
    return request.url.scheme == "https" or forwarded == "https" or os.getenv("APP_ENV", "").lower() == "production"


def _public_user(claims: dict[str, Any]) -> dict[str, Any]:
    return {"email": claims.get("email", ""), "name": claims.get("name", ""),
            "picture": claims.get("picture", ""), "provider": claims.get("provider", "google"),
            "email_verified": bool(claims.get("email_verified"))}


def _admin_session(request: Request) -> dict[str, Any]:
    claims = _read_session(request)
    if not claims:
        raise HTTPException(401, "로그인 후 총괄자 계정으로 접근해 주세요.")
    if not _is_owner(claims):
        raise HTTPException(403, "총괄자 계정만 접근할 수 있습니다.")
    return claims


def _admin_authorized(request: Request, supplied_token: str | None) -> bool:
    if ADMIN_TOKEN and supplied_token and hmac.compare_digest(supplied_token, ADMIN_TOKEN):
        return True
    claims = _read_session(request)
    if _is_owner(claims):
        _require_same_origin(request)
        return True
    return False

def _data_go_response_parts(payload: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
    response = payload.get("response", payload) if isinstance(payload, dict) else {}
    header = response.get("header", {}) if isinstance(response, dict) else {}
    body = response.get("body", {}) if isinstance(response, dict) else {}
    return (header if isinstance(header, dict) else {}, body if isinstance(body, dict) else {})


def parse_data_go_items(payload: dict[str, Any]) -> list[dict[str, Any]]:
    """Read data.go.kr JSON items whether item is a dict, list, or empty."""
    _header, body = _data_go_response_parts(payload)
    items = body.get("items", {}) if isinstance(body, dict) else {}
    if isinstance(items, list):
        rows = items
    elif isinstance(items, dict):
        rows = items.get("item", [])
    else:
        rows = []
    if isinstance(rows, dict):
        return [rows]
    if not isinstance(rows, list):
        return []
    return [row for row in rows if isinstance(row, dict)]


def _enforce_provider_rate_limit(request: Request) -> None:
    """Best-effort per-instance limit; also configure limits at the gateway/WAF."""
    host = request.client.host if request.client else "unknown"
    key = hashlib.sha256(f"tago:{host}".encode("utf-8")).hexdigest()[:24]
    now = time.monotonic()
    recent = [stamp for stamp in PROVIDER_RATE_STATE.get(key, []) if now - stamp < 60]
    if len(recent) >= PROVIDER_RATE_LIMIT_PER_MINUTE:
        retry_after = max(1, int(60 - (now - recent[0])))
        PROVIDER_RATE_STATE[key] = recent
        raise HTTPException(429, "교통정보 조회 요청이 너무 많습니다. 잠시 후 다시 시도해 주세요.",
                            headers={"Retry-After": str(retry_after)})
    recent.append(now)
    PROVIDER_RATE_STATE[key] = recent
    if len(PROVIDER_RATE_STATE) > 10000:
        for old_key, stamps in list(PROVIDER_RATE_STATE.items()):
            if not stamps or now - stamps[-1] >= 60:
                PROVIDER_RATE_STATE.pop(old_key, None)


def _provider_cache_key(provider: str, params: dict[str, Any]) -> str:
    canonical = json.dumps({"provider": provider, "params": params}, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _provider_cache_get(key: str) -> dict[str, Any] | None:
    item = PROVIDER_CACHE.get(key)
    if not item:
        return None
    expires, value = item
    if expires <= time.monotonic():
        PROVIDER_CACHE.pop(key, None)
        return None
    return value


def _provider_cache_put(key: str, value: dict[str, Any], ttl_seconds: int) -> None:
    if len(PROVIDER_CACHE) >= PROVIDER_CACHE_MAX:
        now = time.monotonic()
        for old_key, (expires, _value) in list(PROVIDER_CACHE.items()):
            if expires <= now:
                PROVIDER_CACHE.pop(old_key, None)
        while len(PROVIDER_CACHE) >= PROVIDER_CACHE_MAX:
            PROVIDER_CACHE.pop(next(iter(PROVIDER_CACHE)))
    PROVIDER_CACHE[key] = (time.monotonic() + max(1, ttl_seconds), value)


async def data_go_request(service: str, operation: str, params: dict[str, Any], *,
                          format_parameter: str = "_type", format_value: str = "json",
                          include_paging: bool = True) -> dict[str, Any]:
    """Call an approved data.go.kr endpoint without exposing server credentials.

    Supply the *decoded* service key in DATA_GO_KR_SERVICE_KEY; httpx encodes
    query parameters exactly once. Some operations (e.g. TrainInfo city codes)
    do not document pageNo/numOfRows, so paging can be omitted explicitly.
    """
    if not DATA_GO_KEY:
        raise HTTPException(503, "공공데이터포털 인증키가 서버에 설정되지 않았습니다. 관리자 서버 Secret을 확인해 주세요.")
    if not re.fullmatch(r"[A-Za-z0-9_]{2,80}", service) or not re.fullmatch(r"[A-Za-z0-9_]{2,100}", operation):
        raise HTTPException(400, "허용되지 않은 교통 API 경로입니다.")
    url = f"https://apis.data.go.kr/1613000/{service}/{operation}"
    query = {"serviceKey": DATA_GO_KEY, format_parameter: format_value}
    if include_paging:
        query.update({"pageNo": 1, "numOfRows": 100})
    query.update(params)
    timeout_seconds = max(5, min(30, int(os.getenv("DATA_GO_REQUEST_TIMEOUT_SECONDS", "15"))))
    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(timeout_seconds, connect=5.0),
                                     follow_redirects=False,
                                     headers={"User-Agent": "B-ROUTE/1.94 collaboration"}) as client:
            response = await client.get(url, params=query)
            if response.status_code == 429:
                raise HTTPException(429, "교통정보 공급원의 호출 한도를 초과했습니다. 잠시 후 다시 시도해 주세요.")
            if response.status_code in (401, 403):
                raise HTTPException(503, "공공데이터포털 서비스 활용 신청 또는 인증키 권한을 확인해 주세요.")
            if response.status_code >= 500:
                raise HTTPException(502, f"교통정보 공급원 서버 오류 ({response.status_code})")
            if response.status_code >= 400:
                raise HTTPException(502, f"교통정보 공급원 HTTP 오류 ({response.status_code})")
            data = response.json()
    except HTTPException:
        raise
    except httpx.TimeoutException as exc:
        raise HTTPException(504, "교통정보 공급원 응답 시간이 초과되었습니다.") from exc
    except (httpx.RequestError, ValueError) as exc:
        raise HTTPException(502, "교통정보 공급원에 연결하지 못했거나 JSON 응답을 읽지 못했습니다.") from exc

    header, _body = _data_go_response_parts(data)
    code = str(header.get("resultCode", "00")).strip()
    # data.go.kr common response code 03 means a successful request with no rows.
    if code in ("00", "0", "0000", "03", "NODATA_ERROR"):
        return data
    raw_msg = str(header.get("resultMsg", "공급원 응답 오류"))[:160]
    from urllib.parse import quote, quote_plus, unquote, unquote_plus
    msg = raw_msg
    for secret_variant in {DATA_GO_KEY, quote(DATA_GO_KEY, safe=""), quote_plus(DATA_GO_KEY),
                           unquote(DATA_GO_KEY), unquote_plus(DATA_GO_KEY)}:
        if secret_variant:
            msg = msg.replace(secret_variant, "[REDACTED]")
    if code in ("22", "23", "LIMITED_NUMBER_OF_SERVICE_REQUESTS_EXCEEDS_ERROR", "LIMITED_NUMBER_OF_SERVICE_REQUESTS_PER_SECOND_EXCEEDS_ERROR"):
        raise HTTPException(429, "교통정보 공급원의 호출 한도를 초과했습니다.")
    if code in ("05", "SERVICETIMEOUT_ERROR"):
        raise HTTPException(504, "교통정보 공급원 응답 시간이 초과되었습니다.")
    if code in ("12", "20", "21", "29", "30", "31", "32", "33",
                "NO_OPENAPI_SERVICE_ERROR", "SERVICE_ACCESS_DENIED_ERROR",
                "TEMPORARILY_DISABLE_THE_SERVICEKEY_ERROR", "SERVICE_KEY_IS_NOT_REGISTERED_ERROR",
                "DEADLINE_HAS_EXPIRED_ERROR", "UNREGISTERED_IP_ERROR", "UNSIGNED_CALL_ERROR"):
        raise HTTPException(503, f"공공데이터포털 서비스 신청·인증키·접속 IP 권한을 확인해 주세요. ({code})")
    raise HTTPException(502, f"교통정보 공급원 오류 ({code}): {msg}")


async def data_go_get(service: str, operation: str, params: dict[str, Any]) -> dict[str, Any]:
    return await data_go_request(service, operation, params)


def _pick_provider_value(row: dict[str, Any], *keys: str) -> Any:
    for key in keys:
        value = row.get(key)
        if value not in (None, ""):
            return value
    lowered = {str(k).lower(): v for k, v in row.items()}
    for key in keys:
        value = lowered.get(key.lower())
        if value not in (None, ""):
            return value
    return None


def _parse_provider_datetime(value: Any) -> datetime | None:
    raw = str(value or "").strip()
    for fmt in ("%Y%m%d%H%M%S", "%Y%m%d%H%M", "%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M:%S"):
        try:
            return datetime.strptime(raw, fmt).replace(tzinfo=TZ)
        except ValueError:
            continue
    return None


def normalize_tago_city(row: dict[str, Any]) -> dict[str, Any] | None:
    code = _pick_provider_value(row, "citycode", "cityCode", "city_code")
    name = _pick_provider_value(row, "cityname", "cityName", "city_name")
    if code in (None, "") or name in (None, ""):
        return None
    return {"id": str(code), "name": str(name), "mode": "rail"}


def normalize_tago_station(row: dict[str, Any]) -> dict[str, Any] | None:
    station_id = _pick_provider_value(row, "nodeid", "nodeId", "stationId", "station_id", "railOprIsttCd")
    name = _pick_provider_value(row, "nodename", "nodeName", "stationName", "station_name", "railOprIsttNm")
    if station_id in (None, "") or name in (None, ""):
        return None
    return {"id": str(station_id), "name": str(name),
            "city_code": str(_pick_provider_value(row, "citycode", "cityCode") or ""),
            "latitude": _safe_float(_pick_provider_value(row, "gpslati", "gpsLati", "lat")),
            "longitude": _safe_float(_pick_provider_value(row, "gpslong", "gpsLong", "lon")),
            "mode": "rail", "source": "TAGO"}


def _safe_float(value: Any) -> float | None:
    try:
        result = float(value)
        return result if math.isfinite(result) else None
    except (TypeError, ValueError):
        return None


def normalize_tago_train(row: dict[str, Any]) -> dict[str, Any] | None:
    dep_raw = _pick_provider_value(row, "depplandtime", "depPlanTime", "departureTime")
    arr_raw = _pick_provider_value(row, "arrplandtime", "arrPlanTime", "arrivalTime")
    dep_dt, arr_dt = _parse_provider_datetime(dep_raw), _parse_provider_datetime(arr_raw)
    if not dep_dt or not arr_dt:
        return None
    duration = int(round((arr_dt - dep_dt).total_seconds() / 60))
    if duration <= 0:
        return None
    return {"id": str(_pick_provider_value(row, "trainid", "trainId", "trainno", "trainNo") or ""),
            "train_number": str(_pick_provider_value(row, "trainno", "trainNo") or ""),
            "train_type": str(_pick_provider_value(row, "traingradename", "trainGradeName", "train_grade_name") or "열차"),
            "departure_station": str(_pick_provider_value(row, "depplacename", "depPlaceName") or ""),
            "arrival_station": str(_pick_provider_value(row, "arrplacename", "arrPlaceName") or ""),
            "departure_at": dep_dt.isoformat(), "arrival_at": arr_dt.isoformat(),
            "duration_minutes": max(0, duration),
            "adult_fare_krw": _safe_int(_pick_provider_value(row, "adultcharge", "adultCharge")),
            "mode": "rail", "source": "국토교통부 TAGO 열차정보"}


def _safe_int(value: Any) -> int | None:
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return None


def normalize_tago_bus_route(row: dict[str, Any]) -> dict[str, Any] | None:
    route_id = _pick_provider_value(row, "rte_id", "rteId", "routeid", "routeId", "route_id")
    route_no = _pick_provider_value(row, "rte_no", "rteNo", "routeno", "routeNo", "route_no", "rte_nm", "rteNm")
    if route_id in (None, "") and route_no in (None, ""):
        return None
    return {"id": str(route_id or route_no), "route_number": str(route_no or route_id),
            "name": str(_pick_provider_value(row, "rte_nm", "rteNm", "routeName", "route_name") or route_no or route_id),
            "origin": str(_pick_provider_value(row, "start_node_nm", "startNodeNm", "sttn_nm", "start_station") or ""),
            "destination": str(_pick_provider_value(row, "end_node_nm", "endNodeNm", "end_station") or ""),
            "province_code": str(_pick_provider_value(row, "ctpv_cd", "ctpvCd", "ctpv_code") or ""),
            "mode": "bus", "source": "국토교통부 버스노선 API"}


def normalize_tago_bus_stop(row: dict[str, Any]) -> dict[str, Any] | None:
    stop_id = _pick_provider_value(row, "node_id", "nodeId", "nodeid", "sttn_id", "sttnId", "stop_id")
    stop_name = _pick_provider_value(row, "node_nm", "nodeNm", "nodenm", "sttn_nm", "sttnNm", "stop_name")
    seq = _safe_int(_pick_provider_value(row, "node_ord", "nodeOrd", "node_seq", "nodeSeq", "sttn_seq", "sttnSeq"))
    if stop_id in (None, "") and stop_name in (None, ""):
        return None
    return {
        "stop_id": str(stop_id or ""), "stop_name": str(stop_name or "정류장"),
        "sequence": seq,
        "route_id": str(_pick_provider_value(row, "rte_id", "rteId", "routeid", "routeId") or ""),
        "route_number": str(_pick_provider_value(row, "rte_no", "rteNo", "routeno", "routeNo") or ""),
        "province_code": str(_pick_provider_value(row, "ctpv_cd", "ctpvCd") or ""),
        "district_code": str(_pick_provider_value(row, "sgg_cd", "sggCd") or ""),
        "latitude": _safe_float(_pick_provider_value(row, "gps_lati", "gpsLati", "gpslati", "lat")),
        "longitude": _safe_float(_pick_provider_value(row, "gps_long", "gpsLong", "gpslong", "lon")),
        "mode": "bus", "source": "국토교통부 버스노선별 경유정류장"
    }


def normalize_tago_stop_route(row: dict[str, Any]) -> dict[str, Any] | None:
    """Normalize TAGO BusSttnInfoInqireService getSttnThrghRouteList rows."""
    route_id = _pick_provider_value(row, "routeid", "routeId", "route_id")
    route_no = _pick_provider_value(row, "routeno", "routeNo", "route_no")
    if route_id in (None, "") and route_no in (None, ""):
        return None
    return {
        "id": str(route_id or route_no),
        "route_number": str(route_no or route_id),
        "route_type": str(_pick_provider_value(row, "routetp", "routeTp", "route_type") or ""),
        "origin": str(_pick_provider_value(row, "startnodenm", "startNodeNm", "origin") or ""),
        "destination": str(_pick_provider_value(row, "endnodenm", "endNodeNm", "destination") or ""),
        "mode": "bus", "source": "국토교통부 TAGO 정류소별 경유노선"
    }


def normalize_tago_arrival(row: dict[str, Any]) -> dict[str, Any] | None:
    route_no = _pick_provider_value(row, "routeno", "routeNo", "routeid", "routeId")
    seconds = _safe_int(_pick_provider_value(row, "arrtime", "arrTime"))
    if route_no in (None, "") and seconds is None:
        return None
    return {"route": str(route_no or "버스"), "arrival_seconds": seconds,
            "arrival_minutes": None if seconds is None else max(0, int(round(seconds / 60))),
            "remaining_stops": _safe_int(_pick_provider_value(row, "arrprevstationcnt", "arrPrevStationCnt")),
            "vehicle_type": str(_pick_provider_value(row, "vehicletp", "vehicleTp") or ""),
            "stop_name": str(_pick_provider_value(row, "nodenm", "nodeNm") or ""),
            "mode": "bus", "source": "TAGO 실시간 도착정보"}


def normalize_photon_feature(feature: dict[str, Any]) -> dict[str, Any] | None:
    coords = (feature.get("geometry") or {}).get("coordinates") or []
    if len(coords) < 2:
        return None
    p = feature.get("properties") or {}
    name = p.get("name") or p.get("street") or p.get("city") or "검색 위치"
    address_parts = [p.get("postcode"), p.get("state"), p.get("city"), p.get("district"), p.get("street"), p.get("housenumber")]
    address = " ".join(str(x) for x in address_parts if x)
    return {"id": f"photon:{p.get('osm_type','')}:{p.get('osm_id','')}:{coords[0]}:{coords[1]}", "name": name,
            "address": address or p.get("country", ""), "lat": float(coords[1]), "lon": float(coords[0]),
            "kind": p.get("type", "place"), "source": "OpenStreetMap/Photon"}


def _beta_readiness_checks(*, durable: bool, cos_ready: bool,
                            data_ready: bool, worker_alive: bool) -> dict[str, bool]:
    """Use one readiness definition for the public health endpoint and admin UI."""
    return {
        "app_origin_configured": bool(APP_ORIGIN),
        "google_signin": bool(GOOGLE_CLIENT_ID and len(SESSION_SECRET) >= 32),
        "naver_signin": bool(NAVER_CLIENT_ID and NAVER_CLIENT_SECRET),
        "microsoft_signin": bool(MICROSOFT_CLIENT_ID and MICROSOFT_CLIENT_SECRET),
        "data_go_kr_api": bool(DATA_GO_KEY),
        "project_invite_email": invite_email_configured(),
        "resend_webhook": resend_webhook_secret_configured(),
        "durable_database": bool(durable),
        "cloud_object_storage": bool(cos_ready),
        "gtfs_dataset_registered": bool(data_ready),
        "gtfs_worker": bool(worker_alive),
        "release_gate_approved": bool(BETA_RELEASE_APPROVED),
    }


@app.get("/health")
async def health() -> dict[str, Any]:
    with closing(db()) as con:
        feeds = [dict(r) for r in con.execute("SELECT feed_id,name,agency,imported_at,stop_count,route_count,trip_count,source_id,source_version,effective_date,license_name,sha256,is_active FROM feeds WHERE is_active=1 ORDER BY imported_at DESC")]
        worker_row = con.execute("SELECT status,last_seen FROM gtfs_worker_heartbeats ORDER BY last_seen DESC LIMIT 1").fetchone()
        con.execute("SELECT 1").fetchone()
    durable = durable_database_ready()
    cos_ready = cos_is_configured()
    google_ready = bool(GOOGLE_CLIENT_ID and len(SESSION_SECRET) >= 32)
    data_ready = bool(feeds)
    worker_alive = False
    if worker_row:
        try:
            worker_alive = (datetime.now(TZ) - datetime.fromisoformat(str(worker_row[1]))).total_seconds() <= int(os.getenv("GTFS_WORKER_HEARTBEAT_TTL_SECONDS", "120")) and worker_row[0] != "stopped"
        except Exception:
            worker_alive = False
    beta_checks = _beta_readiness_checks(durable=durable, cos_ready=cos_ready,
                                         data_ready=data_ready, worker_alive=worker_alive)
    return {"ok": True, "app": "B-ROUTE", "version": APP_VERSION, "environment": APP_ENV,
        "readiness": {"beta_ready": all(beta_checks.values()), "checks": beta_checks},
        "storage": {"database_backend": "postgresql" if DB_IS_POSTGRES else "sqlite_local",
                    "durable_database_ready": durable, "cos_configured": cos_ready},
        "features": {"place_search": True, "gps": True, "map_pick": True, "tago": bool(DATA_GO_KEY),
            "kakao_places": bool(KAKAO_REST_KEY), "google_signin": google_ready, "naver_signin": bool(NAVER_CLIENT_ID and NAVER_CLIENT_SECRET),
            "microsoft_signin": bool(MICROSOFT_CLIENT_ID and MICROSOFT_CLIENT_SECRET),
            "project_invite_email": invite_email_configured(),
            "cloud_storage": bool(durable and cos_ready), "server_feedback": durable,
            "gtfs_routing": data_ready, "gtfs_large_file_staging": bool(durable and cos_ready),
            "gtfs_import_worker": worker_alive}, "gtfs_feeds": feeds}


def _hash_capability(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def invite_email_configured() -> bool:
    return bool(RESEND_API_KEY and re.fullmatch(r"[^\s@<>]+@[^\s@<>]+\.[^\s@<>]+", INVITE_FROM_EMAIL))


def resend_webhook_secret_configured() -> bool:
    """Return true only when the configured Svix secret has valid base64 data."""
    if not RESEND_WEBHOOK_SECRET.startswith("whsec_"):
        return False
    try:
        return bool(base64.b64decode(RESEND_WEBHOOK_SECRET[len("whsec_"):], validate=True))
    except (ValueError, base64.binascii.Error):
        return False


def _normalise_email(value: Any) -> str:
    return str(value or "").strip().casefold()


def _invite_email_content(project_name: str, role: str, invite_url: str, expires_at: str) -> tuple[str, str, str]:
    # Remove control characters before using user-created project names in
    # mail headers or plain-text content. HTML values are escaped separately.
    clean_project = " ".join(str(project_name).replace("\r", " ").replace("\n", " ").split())[:120]
    safe_project = html_lib.escape(clean_project)
    safe_role = "편집 권한" if role == "editor" else "보기 전용 권한"
    safe_url = html_lib.escape(invite_url, quote=True)
    safe_expiry = html_lib.escape(datetime.fromisoformat(expires_at).astimezone(TZ).strftime("%Y년 %m월 %d일 %H:%M"))
    subject = f"[B-ROUTE] {clean_project} 프로젝트에 초대되었습니다"
    html_body = f'''<!doctype html>
<html lang="ko"><head><meta charset="utf-8"></head>
<body style="margin:0;padding:28px 12px;background:#f3f6fa;font-family:Arial,'Noto Sans KR',sans-serif;color:#203047">
<table role="presentation" cellpadding="0" cellspacing="0" width="100%"><tr><td align="center">
<table role="presentation" cellpadding="0" cellspacing="0" width="100%" style="max-width:560px;background:#fff;border:1px solid #e2e8f0;border-radius:16px;overflow:hidden">
<tr><td style="padding:24px 28px;background:#12243b;color:#fff;font-size:20px;font-weight:700">B-ROUTE</td></tr>
<tr><td style="padding:28px">
<p style="margin:0 0 12px;color:#627187;font-size:13px">프로젝트 초대</p>
<h1 style="font-size:22px;line-height:1.45;margin:0 0 14px">프로젝트에 초대되었습니다.</h1>
<p style="font-size:15px;line-height:1.8;margin:0 0 8px"><strong>{safe_project}</strong></p>
<p style="font-size:14px;line-height:1.8;color:#53647a;margin:0 0 22px">부여 권한: {safe_role}<br>초대 만료: {safe_expiry} (한국 시간)</p>
<table role="presentation" cellpadding="0" cellspacing="0"><tr><td bgcolor="#2878e5" style="border-radius:9px">
<a href="{safe_url}" style="display:inline-block;padding:14px 24px;color:#fff;text-decoration:none;font-weight:700;font-size:15px">프로젝트 참가하기</a>
</td></tr></table>
<p style="font-size:12px;line-height:1.7;color:#718096;margin:22px 0 0">버튼을 누르면 B-ROUTE로 이동합니다. Google·네이버·Microsoft 중 사용할 계정으로 로그인한 뒤 사이트 안에서 프로젝트 참가하기를 한 번 더 눌러야 참여가 완료됩니다. 현재 로그인 계정의 이메일이 초대 주소와 다르면 해당 계정에 권한을 부여할지 추가 확인합니다.</p>
<p style="font-size:12px;line-height:1.7;color:#718096;margin:12px 0 0">본인이 요청하지 않은 초대라면 이 메일을 무시하셔도 됩니다. 링크는 한 번만 사용할 수 있으며, 만료 전에도 프로젝트 소유자가 취소할 수 있습니다.</p>
<p style="font-size:12px;line-height:1.7;color:#718096;margin:12px 0 0">문의: <a href="mailto:broute.site.app@gmail.com">broute.site.app@gmail.com</a></p>
</td></tr></table></td></tr></table>
</body></html>'''
    text_body = (
        f"B-ROUTE 프로젝트 초대\n\n{clean_project} 프로젝트에 초대되었습니다.\n"
        f"권한: {safe_role}\n만료: {safe_expiry} (한국 시간)\n\n"
        f"프로젝트 참가하기: {invite_url}\n\n"
        "메일의 프로젝트 참가하기 버튼을 열고 Google·네이버·Microsoft 중 원하는 B-ROUTE 계정으로 로그인해 주세요.\n"
        "메일 버튼을 연 뒤 사이트 안에서 참가를 한 번 더 확인해야 권한이 부여됩니다.\n"
        "로그인 계정의 이메일이 초대 주소와 다르면 현재 로그인 계정에 권한을 부여할지 한 번 더 확인합니다.\n"
        "요청하지 않은 초대라면 이 메일을 무시하셔도 됩니다.\n"
        "문의: broute.site.app@gmail.com"
    )
    return subject, html_body, text_body


async def _send_project_invite_email(*, recipient: str, project_name: str, role: str,
                                     invite_url: str, expires_at: str, idempotency_key: str) -> str:
    """Send one transactional project invitation through Resend.

    The token appears only in the delivered message. It is never returned by
    the invite-creation API or written to application logs.
    """
    if not invite_email_configured():
        raise RuntimeError("email_not_configured")
    subject, html_body, text_body = _invite_email_content(project_name, role, invite_url, expires_at)
    safe_sender_name = re.sub(r"[\x00-\x1f\x7f<>\"]", "", INVITE_FROM_NAME).strip()[:80] or "B-ROUTE"
    from_value = f"{safe_sender_name} <{INVITE_FROM_EMAIL}>"
    headers = {"Authorization": f"Bearer {RESEND_API_KEY}", "Content-Type": "application/json",
               "Idempotency-Key": idempotency_key[:256]}
    payload = {"from": from_value, "to": [recipient], "subject": subject,
               "html": html_body, "text": text_body}
    if INVITE_REPLY_TO_EMAIL and re.fullmatch(r"[^\s@<>]+@[^\s@<>]+\.[^\s@<>]+", INVITE_REPLY_TO_EMAIL):
        payload["reply_to"] = INVITE_REPLY_TO_EMAIL
    try:
        transport = RESEND_HTTP_TRANSPORT() if callable(RESEND_HTTP_TRANSPORT) else RESEND_HTTP_TRANSPORT
        async with httpx.AsyncClient(timeout=httpx.Timeout(15.0), transport=transport) as client:
            response = await client.post("https://api.resend.com/emails", headers=headers, json=payload)
        if response.status_code >= 400:
            # Provider response bodies may include recipient and operational
            # details. Persist only a bounded synthetic code, never raw text.
            raise RuntimeError(f"resend_http_{response.status_code}")
        data = response.json()
        message_id = str(data.get("id", "")) if isinstance(data, dict) else ""
        if not message_id:
            raise RuntimeError("resend_invalid_response")
        return message_id
    except httpx.TimeoutException as exc:
        raise RuntimeError("resend_timeout") from exc
    except httpx.HTTPError as exc:
        raise RuntimeError("resend_network_error") from exc
    except (ValueError, TypeError) as exc:
        raise RuntimeError("resend_invalid_response") from exc


def _lock_invite_email_quota(con) -> None:
    """Serialize daily email-cap checks across production PostgreSQL workers."""
    if DB_IS_POSTGRES:
        con.execute("SELECT pg_advisory_xact_lock(1942519401)").fetchone()
    else:
        con.execute("UPDATE app_settings SET updated_at=updated_at WHERE setting_key='cloud_quota_mb'")


def _invite_email_quota_count(con, now: datetime) -> int:
    day_start = now.replace(hour=0, minute=0, second=0, microsecond=0).isoformat()
    row = con.execute("SELECT COUNT(*) FROM project_invite_email_events WHERE created_at>=?",
                      (day_start,)).fetchone()
    return int(row[0]) if row else 0


def _email_delivery_priority(status: str) -> int:
    return {"sending":0,"failed":5,"accepted":1,"sent":2,"delivery_delayed":3,
            "delivered":4,"bounced":6,"complained":7,"suppressed":8,"legacy_link":1}.get(status,0)


def _record_invite_email_result(event_id: str, invite_id: str, *, status: str,
                                 now: str, message_id: str = "", error_code: str = "") -> None:
    with closing(db()) as con:
        event_row = con.execute("SELECT status FROM project_invite_email_events WHERE event_id=?", (event_id,)).fetchone()
        if event_row and _email_delivery_priority(status) >= _email_delivery_priority(str(event_row[0])):
            con.execute("UPDATE project_invite_email_events SET status=?,provider_message_id=CASE WHEN ?<>'' THEN ? ELSE provider_message_id END,error_code=? WHERE event_id=?",
                        (status, message_id, message_id, error_code, event_id))
        # A webhook may arrive before the sending request finishes. Do not let
        # the later API response regress delivered/bounced/complained states.
        current = con.execute("SELECT email_status,current_email_event_id FROM project_invites WHERE invite_id=?", (invite_id,)).fetchone()
        if current and str(current[1]) == event_id and _email_delivery_priority(status) >= _email_delivery_priority(str(current[0])):
            con.execute("UPDATE project_invites SET email_status=?,email_message_id=CASE WHEN ?<>'' THEN ? ELSE email_message_id END,email_sent_at=CASE WHEN ?='accepted' THEN ? ELSE email_sent_at END,email_error_code=? WHERE invite_id=? AND current_email_event_id=?",
                        (status,message_id,message_id,status,now,error_code,invite_id,event_id))
        # A provider webhook can race the email API response. It is first stored
        # as an unmatched event; reconcile it now that the provider message ID is known.
        if message_id:
            pending = con.execute("SELECT event_id,event_type,received_at FROM provider_webhook_events WHERE provider='resend' AND provider_message_id=? ORDER BY received_at", (message_id,)).fetchall()
            status_map = {"email.sent":"sent","email.delivered":"delivered","email.delivery_delayed":"delivery_delayed","email.bounced":"bounced","email.complained":"complained","email.failed":"failed","email.suppressed":"suppressed"}
            for webhook_id, webhook_type, webhook_at in pending:
                webhook_status = status_map.get(str(webhook_type), "")
                if not webhook_status:
                    continue
                current_event = con.execute("SELECT status FROM project_invite_email_events WHERE event_id=?", (event_id,)).fetchone()
                if current_event and _email_delivery_priority(webhook_status) >= _email_delivery_priority(str(current_event[0])):
                    con.execute("UPDATE project_invite_email_events SET status=?,last_event_type=?,delivered_at=CASE WHEN ?='email.delivered' THEN ? ELSE delivered_at END,bounced_at=CASE WHEN ?='email.bounced' THEN ? ELSE bounced_at END,complained_at=CASE WHEN ?='email.complained' THEN ? ELSE complained_at END WHERE event_id=?", (webhook_status,str(webhook_type),str(webhook_type),str(webhook_at),str(webhook_type),str(webhook_at),str(webhook_type),str(webhook_at),event_id))
                    current_invite = con.execute("SELECT email_status,current_email_event_id FROM project_invites WHERE invite_id=?", (invite_id,)).fetchone()
                    if current_invite and str(current_invite[1]) == event_id and _email_delivery_priority(webhook_status) >= _email_delivery_priority(str(current_invite[0])):
                        con.execute("UPDATE project_invites SET email_status=?,email_error_code=CASE WHEN ? IN ('bounced','complained','failed','suppressed') THEN ? ELSE email_error_code END WHERE invite_id=? AND current_email_event_id=?", (webhook_status,webhook_status,webhook_status,invite_id,event_id))
        con.commit()


def _verify_resend_webhook(raw_body: bytes, headers: dict[str, str], *, now: int | None = None) -> str:
    """Verify Svix-compatible Resend webhook signatures and return the event id."""
    if not resend_webhook_secret_configured():
        raise HTTPException(503, "Resend 웹훅 서명키가 설정되지 않았거나 형식이 올바르지 않습니다.")
    event_id, timestamp, supplied = headers.get("svix-id", ""), headers.get("svix-timestamp", ""), headers.get("svix-signature", "")
    if not event_id or not timestamp or not supplied or len(event_id) > 200:
        raise HTTPException(400, "웹훅 서명 헤더가 누락되었습니다.")
    try: ts = int(timestamp)
    except (TypeError, ValueError): raise HTTPException(400, "웹훅 타임스탬프가 올바르지 않습니다.")
    current = int(time.time()) if now is None else int(now)
    if abs(current-ts) > RESEND_WEBHOOK_TOLERANCE_SECONDS:
        raise HTTPException(400, "웹훅 서명 시간이 허용 범위를 벗어났습니다.")
    try: secret = base64.b64decode(RESEND_WEBHOOK_SECRET[len("whsec_"):], validate=True)
    except Exception: raise HTTPException(503, "Resend 웹훅 서명키 형식이 올바르지 않습니다.")
    signed = event_id.encode()+b"."+timestamp.encode()+b"."+raw_body
    expected = base64.b64encode(hmac.new(secret, signed, hashlib.sha256).digest()).decode()
    valid = any(version == "v1" and hmac.compare_digest(signature, expected)
                for item in supplied.split() if "," in item for version, signature in [item.split(",",1)])
    if not valid: raise HTTPException(401, "웹훅 서명이 일치하지 않습니다.")
    return event_id


def _apply_resend_delivery_event(event_id: str, event_type: str, message_id: str, received_at: str, payload_sha256: str) -> dict[str, Any]:
    """Idempotently apply delivery events; stale/duplicate events cannot regress state."""
    status_map = {"email.sent":"sent", "email.delivered":"delivered", "email.delivery_delayed":"delivery_delayed", "email.bounced":"bounced", "email.complained":"complained", "email.failed":"failed", "email.suppressed":"suppressed"}
    status = status_map.get(event_type)
    if not status or not message_id: return {"processed":False,"reason":"unsupported_event"}
    with closing(db()) as con:
        inserted = con.execute("INSERT INTO provider_webhook_events(event_id,provider,event_type,provider_message_id,received_at,payload_sha256) VALUES(?,?,?,?,?,?) ON CONFLICT(event_id) DO NOTHING", (event_id,"resend",event_type,message_id,received_at,payload_sha256))
        if getattr(inserted, "rowcount", 1) == 0:
            con.commit()
            return {"processed":True,"duplicate":True}
        event=con.execute("SELECT event_id,invite_id FROM project_invite_email_events WHERE provider_message_id=?",(message_id,)).fetchone()
        if not event:
            con.commit(); return {"processed":True,"matched":False}
        email_event_id,invite_id=str(event[0]),str(event[1])
        event_state=con.execute("SELECT status FROM project_invite_email_events WHERE event_id=?",(email_event_id,)).fetchone()
        if event_state and _email_delivery_priority(status) >= _email_delivery_priority(str(event_state[0])):
            con.execute("UPDATE project_invite_email_events SET status=?,last_event_type=?,delivered_at=CASE WHEN ?='email.delivered' THEN ? ELSE delivered_at END,bounced_at=CASE WHEN ?='email.bounced' THEN ? ELSE bounced_at END,complained_at=CASE WHEN ?='email.complained' THEN ? ELSE complained_at END WHERE event_id=?",(status,event_type,event_type,received_at,event_type,received_at,event_type,received_at,email_event_id))
        current=con.execute("SELECT email_status,current_email_event_id FROM project_invites WHERE invite_id=?",(invite_id,)).fetchone()
        if current and str(current[1])==email_event_id:
            if _email_delivery_priority(status)>=_email_delivery_priority(str(current[0])):
                con.execute("UPDATE project_invites SET email_status=?,email_error_code=CASE WHEN ? IN ('bounced','complained','failed','suppressed') THEN ? ELSE email_error_code END WHERE invite_id=? AND current_email_event_id=?",(status,status,status,invite_id,email_event_id))
        con.commit()
    return {"processed":True,"matched":True,"status":status}


@app.post("/webhooks/resend")
async def resend_webhook(request: Request):
    """Public Resend webhook endpoint. Signature verification is mandatory."""
    raw_body=await request.body()
    if len(raw_body)>256*1024: raise HTTPException(413,"웹훅 본문이 너무 큽니다.")
    event_id=_verify_resend_webhook(raw_body,dict(request.headers))
    try: payload=json.loads(raw_body.decode("utf-8"))
    except (UnicodeDecodeError,ValueError): raise HTTPException(400,"웹훅 JSON 형식이 올바르지 않습니다.")
    if not isinstance(payload,dict): raise HTTPException(400,"웹훅 데이터 형식이 올바르지 않습니다.")
    data=payload.get("data") if isinstance(payload.get("data"),dict) else {}
    message_id=str(data.get("email_id") or data.get("id") or "")[:200]
    event_type=str(payload.get("type") or "")[:100]
    result=_apply_resend_delivery_event(event_id,event_type,message_id,datetime.now(TZ).isoformat(),hashlib.sha256(raw_body).hexdigest())
    return {"ok":True,**result}


def _effective_origin(request: Request) -> str:
    if APP_ORIGIN:
        return APP_ORIGIN
    host = request.headers.get("host", "localhost")
    proto = request.headers.get("x-forwarded-proto", request.url.scheme).split(",")[0].strip()
    return f"{proto}://{host}".rstrip("/")


def _oauth_success_url(request: Request, return_to: str) -> str:
    safe_return = return_to if return_to.startswith("/") and not return_to.startswith("//") and "\\" not in return_to and "\r" not in return_to and "\n" not in return_to else "/"
    # OAuth providers redirect through the server, so preserve a browser-only
    # invite fragment while placing auth status in the real query string.
    path_query, marker, fragment = safe_return.partition("#")
    separator = "&" if "?" in path_query else "?"
    return _effective_origin(request) + path_query + separator + "auth=success" + ("#" + fragment if marker else "")


def _signed_cookie_claims(token: str, purpose: str) -> dict[str, Any] | None:
    if not token or not SESSION_SECRET or len(SESSION_SECRET) < 32 or "." not in token:
        return None
    payload, supplied_sig = token.rsplit(".", 1)
    expected_sig = _b64url(hmac.new(SESSION_SECRET.encode("utf-8"), payload.encode("ascii"), hashlib.sha256).digest())
    if not hmac.compare_digest(supplied_sig, expected_sig):
        return None
    try:
        raw = payload + "=" * (-len(payload) % 4)
        claims = json.loads(base64.urlsafe_b64decode(raw.encode("ascii")))
        if not isinstance(claims, dict) or claims.get("purpose") != purpose or int(claims.get("exp", 0)) <= int(time.time()):
            return None
        return claims
    except Exception:
        return None


def _oauth_state_cookie(provider: str, state: str, nonce: str, verifier: str, return_to: str = "/") -> str:
    now = int(time.time())
    safe_return = return_to if return_to.startswith("/") and not return_to.startswith("//") and "\\" not in return_to and "\r" not in return_to and "\n" not in return_to else "/"
    return _session_token({"purpose": "oauth_state", "provider": provider, "state": state,
                           "nonce": nonce, "verifier": verifier, "return_to": safe_return,
                           "iat": now, "exp": now + 600})


def _consume_oauth_state(request: Request, provider: str, state: str | None) -> dict[str, Any]:
    claims = _signed_cookie_claims(request.cookies.get(OAUTH_STATE_COOKIE, ""), "oauth_state")
    if not claims or claims.get("provider") != provider or not state or not hmac.compare_digest(str(claims.get("state", "")), state):
        raise HTTPException(400, "로그인 상태 검증에 실패했습니다. 처음부터 다시 시도해 주세요.")
    return claims


def _provider_user_session(provider: str, provider_subject: str, email: str, name: str,
                           email_verified: bool = False, picture: str = "") -> dict[str, Any]:
    if not provider_subject:
        raise HTTPException(401, "인증 공급자가 고유 사용자 ID를 반환하지 않았습니다.")
    sub = provider_subject
    now = int(time.time())
    claims = {"sub": sub, "provider": provider, "email": (email or "")[:254],
              "email_verified": bool(email_verified), "name": (name or "")[:160],
              "picture": (picture or "")[:1000], "iat": now, "exp": now + SESSION_TTL_SECONDS}
    now_iso = datetime.now(TZ).isoformat()
    with closing(db()) as con:
        con.execute("INSERT INTO users(user_sub,email,name,storage_used_bytes,created_at,last_login_at) VALUES(?,?,?,?,?,?) "
                    "ON CONFLICT(user_sub) DO UPDATE SET email=excluded.email,name=excluded.name,last_login_at=excluded.last_login_at",
                    (sub, claims["email"], claims["name"], 0, now_iso, now_iso))
        con.commit()
    return claims


def _verify_oidc_id_token(token: str, jwks: dict[str, Any], audience: str,
                          issuer: str, nonce: str) -> dict[str, Any]:
    try:
        import jwt
        header = jwt.get_unverified_header(token)
        if header.get("alg") != "RS256" or not header.get("kid"):
            raise ValueError("지원하지 않는 ID 토큰 서명 알고리즘입니다.")
        jwk = next((item for item in jwks.get("keys", []) if item.get("kid") == header["kid"]), None)
        if not jwk:
            raise ValueError("ID 토큰 서명 키를 찾을 수 없습니다.")
        signing_key = jwt.PyJWK.from_dict(jwk).key
        claims = jwt.decode(token, signing_key, algorithms=["RS256"], audience=audience, issuer=issuer,
                            options={"require": ["exp", "iat", "iss", "aud", "sub"]}, leeway=60)
        if not hmac.compare_digest(str(claims.get("nonce", "")), nonce):
            raise ValueError("로그인 nonce 검증에 실패했습니다.")
        return claims
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(401, "외부 계정의 ID 토큰을 검증하지 못했습니다.") from exc


async def _oauth_json(client: httpx.AsyncClient, method: str, url: str, **kwargs) -> dict[str, Any]:
    try:
        response = await client.request(method, url, **kwargs)
        response.raise_for_status()
        data = response.json()
        if not isinstance(data, dict):
            raise ValueError("JSON 객체 응답이 아닙니다.")
        return data
    except httpx.HTTPStatusError as exc:
        # Do not expose raw provider body: it may contain tokens or secrets.
        raise HTTPException(502, f"외부 로그인 공급자가 요청을 거부했습니다. (HTTP {exc.response.status_code})") from exc
    except (httpx.HTTPError, ValueError) as exc:
        raise HTTPException(502, "외부 로그인 공급자와 통신하지 못했습니다.") from exc


def _validate_project_route(plan: dict[str, Any], result: dict[str, Any]) -> None:
    if len(json.dumps(plan, ensure_ascii=False)) > 1_000_000 or len(json.dumps(result, ensure_ascii=False)) > 2_000_000:
        raise HTTPException(413, "프로젝트 경로 데이터가 너무 큽니다.")
    def valid_point(point):
        if not isinstance(point, dict):
            return False
        try:
            lat, lon = float(point.get("lat")), float(point.get("lon"))
            return math.isfinite(lat) and math.isfinite(lon) and -90 <= lat <= 90 and -180 <= lon <= 180
        except (TypeError, ValueError):
            return False
    if not valid_point(plan.get("origin")) or not valid_point(plan.get("destination")):
        raise HTTPException(400, "프로젝트 경로에는 유효한 출발지와 도착지 좌표가 필요합니다.")
    vias = plan.get("vias", [])
    if not isinstance(vias, list) or len(vias) > 50 or not all(valid_point(item) for item in vias):
        raise HTTPException(400, "경유지 데이터 또는 좌표가 올바르지 않습니다.")


def _project_member(con, project_id: str, claims: dict[str, Any], roles: tuple[str, ...] = ("owner", "editor", "viewer")):
    row = con.execute("SELECT p.owner_sub,p.archived_at,m.role FROM projects p "
                      "JOIN project_members m ON m.project_id=p.project_id "
                      "WHERE p.project_id=? AND m.user_sub=?", (project_id, str(claims["sub"]))).fetchone()
    if not row:
        raise HTTPException(404, "프로젝트를 찾을 수 없거나 접근 권한이 없습니다.")
    if row[1]:
        raise HTTPException(410, "보관 처리된 프로젝트입니다.")
    role = str(row[2])
    if role not in roles:
        raise HTTPException(403, "이 작업을 수행할 프로젝트 권한이 없습니다.")
    return role


def _lock_project(con, project_id: str) -> None:
    """Serialize quota-sensitive writes for one project across DB workers."""
    if DB_IS_POSTGRES:
        con.execute("SELECT project_id FROM projects WHERE project_id=? FOR UPDATE", (project_id,)).fetchone()
    else:
        # A no-op write obtains SQLite's write reservation before counting.
        con.execute("UPDATE projects SET updated_at=updated_at WHERE project_id=?", (project_id,))

def _lock_user(con, user_sub: str) -> None:
    """Serialize per-account quota checks."""
    if DB_IS_POSTGRES:
        con.execute("SELECT user_sub FROM users WHERE user_sub=? FOR UPDATE", (user_sub,)).fetchone()
    else:
        con.execute("UPDATE users SET last_login_at=last_login_at WHERE user_sub=?", (user_sub,))


def _project_list_row(row) -> dict[str, Any]:
    return {"project_id": row[0], "name": row[1], "description": row[2], "owner_sub": row[3],
            "role": row[4], "member_count": int(row[5]), "route_count": int(row[6]),
            "created_at": row[7], "updated_at": row[8]}


@app.get("/auth/config")
async def auth_config() -> dict[str, Any]:
    google_enabled = bool(GOOGLE_CLIENT_ID and len(SESSION_SECRET) >= 32)
    naver_enabled = bool(NAVER_CLIENT_ID and NAVER_CLIENT_SECRET and NAVER_REDIRECT_URI and len(SESSION_SECRET) >= 32)
    microsoft_enabled = bool(MICROSOFT_CLIENT_ID and MICROSOFT_CLIENT_SECRET and MICROSOFT_REDIRECT_URI and len(SESSION_SECRET) >= 32)
    return {"google_signin_enabled": google_enabled, "google_client_id": GOOGLE_CLIENT_ID if google_enabled else None,
            "naver_signin_enabled": naver_enabled, "microsoft_signin_enabled": microsoft_enabled,
            "project_invite_email_enabled": invite_email_configured(),
            "providers": {"google": google_enabled, "naver": naver_enabled, "microsoft": microsoft_enabled,
                          "project_invite_email": invite_email_configured()}}


@app.get("/auth/naver/start")
async def naver_login_start(request: Request, return_to: str = "/"):
    if not (NAVER_CLIENT_ID and NAVER_CLIENT_SECRET and NAVER_REDIRECT_URI and len(SESSION_SECRET) >= 32):
        raise HTTPException(503, "네이버 로그인이 아직 설정되지 않았습니다.")
    state, nonce, verifier = secrets.token_urlsafe(32), secrets.token_urlsafe(32), secrets.token_urlsafe(48)
    challenge = _b64url(hashlib.sha256(verifier.encode("ascii")).digest())
    params = {"response_type": "code", "client_id": NAVER_CLIENT_ID, "redirect_uri": NAVER_REDIRECT_URI,
              "state": state, "scope": "openid", "nonce": nonce, "code_challenge": challenge,
              "code_challenge_method": "S256"}
    response = RedirectResponse("https://nid.naver.com/oauth2/authorize?" + urlencode(params), status_code=302)
    response.set_cookie(OAUTH_STATE_COOKIE, _oauth_state_cookie("naver", state, nonce, verifier, return_to), max_age=600,
                        httponly=True, secure=_cookie_secure(request), samesite="lax", path="/")
    return response


@app.get("/auth/naver/callback")
async def naver_login_callback(request: Request, code: str = "", state: str = "", error: str = ""):
    if error or not code:
        raise HTTPException(400, "네이버 로그인이 취소되었거나 승인되지 않았습니다.")
    state_claims = _consume_oauth_state(request, "naver", state)
    if not (NAVER_CLIENT_ID and NAVER_CLIENT_SECRET and NAVER_REDIRECT_URI):
        raise HTTPException(503, "네이버 로그인 설정이 완료되지 않았습니다.")
    async with httpx.AsyncClient(timeout=15, follow_redirects=False) as client:
        token_data = await _oauth_json(client, "POST", "https://nid.naver.com/oauth2/token", data={
            "grant_type": "authorization_code", "client_id": NAVER_CLIENT_ID,
            "client_secret": NAVER_CLIENT_SECRET, "code": code, "state": state,
            "redirect_uri": NAVER_REDIRECT_URI, "code_verifier": state_claims["verifier"]})
        access_token, id_token_value = token_data.get("access_token"), token_data.get("id_token")
        if not access_token or not id_token_value:
            raise HTTPException(502, "네이버가 ID 토큰 또는 액세스 토큰을 반환하지 않았습니다.")
        jwks = await _oauth_json(client, "GET", "https://nid.naver.com/oauth2/jwks")
        identity = _verify_oidc_id_token(id_token_value, jwks, NAVER_CLIENT_ID, "https://nid.naver.com", state_claims["nonce"])
        # The validated OIDC subject is sufficient for account identity. The
        # legacy profile endpoint is optional display metadata; a temporary
        # failure there must not invalidate an otherwise valid OIDC login.
        try:
            profile = await _oauth_json(client, "GET", "https://openapi.naver.com/v1/nid/me",
                                        headers={"Authorization": f"Bearer {access_token}"})
        except HTTPException:
            profile = {}
    # OIDC sub is the canonical, application-specific identity key. The
    # separate legacy profile endpoint is used only for display fields; its
    # `id` field is not assumed to be interchangeable with the OIDC subject.
    profile_data = profile.get("response") if isinstance(profile.get("response"), dict) else {}
    provider_sub = str(identity.get("sub", ""))
    if not provider_sub:
        raise HTTPException(401, "네이버 OIDC 사용자 식별 정보가 없습니다.")
    claims = _provider_user_session("naver", "naver:" + provider_sub,
                                    str(profile_data.get("email", "")), str(profile_data.get("name", "")),
                                    False, str(profile_data.get("profile_image", "")))
    response = RedirectResponse(_oauth_success_url(request, str(state_claims.get("return_to", "/"))), status_code=303)
    response.set_cookie(SESSION_COOKIE, _session_token(claims), max_age=SESSION_TTL_SECONDS, httponly=True,
                        secure=_cookie_secure(request), samesite="lax", path="/")
    response.delete_cookie(OAUTH_STATE_COOKIE, path="/", httponly=True, secure=_cookie_secure(request), samesite="lax")
    return response


@app.get("/auth/microsoft/start")
async def microsoft_login_start(request: Request, return_to: str = "/"):
    if not (MICROSOFT_CLIENT_ID and MICROSOFT_CLIENT_SECRET and MICROSOFT_REDIRECT_URI and len(SESSION_SECRET) >= 32):
        raise HTTPException(503, "Microsoft 로그인이 아직 설정되지 않았습니다.")
    state, nonce, verifier = secrets.token_urlsafe(32), secrets.token_urlsafe(32), secrets.token_urlsafe(48)
    challenge = _b64url(hashlib.sha256(verifier.encode("ascii")).digest())
    discovery_url = f"https://login.microsoftonline.com/{MICROSOFT_TENANT}/v2.0/.well-known/openid-configuration"
    async with httpx.AsyncClient(timeout=12) as client:
        discovery = await _oauth_json(client, "GET", discovery_url)
    params = {"client_id": MICROSOFT_CLIENT_ID, "response_type": "code", "redirect_uri": MICROSOFT_REDIRECT_URI,
              "response_mode": "query", "scope": "openid profile email", "state": state, "nonce": nonce,
              "code_challenge": challenge, "code_challenge_method": "S256"}
    response = RedirectResponse(str(discovery["authorization_endpoint"]) + "?" + urlencode(params), status_code=302)
    response.set_cookie(OAUTH_STATE_COOKIE, _oauth_state_cookie("microsoft", state, nonce, verifier, return_to), max_age=600,
                        httponly=True, secure=_cookie_secure(request), samesite="lax", path="/")
    return response


@app.get("/auth/microsoft/callback")
async def microsoft_login_callback(request: Request, code: str = "", state: str = "", error: str = ""):
    if error or not code:
        raise HTTPException(400, "Microsoft 로그인이 취소되었거나 승인되지 않았습니다.")
    state_claims = _consume_oauth_state(request, "microsoft", state)
    if not (MICROSOFT_CLIENT_ID and MICROSOFT_CLIENT_SECRET and MICROSOFT_REDIRECT_URI):
        raise HTTPException(503, "Microsoft 로그인 설정이 완료되지 않았습니다.")
    discovery_url = f"https://login.microsoftonline.com/{MICROSOFT_TENANT}/v2.0/.well-known/openid-configuration"
    async with httpx.AsyncClient(timeout=15, follow_redirects=False) as client:
        discovery = await _oauth_json(client, "GET", discovery_url)
        token_data = await _oauth_json(client, "POST", str(discovery["token_endpoint"]), data={
            "client_id": MICROSOFT_CLIENT_ID, "client_secret": MICROSOFT_CLIENT_SECRET,
            "grant_type": "authorization_code", "code": code, "redirect_uri": MICROSOFT_REDIRECT_URI,
            "scope": "openid profile email", "code_verifier": state_claims["verifier"]})
        id_token_value = token_data.get("id_token")
        if not id_token_value:
            raise HTTPException(502, "Microsoft가 ID 토큰을 반환하지 않았습니다.")
        try:
            import jwt
            unverified = jwt.decode(id_token_value, options={"verify_signature": False, "verify_aud": False})
        except Exception as exc:
            raise HTTPException(401, "Microsoft ID 토큰을 읽을 수 없습니다.") from exc
        tenant_id = str(unverified.get("tid", ""))
        oid = str(unverified.get("oid", ""))
        if not tenant_id:
            raise HTTPException(401, "Microsoft ID 토큰에 테넌트 ID가 없습니다.")
        expected_issuer = str(discovery.get("issuer", "")).replace("{tenantid}", tenant_id)
        jwks = await _oauth_json(client, "GET", str(discovery["jwks_uri"]))
        identity = _verify_oidc_id_token(id_token_value, jwks, MICROSOFT_CLIENT_ID, expected_issuer, state_claims["nonce"])
        # The tenant/object identifiers are used to select discovery metadata
        # before signature verification. Re-check them against signed claims.
        if str(identity.get("tid", "")) != tenant_id:
            raise HTTPException(401, "Microsoft ID 토큰의 테넌트 정보가 일치하지 않습니다.")
        signed_oid = str(identity.get("oid", ""))
        if oid and signed_oid != oid:
            raise HTTPException(401, "Microsoft ID 토큰의 사용자 식별 정보가 일치하지 않습니다.")
    stable_id = f"microsoft:{tenant_id}:{str(identity.get('oid', '')) or identity.get('sub', '')}"
    claims = _provider_user_session("microsoft", stable_id,
                                    str(identity.get("email", identity.get("preferred_username", ""))),
                                    str(identity.get("name", "")), False, "")
    response = RedirectResponse(_oauth_success_url(request, str(state_claims.get("return_to", "/"))), status_code=303)
    response.set_cookie(SESSION_COOKIE, _session_token(claims), max_age=SESSION_TTL_SECONDS, httponly=True,
                        secure=_cookie_secure(request), samesite="lax", path="/")
    response.delete_cookie(OAUTH_STATE_COOKIE, path="/", httponly=True, secure=_cookie_secure(request), samesite="lax")
    return response


@app.post("/auth/google")
async def google_login(body: GoogleLoginRequest, request: Request, response: Response) -> dict[str, Any]:
    _require_same_origin(request)
    if not GOOGLE_CLIENT_ID or len(SESSION_SECRET) < 32:
        raise HTTPException(503, "Google 로그인 설정이 아직 완료되지 않았습니다.")
    require_durable_database()
    try:
        from google.auth.transport.requests import Request as GoogleRequest
        from google.oauth2 import id_token
        identity = id_token.verify_oauth2_token(body.credential, GoogleRequest(), GOOGLE_CLIENT_ID)
    except ImportError as exc:
        raise HTTPException(503, "Google 로그인 모듈이 설치되지 않았습니다. requirements.txt를 확인하세요.") from exc
    except Exception as exc:
        raise HTTPException(401, "Google 로그인 토큰을 확인하지 못했습니다. 다시 로그인해 주세요.") from exc
    issuer = str(identity.get("iss", ""))
    if issuer not in ("accounts.google.com", "https://accounts.google.com"):
        raise HTTPException(401, "인증 발급자가 올바르지 않습니다.")
    if identity.get("email_verified") is not True:
        raise HTTPException(403, "Google에서 이메일 인증이 완료된 계정만 사용할 수 있습니다.")
    now = int(time.time())
    claims = {"sub": str(identity["sub"]), "provider": "google", "email": str(identity.get("email", "")),
              "email_verified": True, "name": str(identity.get("name", ""))[:160],
              "picture": str(identity.get("picture", ""))[:1000], "iat": now,
              "exp": now + SESSION_TTL_SECONDS}
    with closing(db()) as con:
        con.execute("INSERT INTO users(user_sub,email,name,storage_used_bytes,created_at,last_login_at) VALUES(?,?,?,?,?,?) "
                    "ON CONFLICT(user_sub) DO UPDATE SET email=excluded.email,name=excluded.name,last_login_at=excluded.last_login_at",
                    (claims["sub"], claims["email"], claims["name"], 0, datetime.now(TZ).isoformat(), datetime.now(TZ).isoformat()))
        con.commit()
    token = _session_token(claims)
    response.set_cookie(SESSION_COOKIE, token, max_age=SESSION_TTL_SECONDS, httponly=True,
                        secure=_cookie_secure(request), samesite="lax", path="/")
    return {"ok": True, "authenticated": True, "user": _public_user(claims), "is_owner": _is_owner(claims)}


@app.get("/auth/me")
async def auth_me(request: Request) -> dict[str, Any]:
    claims = _read_session(request)
    if not claims:
        return {"authenticated": False, "user": None, "is_owner": False}
    return {"authenticated": True, "user": _public_user(claims), "is_owner": _is_owner(claims)}


@app.post("/auth/logout")
async def auth_logout(request: Request, response: Response) -> dict[str, bool]:
    _require_same_origin(request)
    response.delete_cookie(SESSION_COOKIE, path="/", httponly=True,
                          secure=_cookie_secure(request), samesite="lax")
    response.delete_cookie(OAUTH_STATE_COOKIE, path="/", httponly=True,
                          secure=_cookie_secure(request), samesite="lax")
    return {"ok": True}


@app.post("/admin/providers/probe")
async def admin_provider_probe(body: ProviderProbeRequest, request: Request):
    actor = _admin_session(request)
    _enforce_provider_rate_limit(request)
    _require_same_origin(request)
    if not DATA_GO_KEY:
        raise HTTPException(503, "DATA_GO_KR_SERVICE_KEY가 서버 Secret에 설정되지 않았습니다.")
    include_paging = True
    normalization_kind = ""
    if body.provider == "tago_rail":
        service, operation, params, format_parameter, format_value = TAGO_TRAIN_SERVICE_NAME, TAGO_TRAIN_OP_CITY_CODES, {}, "_type", "json"
        include_paging = False
        normalization_kind = "city"
        label = "TAGO 철도 도시코드 목록"
    elif body.provider == "tago_bus_city_codes":
        service, operation, params, format_parameter, format_value = "BusSttnInfoInqireService", "getCtyCodeList", {}, "_type", "json"
        include_paging = False
        normalization_kind = "city"
        label = "TAGO 버스 도시코드 목록"
    elif body.provider == "tago_rail_stations":
        if not body.city_code:
            raise HTTPException(400, "철도역 목록 검사는 도시코드가 필요합니다.")
        service, operation = TAGO_TRAIN_SERVICE_NAME, TAGO_TRAIN_OP_STATIONS
        params, format_parameter, format_value = {"cityCode": body.city_code}, "_type", "json"
        normalization_kind = "station"
        label = "TAGO 시도별 철도역 목록"
    elif body.provider == "tago_rail_timetable":
        if not (body.dep_station_id and body.arr_station_id and body.operation_date):
            raise HTTPException(400, "열차 시간표 검사는 출발역 ID·도착역 ID·출발일이 필요합니다.")
        if body.dep_station_id == body.arr_station_id:
            raise HTTPException(400, "출발역과 도착역은 서로 달라야 합니다.")
        try:
            datetime.strptime(body.operation_date, "%Y%m%d")
        except ValueError:
            raise HTTPException(400, "열차 출발일은 YYYYMMDD 형식의 실제 날짜여야 합니다.")
        service, operation = TAGO_TRAIN_SERVICE_NAME, TAGO_TRAIN_OP_TIMETABLE
        params = {"depPlaceId": body.dep_station_id, "arrPlaceId": body.arr_station_id,
                  "depPlandTime": body.operation_date}
        if body.train_grade_code:
            params["trainGradeCode"] = body.train_grade_code
        format_parameter, format_value = "_type", "json"
        normalization_kind = "train"
        label = "TAGO 출발·도착역 열차 시간표"
    elif body.provider == "tago_bus_stop_routes":
        if not (body.city_code and body.node_id):
            raise HTTPException(400, "정류소 경유노선 검사는 도시코드와 정류소 ID가 필요합니다.")
        service, operation = "BusSttnInfoInqireService", "getSttnThrghRouteList"
        params, format_parameter, format_value = {"cityCode": body.city_code, "nodeid": body.node_id}, "_type", "json"
        normalization_kind = "stop_routes"
        label = "TAGO 정류소별 경유노선"
    elif body.provider == "tago_bus_arrivals":
        if not (body.city_code and body.node_id):
            raise HTTPException(400, "버스 도착정보 검사는 도시코드와 정류소 ID가 필요합니다.")
        service, operation = "ArvlInfoInqireService", "getSttnAcctoArvlPrearngeInfoList"
        params, format_parameter, format_value = {"cityCode": body.city_code, "nodeId": body.node_id}, "_type", "json"
        normalization_kind = "arrival"
        label = "TAGO 정류소별 실시간 버스 도착정보"
    elif body.provider == "tago_bus_stops":
        if not (body.province_code and body.district_code and body.route_id):
            raise HTTPException(400, "버스 경유정류장 검사는 시도코드·시군구코드·노선ID가 필요합니다.")
        date_value = body.operation_date or datetime.now(TZ).strftime("%Y%m%d")
        try:
            datetime.strptime(date_value, "%Y%m%d")
        except ValueError:
            raise HTTPException(400, "운행일은 YYYYMMDD 형식의 실제 날짜여야 합니다.")
        service, operation = "BusRoutespecificStopInformation", "getBusRoutespecificStopInformation"
        params = {"opr_ymd": date_value, "rte_id": body.route_id,
                  "ctpv_cd": body.province_code, "sgg_cd": body.district_code,
                  "pageNo": 1, "numOfRows": 10}
        format_parameter, format_value = "dataType", "JSON"
        normalization_kind = "bus_stops"
        label = "국토교통부 버스노선별 경유정류장"
    elif body.province_code:
        date_value = body.operation_date or datetime.now(TZ).strftime("%Y%m%d")
        try:
            datetime.strptime(date_value, "%Y%m%d")
        except ValueError:
            raise HTTPException(400, "운행일은 YYYYMMDD 형식의 실제 날짜여야 합니다.")
        service, operation = "BusRoute", "getBusRoute"
        params = {"opr_ymd": date_value, "ctpv_cd": body.province_code, "pageNo": 1, "numOfRows": 10}
        if body.route_id:
            params["rte_id"] = body.route_id
        format_parameter, format_value = "dataType", "JSON"
        normalization_kind = "bus_routes"
        label = "국토교통부 버스노선 목록"
    else:
        service, operation, params, format_parameter, format_value = "BusSttnInfoInqireService", "getCtyCodeList", {}, "_type", "json"
        include_paging = False
        normalization_kind = "city"
        label = "TAGO 버스 도시코드 목록"
    started = time.monotonic()
    payload = await data_go_request(service, operation, params, format_parameter=format_parameter,
                                    format_value=format_value, include_paging=include_paging)
    rows = parse_data_go_items(payload)
    normalizers = {
        "city": normalize_tago_city,
        "station": normalize_tago_station,
        "train": normalize_tago_train,
        "stop_routes": normalize_tago_stop_route,
        "arrival": normalize_tago_arrival,
        "bus_stops": normalize_tago_bus_stop,
        "bus_routes": normalize_tago_bus_route,
    }
    samples = [x for x in (normalizers[normalization_kind](r) for r in rows[:5]) if x]
    with closing(db()) as con:
        _audit(con, actor, "provider.probe", "provider", body.provider, None,
               {"service": service, "operation": operation, "success": True,
                "result_count": len(rows), "normalized_sample_count": len(samples)},
               "총괄자가 서버 측 교통 API 연결 검사를 실행")
        con.commit()
    return {"ok": True, "provider": body.provider, "label": label,
            "service": service, "operation": operation,
            "result_count": len(rows), "normalized_sample_count": len(samples),
            "normalization_warning": bool(rows and not samples), "sample": samples,
            "elapsed_ms": int((time.monotonic() - started) * 1000),
            "tested_at": datetime.now(TZ).isoformat(), "secret_values_returned": False}


@app.get("/admin/config/status")
async def admin_config_status(request: Request) -> dict[str, Any]:
    _admin_session(request)
    with closing(db()) as con:
        feed_count = con.execute("SELECT COUNT(*) FROM feeds WHERE is_active=1").fetchone()[0]
        source_count = con.execute("SELECT COUNT(*) FROM data_sources WHERE active=1").fetchone()[0]
        import_job_count = con.execute("SELECT COUNT(*) FROM data_import_jobs").fetchone()[0]
        staging_job_count = con.execute("SELECT COUNT(*) FROM gtfs_staging_uploads").fetchone()[0]
        worker_row = con.execute("SELECT worker_id,status,last_seen,last_error FROM gtfs_worker_heartbeats ORDER BY last_seen DESC LIMIT 1").fetchone()
        user_count = con.execute("SELECT COUNT(*) FROM users").fetchone()[0]
        feedback_count = con.execute("SELECT COUNT(*) FROM feedback").fetchone()[0]
        cloud_count = con.execute("SELECT COUNT(*) FROM cloud_files").fetchone()[0]
        invite_email_count = con.execute("SELECT COUNT(*) FROM project_invite_email_events").fetchone()[0]
        invite_email_sent_today = _invite_email_quota_count(con, datetime.now(TZ))
        invite_delivery_status_counts = {str(r[0]): int(r[1]) for r in con.execute("SELECT status,COUNT(*) FROM project_invite_email_events GROUP BY status").fetchall()}
    durable = durable_database_ready()
    cos_ready = cos_is_configured()
    worker_alive = False
    if worker_row:
        try:
            worker_alive = (datetime.now(TZ) - datetime.fromisoformat(str(worker_row[2]))).total_seconds() <= int(os.getenv("GTFS_WORKER_HEARTBEAT_TTL_SECONDS", "120")) and worker_row[1] != "stopped"
        except Exception:
            worker_alive = False
    checks = _beta_readiness_checks(durable=durable, cos_ready=cos_ready,
                                    data_ready=bool(feed_count), worker_alive=worker_alive)
    return {
        "app_version": APP_VERSION,
        "beta_readiness": {"ready": all(checks.values()), "checks": checks,
                           "message": "필수 설정이 모두 연결되어야 비공개 베타를 시작할 수 있습니다."},
        "providers": {
            "data_go_kr": {"configured": bool(DATA_GO_KEY), "secret_values_returned": False,
                           "bus_route_api": "BusRoute/getBusRoute", "rail_operations": [TAGO_TRAIN_OP_CITY_CODES, TAGO_TRAIN_OP_STATIONS, TAGO_TRAIN_OP_TIMETABLE], "rail_service": TAGO_TRAIN_SERVICE_NAME},
            "tago_bus": {"configured": bool(DATA_GO_KEY), "capabilities": ["nearby_stops", "arrivals", "regional_routes"]},
            "tago_rail": {"configured": bool(DATA_GO_KEY), "capabilities": ["city_codes", "stations", "direct_timetables"]},
            "kakao_local": {"configured": bool(KAKAO_REST_KEY), "secret_values_returned": False},
            "photon": {"configured": True, "is_fallback": True},
            "google_signin": {"configured": checks["google_signin"]},
            "project_invite_email": {"configured": invite_email_configured(),
                                     "provider": "resend", "sender": INVITE_FROM_EMAIL if invite_email_configured() else "",
                                     "daily_limit": INVITE_EMAIL_DAILY_LIMIT,
                                     "attempts_today": invite_email_sent_today,
                                     "attempts_total": int(invite_email_count),
                                     "reply_to": INVITE_REPLY_TO_EMAIL,
                                     "webhook_configured": resend_webhook_secret_configured(),
                                     "delivery_tracking": resend_webhook_secret_configured(),
                                     "delivery_status_counts": invite_delivery_status_counts,
                                     "secret_values_returned": False},
            "tencent_cos": {"credentials_present": cos_ready, "integration_status": "enabled" if cos_ready else "not_configured"},
            "gtfs_large_file_staging": {"enabled": bool(durable and cos_ready),
                "part_size_mb": GTFS_STAGING_PART_SIZE // (1024*1024),
                "max_file_mb": GTFS_STAGING_MAX_BYTES // (1024*1024),
                "worker_required": True, "worker_online": worker_alive,
                "worker_last_seen": str(worker_row[2]) if worker_row else None},
        },
        "persistence": {"database": "postgresql" if DB_IS_POSTGRES else "sqlite_local",
                        "durable_storage_ready": durable,
                        "note": "운영 환경에서는 DATABASE_URL로 관리형 PostgreSQL을 연결해야 합니다."},
        "usage": {"users": int(user_count), "feedback": int(feedback_count), "cloud_files": int(cloud_count), "gtfs_feeds": int(feed_count), "active_data_sources": int(source_count), "gtfs_import_jobs": int(import_job_count), "gtfs_staging_jobs": int(staging_job_count)},
        "security": {"admin_login": "google_session", "api_secrets_exposed": False},
    }


@app.get("/places/search")
async def place_search(q: str = Query(min_length=2, max_length=120), lat: float | None = None, lon: float | None = None, limit: int = 8):
    limit = max(1, min(limit, 12))
    async with httpx.AsyncClient(timeout=12, headers={"User-Agent": "B-ROUTE/1.0 (public transit trip planner)"}) as client:
        if KAKAO_REST_KEY:
            try:
                resp = await client.get("https://dapi.kakao.com/v2/local/search/keyword.json",
                    params={"query": q, "size": limit, **({"x": lon, "y": lat, "sort": "distance"} if lat is not None and lon is not None else {})},
                    headers={"Authorization": f"KakaoAK {KAKAO_REST_KEY}"})
                resp.raise_for_status()
                docs = resp.json().get("documents", [])
                if docs:
                    return {"provider": "kakao", "results": [{"id": f"kakao:{d.get('id')}", "name": d.get("place_name", "장소"),
                        "address": d.get("road_address_name") or d.get("address_name", ""), "lat": float(d["y"]), "lon": float(d["x"]),
                        "kind": d.get("category_name", "place"), "phone": d.get("phone", ""), "url": d.get("place_url", ""), "source": "Kakao Local"} for d in docs]}
                # Kakao Local is Korea-focused; fall through to Photon for
                # overseas places or terms not found in the Kakao index.
            except Exception:
                # Keep the cross-region/international Photon fallback available
                # even if the optional Kakao provider has a temporary problem.
                pass
        try:
            params = {"q": q, "lang": "default", "limit": limit}
            if lat is not None and lon is not None:
                params.update({"lat": lat, "lon": lon})
            resp = await client.get(PHOTON_URL, params=params)
            resp.raise_for_status()
            features = resp.json().get("features", [])
            return {"provider": "photon", "results": [x for x in (normalize_photon_feature(f) for f in features) if x]}
        except Exception as exc:
            raise HTTPException(502, f"장소 검색 서비스에 연결하지 못했습니다: {exc}") from exc


@app.get("/places/reverse")
async def reverse_geocode(lat: float, lon: float):
    async with httpx.AsyncClient(timeout=12, headers={"User-Agent": "B-ROUTE/1.0 contact: configure-your-app"}) as client:
        if KAKAO_REST_KEY:
            try:
                resp = await client.get("https://dapi.kakao.com/v2/local/geo/coord2address.json", params={"x": lon, "y": lat}, headers={"Authorization": f"KakaoAK {KAKAO_REST_KEY}"})
                resp.raise_for_status()
                docs = resp.json().get("documents", [])
                if docs:
                    d = docs[0]
                    addr = d.get("road_address") or d.get("address") or {}
                    return {"name": addr.get("building_name") or addr.get("address_name") or "선택한 위치", "address": addr.get("address_name", ""), "lat": lat, "lon": lon, "source": "Kakao Local"}
            except Exception:
                pass
        try:
            resp = await client.get("https://photon.komoot.io/reverse", params={"lat": lat, "lon": lon, "lang": "default"})
            resp.raise_for_status()
            features = resp.json().get("features", [])
            if features:
                place = normalize_photon_feature(features[0])
                return {**(place or {}), "lat": lat, "lon": lon}
        except Exception:
            pass
    return {"name": "지도에서 선택한 위치", "address": f"위도 {lat:.5f}, 경도 {lon:.5f}", "lat": lat, "lon": lon, "source": "GPS/지도 좌표"}


@app.get("/transit/nearby")
async def nearby_stops(request: Request, lat: float = Query(ge=-90, le=90),
                       lon: float = Query(ge=-180, le=180),
                       radius: int = Query(default=500, ge=100, le=500)):
    """Search TAGO's documented 500m vicinity, then apply a smaller local radius.

    The upstream operation has no radius query parameter; it returns stops
    within its fixed vicinity. Never claim support for distances > 500m.
    """
    _enforce_provider_rate_limit(request)
    payload = await data_go_get("BusSttnInfoInqireService", "getCrdntPrxmtSttnList",
                                {"gpsLati": lat, "gpsLong": lon, "numOfRows": 100})
    _header, body = _data_go_response_parts(payload)
    rows = parse_data_go_items(payload)
    normalized = []
    for x in rows:
        try:
            stop_lat = float(x.get("gpslati") or x.get("gpsLati"))
            stop_lon = float(x.get("gpslong") or x.get("gpsLong"))
            # Haversine distance in meters for the user-selected radius (up to TAGO's 500m range).
            p1, p2 = math.radians(lat), math.radians(stop_lat)
            dlat, dlon = p2 - p1, math.radians(stop_lon - lon)
            a = math.sin(dlat / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dlon / 2) ** 2
            distance_m = 6371000 * 2 * math.asin(min(1.0, math.sqrt(a)))
            if distance_m > radius:
                continue
            normalized.append({"id": x.get("nodeid") or x.get("nodeId"), "name": x.get("nodenm") or x.get("nodeNm") or "버스정류장",
                "ars": x.get("nodeno") or x.get("nodeNo") or "", "city_code": x.get("citycode") or x.get("cityCode"),
                "lat": stop_lat, "lon": stop_lon, "distance_m": round(distance_m), "source": "TAGO"})
        except (TypeError, ValueError):
            continue
    normalized.sort(key=lambda item: item["distance_m"])
    return {"provider": "TAGO", "count": len(normalized), "stops": normalized,
            "requested_radius_m": radius, "provider_max_radius_m": 500,
            "raw_provider_count": len(rows), "total_count": _safe_int(body.get("totalCount")) or len(rows),
            "retrieved_at": datetime.now(TZ).isoformat()}


@app.get("/transit/stops/{node_id}/routes")
async def stop_routes(node_id: str, request: Request,
                      city_code: str = Query(min_length=1, max_length=5),
                      page: int = Query(default=1, ge=1, le=10000),
                      page_size: int = Query(default=100, ge=1, le=500)):
    """Return routes serving a TAGO stop using the official stop-info service.

    getSttnThrghRouteList belongs to BusSttnInfoInqireService. Its request
    fields are cityCode and lowercase nodeid; this differs from the nodeId
    spelling used by the arrivals service.
    """
    _enforce_provider_rate_limit(request)
    if not node_id or len(node_id) > 30:
        raise HTTPException(400, "유효하지 않은 정류소 ID입니다.")
    params = {"cityCode": city_code, "nodeid": node_id,
              "pageNo": page, "numOfRows": page_size}
    key = _provider_cache_key("tago_stop_routes", params)
    cached = _provider_cache_get(key)
    if cached:
        return {**cached, "cache_hit": True}
    payload = await data_go_get("BusSttnInfoInqireService", "getSttnThrghRouteList", params)
    _header, body = _data_go_response_parts(payload)
    rows = parse_data_go_items(payload)
    routes = [x for x in (normalize_tago_stop_route(r) for r in rows) if x]
    result = {"routes": routes, "count": len(routes),
              "total_count": _safe_int(body.get("totalCount")) or len(rows),
              "page": page, "page_size": page_size,
              "source": "TAGO", "stop_id": node_id, "city_code": city_code,
              "retrieved_at": datetime.now(TZ).isoformat(), "cache_hit": False}
    _provider_cache_put(key, result, 180)
    return result


@app.get("/transit/stops/{node_id}/arrivals")
async def stop_arrivals(node_id: str, city_code: str, request: Request):
    _enforce_provider_rate_limit(request)
    payload = await data_go_get("ArvlInfoInqireService", "getSttnAcctoArvlPrearngeInfoList", {"cityCode": city_code, "nodeId": node_id})
    rows = parse_data_go_items(payload)
    return {"arrivals": rows, "normalized_arrivals": [x for x in (normalize_tago_arrival(r) for r in rows) if x],
            "source": "TAGO", "retrieved_at": datetime.now(TZ).isoformat(), "realtime": True}


@app.get("/transit/providers/status")
async def transit_provider_status():
    configured = bool(DATA_GO_KEY)
    return {"providers": [
        {"id": "tago_bus", "name": "국토교통부 TAGO 버스", "configured": configured,
         "capabilities": ["nearby_stops", "stop_routes", "arrivals", "regional_route_catalog", "route_stop_sequence"],
         "status": "credential_present_unverified" if configured else "needs_server_secret",
         "authorization_note": "API 키 등록만으로 서비스 활용 신청 승인이 보장되지는 않습니다."},
        {"id": "tago_rail", "name": "국토교통부 TAGO 열차", "configured": configured,
         "capabilities": ["city_codes", "station_catalog", "origin_destination_timetables"],
         "status": "credential_present_unverified" if configured else "needs_server_secret",
         "authorization_note": "API 키 등록만으로 서비스 활용 신청 승인이 보장되지는 않습니다."}
    ], "secrets_exposed": False,
        "routing_note": "공급원 API 응답은 경로 엔진용 GTFS 데이터와 별개입니다. 정적 그래프 등록 전까지 실시간·직접 구간 조회 보조 데이터로만 사용합니다."}


@app.get("/transit/bus/routes")
async def transit_bus_routes(request: Request, province_code: str = Query(min_length=2, max_length=5, pattern=r"^[0-9]{2,5}$"),
                             operation_date: str = Query(min_length=8, max_length=8, pattern=r"^[0-9]{8}$"),
                             route_id: str | None = Query(default=None, max_length=80),
                             page: int = Query(default=1, ge=1, le=10000),
                             page_size: int = Query(default=100, ge=1, le=500)):
    _enforce_provider_rate_limit(request)
    try:
        datetime.strptime(operation_date, "%Y%m%d")
    except ValueError:
        raise HTTPException(400, "운행일은 YYYYMMDD 형식의 실제 날짜여야 합니다.")
    params = {"opr_ymd": operation_date, "ctpv_cd": province_code,
              "pageNo": page, "numOfRows": page_size}
    if route_id:
        params["rte_id"] = route_id
    cache_params = {**params, "service": "BusRoute", "operation": "getBusRoute"}
    key = _provider_cache_key("tago_bus_route", cache_params)
    cached = _provider_cache_get(key)
    if cached:
        return {**cached, "cache_hit": True}
    payload = await data_go_request("BusRoute", "getBusRoute", params,
                                    format_parameter="dataType", format_value="JSON")
    header, body = _data_go_response_parts(payload)
    rows = parse_data_go_items(payload)
    normalized = [x for x in (normalize_tago_bus_route(r) for r in rows) if x]
    result = {"provider": "국토교통부 버스노선 API", "operation_date": operation_date,
              "province_code": province_code, "page": page, "page_size": page_size,
              "total_count": _safe_int(body.get("totalCount")) or len(rows),
              "routes": normalized, "count": len(normalized), "raw_item_count": len(rows),
              "retrieved_at": datetime.now(TZ).isoformat(), "cache_hit": False,
              "notice": "공급원 노선목록 응답입니다. 완전한 정류장별 시간표·경로 그래프를 보증하지 않습니다."}
    _provider_cache_put(key, result, 600)
    return result


@app.get("/transit/bus/routes/{route_id}/stops")
async def transit_bus_route_stops(request: Request, route_id: str,
                                  province_code: str = Query(min_length=2, max_length=5, pattern=r"^[0-9]{2,5}$"),
                                  district_code: str = Query(min_length=2, max_length=5, pattern=r"^[0-9]{2,5}$"),
                                  operation_date: str = Query(min_length=8, max_length=8, pattern=r"^[0-9]{8}$"),
                                  page: int = Query(default=1, ge=1, le=10000),
                                  page_size: int = Query(default=100, ge=1, le=500)):
    """Return ordered stops for one route using the official BusRouteSpecificStop API."""
    _enforce_provider_rate_limit(request)
    if not route_id or len(route_id) > 80:
        raise HTTPException(400, "유효하지 않은 노선 ID입니다.")
    try:
        datetime.strptime(operation_date, "%Y%m%d")
    except ValueError:
        raise HTTPException(400, "운행일은 YYYYMMDD 형식의 실제 날짜여야 합니다.")
    params = {"opr_ymd": operation_date, "rte_id": route_id,
              "ctpv_cd": province_code, "sgg_cd": district_code,
              "pageNo": page, "numOfRows": page_size}
    key = _provider_cache_key("tago_bus_route_stops", params)
    cached = _provider_cache_get(key)
    if cached:
        return {**cached, "cache_hit": True}
    payload = await data_go_request("BusRoutespecificStopInformation", "getBusRoutespecificStopInformation", params,
                                    format_parameter="dataType", format_value="JSON")
    _header, body = _data_go_response_parts(payload)
    rows = parse_data_go_items(payload)
    stops = [x for x in (normalize_tago_bus_stop(r) for r in rows) if x]
    stops.sort(key=lambda x: (x.get("sequence") is None, x.get("sequence") or 0))
    result = {"provider": "국토교통부 버스노선별 경유정류장", "route_id": route_id,
              "operation_date": operation_date, "province_code": province_code, "district_code": district_code,
              "page": page, "page_size": page_size,
              "total_count": _safe_int(body.get("totalCount")) or len(rows),
              "stops": stops, "count": len(stops), "retrieved_at": datetime.now(TZ).isoformat(),
              "cache_hit": False,
              "notice": "노선별 정류장 순서 자료입니다. 개별 정류장 시간표·실시간 도착정보와는 별도입니다."}
    _provider_cache_put(key, result, 600)
    return result


@app.get("/transit/rail/cities")
async def transit_rail_cities(request: Request):
    _enforce_provider_rate_limit(request)
    key = _provider_cache_key("tago_rail_cities", {})
    cached = _provider_cache_get(key)
    if cached:
        return {**cached, "cache_hit": True}
    payload = await data_go_request(TAGO_TRAIN_SERVICE_NAME, TAGO_TRAIN_OP_CITY_CODES, {}, include_paging=False)
    rows = parse_data_go_items(payload)
    cities = [x for x in (normalize_tago_city(r) for r in rows) if x]
    result = {"provider": "국토교통부 TAGO 열차정보", "cities": cities,
              "count": len(cities), "retrieved_at": datetime.now(TZ).isoformat(), "cache_hit": False}
    _provider_cache_put(key, result, 86400)
    return result


@app.get("/transit/rail/stations")
async def transit_rail_stations(request: Request, city_code: str = Query(min_length=1, max_length=12, pattern=r"^[A-Za-z0-9]+$"),
                                page: int = Query(default=1, ge=1, le=10000),
                                page_size: int = Query(default=100, ge=1, le=500)):
    _enforce_provider_rate_limit(request)
    params = {"cityCode": city_code, "pageNo": page, "numOfRows": page_size}
    key = _provider_cache_key("tago_rail_stations", params)
    cached = _provider_cache_get(key)
    if cached:
        return {**cached, "cache_hit": True}
    payload = await data_go_request(TAGO_TRAIN_SERVICE_NAME, TAGO_TRAIN_OP_STATIONS, params)
    header, body = _data_go_response_parts(payload)
    rows = parse_data_go_items(payload)
    stations = [x for x in (normalize_tago_station(r) for r in rows) if x]
    result = {"provider": "국토교통부 TAGO 열차정보", "city_code": city_code,
              "page": page, "page_size": page_size,
              "total_count": _safe_int(body.get("totalCount")) or len(rows),
              "stations": stations, "count": len(stations),
              "retrieved_at": datetime.now(TZ).isoformat(), "cache_hit": False}
    _provider_cache_put(key, result, 86400)
    return result


@app.get("/transit/rail/trains")
async def transit_rail_trains(request: Request, dep_station_id: str = Query(min_length=2, max_length=30, pattern=r"^[A-Za-z0-9_-]+$"),
                              arr_station_id: str = Query(min_length=2, max_length=30, pattern=r"^[A-Za-z0-9_-]+$"),
                              departure_date: str = Query(min_length=8, max_length=8, pattern=r"^[0-9]{8}$"),
                              train_grade_code: str | None = Query(default=None, max_length=12, pattern=r"^[A-Za-z0-9_]+$"),
                              page: int = Query(default=1, ge=1, le=10000),
                              page_size: int = Query(default=100, ge=1, le=500)):
    _enforce_provider_rate_limit(request)
    if dep_station_id == arr_station_id:
        raise HTTPException(400, "출발역과 도착역은 달라야 합니다.")
    try:
        datetime.strptime(departure_date, "%Y%m%d")
    except ValueError:
        raise HTTPException(400, "출발일은 YYYYMMDD 형식의 실제 날짜여야 합니다.")
    params = {"depPlaceId": dep_station_id, "arrPlaceId": arr_station_id,
              "depPlandTime": departure_date, "pageNo": page, "numOfRows": page_size}
    if train_grade_code:
        params["trainGradeCode"] = train_grade_code
    key = _provider_cache_key("tago_rail_trains", params)
    cached = _provider_cache_get(key)
    if cached:
        return {**cached, "cache_hit": True}
    payload = await data_go_request(TAGO_TRAIN_SERVICE_NAME, TAGO_TRAIN_OP_TIMETABLE, params)
    _header, body = _data_go_response_parts(payload)
    rows = parse_data_go_items(payload)
    trains = [x for x in (normalize_tago_train(r) for r in rows) if x]
    result = {"provider": "국토교통부 TAGO 열차정보", "departure_date": departure_date,
              "departure_station_id": dep_station_id, "arrival_station_id": arr_station_id,
              "page": page, "page_size": page_size,
              "total_count": _safe_int(body.get("totalCount")) or len(rows),
              "trains": trains, "count": len(trains),
              "retrieved_at": datetime.now(TZ).isoformat(), "cache_hit": False,
              "notice": "출발역·도착역 간 열차 조회 결과입니다. 여러 열차를 갈아타는 전체 철도 경로 계산은 GTFS 정적 데이터에서 수행합니다."}
    _provider_cache_put(key, result, 120)
    return result


def gtfs_time(value: str) -> int:
    parts = value.strip().split(":")
    if len(parts) != 3:
        return 0
    return int(parts[0]) * 3600 + int(parts[1]) * 60 + int(parts[2])


def _gtfs_members(zf: zipfile.ZipFile) -> dict[str, str]:
    """Return basename -> member path after rejecting unsafe/ambiguous ZIP entries."""
    members: dict[str, str] = {}
    total_uncompressed = 0
    infos = zf.infolist()
    if len(infos) > 200:
        raise ValueError("GTFS ZIP 내부 파일이 너무 많습니다(200개 초과).")
    for info in infos:
        if info.is_dir():
            continue
        path = info.filename.replace("\\", "/")
        parts = path.split("/")
        if path.startswith("/") or any(part in ("", ".", "..") for part in parts):
            raise ValueError("GTFS ZIP에 안전하지 않은 파일 경로가 포함되어 있습니다.")
        if info.flag_bits & 0x1:
            raise ValueError("암호화된 ZIP 파일은 가져올 수 없습니다.")
        total_uncompressed += info.file_size
        if info.file_size > 150 * 1024 * 1024 or total_uncompressed > 250 * 1024 * 1024:
            raise ValueError("압축 해제 용량이 허용 한도(파일 150MB / 전체 250MB)를 초과합니다.")
        if info.compress_size == 0 and info.file_size > 0:
            raise ValueError("비정상 압축 파일이 포함되어 있습니다.")
        if info.compress_size and info.file_size / info.compress_size > 250:
            raise ValueError("압축률이 비정상적으로 높아 안전을 위해 가져오기를 거부했습니다.")
        base = parts[-1].lower()
        if base.endswith(".txt"):
            if base in members:
                raise ValueError(f"GTFS ZIP에 {base} 파일이 중복되어 있습니다.")
            members[base] = info.filename
    return members


def _read_gtfs_table(zf: zipfile.ZipFile, member: str) -> list[dict[str, str]]:
    with zf.open(member) as raw:
        text = raw.read().decode("utf-8-sig", errors="strict")
    return list(csv.DictReader(io.StringIO(text)))


def read_csv_from_zip(zf: zipfile.ZipFile, filename: str) -> list[dict[str, str]]:
    members = _gtfs_members(zf)
    member = members.get(filename.lower())
    return _read_gtfs_table(zf, member) if member else []


def validate_gtfs_bytes(blob: bytes) -> dict[str, Any]:
    """Bounded GTFS Schedule structural validation; not a guarantee of real-world accuracy."""
    try:
        zf = zipfile.ZipFile(io.BytesIO(blob))
        members = _gtfs_members(zf)
        required = {"agency.txt", "stops.txt", "routes.txt", "trips.txt", "stop_times.txt"}
        missing = sorted(required - set(members))
        if missing:
            raise ValueError("필수 GTFS 파일 누락: " + ", ".join(missing))
        if not ({"calendar.txt", "calendar_dates.txt"} & set(members)):
            raise ValueError("calendar.txt 또는 calendar_dates.txt 중 하나 이상이 필요합니다.")
        required_columns = {
            "agency.txt": {"agency_name", "agency_url", "agency_timezone"},
            "stops.txt": {"stop_id", "stop_name", "stop_lat", "stop_lon"},
            "routes.txt": {"route_id", "route_type"},
            "trips.txt": {"route_id", "service_id", "trip_id"},
            "stop_times.txt": {"trip_id", "arrival_time", "departure_time", "stop_id", "stop_sequence"},
        }
        optional_columns = {
            "transfers.txt": {"from_stop_id", "to_stop_id", "transfer_type"},
            "pathways.txt": {"pathway_id", "from_stop_id", "to_stop_id", "pathway_mode", "is_bidirectional"},
            "calendar.txt": {"service_id", "monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday", "start_date", "end_date"},
            "calendar_dates.txt": {"service_id", "date", "exception_type"},
        }
        tables: dict[str, list[dict[str, str]]] = {}
        errors: list[str] = []
        warnings: list[str] = []
        counts: dict[str, int] = {}
        for filename, member in members.items():
            if filename not in required_columns and filename not in optional_columns and filename not in {"shapes.txt", "feed_info.txt"}:
                continue
            rows = _read_gtfs_table(zf, member)
            tables[filename] = rows
            counts[filename] = len(rows)
        for filename, needed in required_columns.items():
            with zf.open(members[filename]) as raw:
                header = next(csv.reader(io.TextIOWrapper(raw, encoding="utf-8-sig")), [])
            absent = sorted(needed - set(header))
            if absent:
                errors.append(f"{filename}: 필수 열 누락 {', '.join(absent)}")
            if not tables.get(filename):
                errors.append(f"{filename}: 데이터 행이 없습니다.")
        for filename in ("calendar.txt", "calendar_dates.txt"):
            if filename in members:
                with zf.open(members[filename]) as raw:
                    header = next(csv.reader(io.TextIOWrapper(raw, encoding="utf-8-sig")), [])
                absent = sorted(optional_columns[filename] - set(header))
                if absent:
                    errors.append(f"{filename}: 필수 열 누락 {', '.join(absent)}")
        agencies=tables.get("agency.txt",[]); stops=tables.get("stops.txt",[]); routes=tables.get("routes.txt",[])
        trips=tables.get("trips.txt",[]); stop_times=tables.get("stop_times.txt",[])
        stop_ids={r.get("stop_id","") for r in stops}; route_ids={r.get("route_id","") for r in routes}; trip_ids={r.get("trip_id","") for r in trips}
        service_ids={r.get("service_id","") for r in tables.get("calendar.txt",[])} | {r.get("service_id","") for r in tables.get("calendar_dates.txt",[])}
        def duplicate_count(values):
            seen=set(); duplicates=0
            for value in values:
                if not value: continue
                if value in seen: duplicates+=1
                seen.add(value)
            return duplicates
        for filename, values in (("stops.txt",[r.get("stop_id","") for r in stops]),
                                 ("routes.txt",[r.get("route_id","") for r in routes]),
                                 ("trips.txt",[r.get("trip_id","") for r in trips])):
            duplicates=duplicate_count(values)
            if duplicates: errors.append(f"{filename}: 중복 기본 ID {duplicates}개")
        bad_coords=0
        for row in stops:
            try:
                lat=float(row.get("stop_lat","")); lon=float(row.get("stop_lon",""))
                if not (math.isfinite(lat) and math.isfinite(lon) and -90<=lat<=90 and -180<=lon<=180): bad_coords+=1
            except Exception: bad_coords+=1
        if bad_coords: errors.append(f"stops.txt: 좌표가 유효하지 않은 정류장 {bad_coords}개")
        bad_route_types=sum(1 for r in routes if not str(r.get("route_type","")).strip().isdigit())
        if bad_route_types: errors.append(f"routes.txt: 숫자가 아닌 route_type {bad_route_types}개")
        missing_route=sum(1 for r in trips if r.get("route_id") not in route_ids)
        missing_service=sum(1 for r in trips if r.get("service_id") not in service_ids)
        if missing_route: errors.append(f"trips.txt: routes.txt에 없는 route_id 참조 {missing_route}개")
        if missing_service: warnings.append(f"trips.txt: calendar/calendar_dates에 없는 service_id 참조 {missing_service}개")
        missing_trip=sum(1 for r in stop_times if r.get("trip_id") not in trip_ids)
        missing_stop=sum(1 for r in stop_times if r.get("stop_id") not in stop_ids)
        if missing_trip: errors.append(f"stop_times.txt: trips.txt에 없는 trip_id 참조 {missing_trip}개")
        if missing_stop: errors.append(f"stop_times.txt: stops.txt에 없는 stop_id 참조 {missing_stop}개")
        bad_times=0; bad_sequences=0; sequence_seen=set()
        for row in stop_times:
            for field in ("arrival_time","departure_time"):
                value=(row.get(field) or "").strip()
                match=re.fullmatch(r"(\d{1,2}):([0-5]\d):([0-5]\d)",value)
                if not match or int(match.group(1))>99: bad_times+=1
            try:
                seq=int(row.get("stop_sequence",""))
                if seq<0: bad_sequences+=1
                key=(row.get("trip_id"),seq)
                if key in sequence_seen: bad_sequences+=1
                sequence_seen.add(key)
            except Exception: bad_sequences+=1
        if bad_times: errors.append(f"stop_times.txt: 시간 형식이 유효하지 않은 값 {bad_times}개")
        if bad_sequences: errors.append(f"stop_times.txt: stop_sequence 누락·중복·음수 {bad_sequences}개")
        stop_by_id = {r.get("stop_id", ""): r for r in stops if r.get("stop_id")}
        route_by_id = {r.get("route_id", ""): r for r in routes if r.get("route_id")}
        trip_by_id = {r.get("trip_id", ""): r for r in trips if r.get("trip_id")}
        # GTFS station hierarchy: station has no parent; platform/entrance/generic nodes
        # point to a station; boarding areas point to a platform.
        bad_parent_type = 0
        for row in stops:
            parent_id = (row.get("parent_station") or "").strip()
            if not parent_id:
                continue
            parent = stop_by_id.get(parent_id)
            if not parent:
                bad_parent_type += 1
                continue
            child_type = _safe_int(row.get("location_type")) or 0
            parent_type = _safe_int(parent.get("location_type")) or 0
            expected_parent_type = 0 if child_type == 4 else 1
            if child_type not in range(0, 5) or parent_type != expected_parent_type or child_type == 1:
                bad_parent_type += 1
        invalid_location_types = sum(1 for row in stops
                                     if (_safe_int(row.get("location_type")) or 0) not in range(0, 5))
        if invalid_location_types:
            errors.append(f"stops.txt: 지원하지 않는 location_type 0~4 외 값 {invalid_location_types}개")
        if bad_parent_type:
            errors.append(f"stops.txt: parent_station 위치 유형 관계가 잘못된 항목 {bad_parent_type}개")

        if "transfers.txt" in members:
            transfer_rows = tables.get("transfers.txt", [])
            allowed_transfer_types = {0, 1, 2, 3, 4, 5}
            bad_transfer_type = 0
            bad_transfer_refs = 0
            bad_transfer_location_types = 0
            bad_min_time = 0
            duplicate_transfer_keys = 0
            seen_transfer_keys = set()
            for row in transfer_rows:
                raw_type = (row.get("transfer_type") or "0").strip()
                if not raw_type.isdigit() or int(raw_type) not in allowed_transfer_types:
                    bad_transfer_type += 1
                    continue
                transfer_type = int(raw_type)
                fs = (row.get("from_stop_id") or "").strip()
                ts = (row.get("to_stop_id") or "").strip()
                ft = (row.get("from_trip_id") or "").strip()
                tt = (row.get("to_trip_id") or "").strip()
                fr = (row.get("from_route_id") or "").strip()
                tr = (row.get("to_route_id") or "").strip()
                if transfer_type in (0, 1, 2, 3) and (not fs or not ts):
                    bad_transfer_refs += 1
                if transfer_type in (4, 5) and (not ft or not tt):
                    bad_transfer_refs += 1
                if fs and fs not in stop_by_id: bad_transfer_refs += 1
                if ts and ts not in stop_by_id: bad_transfer_refs += 1
                if ft and ft not in trip_by_id: bad_transfer_refs += 1
                if tt and tt not in trip_by_id: bad_transfer_refs += 1
                if fr and fr not in route_by_id: bad_transfer_refs += 1
                if tr and tr not in route_by_id: bad_transfer_refs += 1
                if ft and fr and ft in trip_by_id and trip_by_id[ft].get("route_id") != fr: bad_transfer_refs += 1
                if tt and tr and tt in trip_by_id and trip_by_id[tt].get("route_id") != tr: bad_transfer_refs += 1
                if transfer_type in (4, 5):
                    for sid in (fs, ts):
                        if sid and sid in stop_by_id and (_safe_int(stop_by_id[sid].get("location_type")) or 0) != 0:
                            bad_transfer_location_types += 1
                elif transfer_type in (0, 1, 2, 3):
                    for sid in (fs, ts):
                        if sid and sid in stop_by_id and (_safe_int(stop_by_id[sid].get("location_type")) or 0) not in (0, 1):
                            bad_transfer_location_types += 1
                if transfer_type == 2:
                    value = (row.get("min_transfer_time") or "").strip()
                    if not value.isdigit():
                        bad_min_time += 1
                key = (fs, ts, ft, tt, fr, tr)
                if key in seen_transfer_keys: duplicate_transfer_keys += 1
                seen_transfer_keys.add(key)
            if bad_transfer_type: errors.append(f"transfers.txt: 유효하지 않은 transfer_type {bad_transfer_type}개")
            if bad_transfer_refs: errors.append(f"transfers.txt: 정류장·노선·운행편 참조 누락/불일치 {bad_transfer_refs}개")
            if bad_transfer_location_types: errors.append(f"transfers.txt: from/to 위치 유형이 transfer_type 규칙(0~3은 0/1, 4/5는 0)에 맞지 않는 항목 {bad_transfer_location_types}개")
            if bad_min_time: errors.append(f"transfers.txt: transfer_type=2의 min_transfer_time 누락/오류 {bad_min_time}개")
            if duplicate_transfer_keys: errors.append(f"transfers.txt: 중복 환승 규칙 {duplicate_transfer_keys}개")
        if "pathways.txt" in members:
            pathway_rows = tables.get("pathways.txt", [])
            missing_from = sum(1 for r in pathway_rows if r.get("from_stop_id") not in stop_ids)
            missing_to = sum(1 for r in pathway_rows if r.get("to_stop_id") not in stop_ids)
            bad_mode = sum(1 for r in pathway_rows if not str(r.get("pathway_mode", "")).isdigit() or int(r.get("pathway_mode") or 0) not in range(1, 8))
            bad_direction = sum(1 for r in pathway_rows if str(r.get("is_bidirectional", "0")).strip() not in ("0", "1"))
            bad_measure = 0
            for r in pathway_rows:
                mode_value = _safe_int(r.get("pathway_mode")) or 0
                direction_value = str(r.get("is_bidirectional", "")).strip()
                if mode_value == 7 and direction_value == "1":
                    bad_measure += 1
                if direction_value not in ("0", "1"):
                    bad_measure += 1
                for field in ("length", "traversal_time"):
                    val = (r.get(field) or "").strip()
                    if not val: continue
                    try:
                        number = float(val)
                        if not math.isfinite(number) or number < 0 or (field == "traversal_time" and (not number.is_integer() or number <= 0)):
                            bad_measure += 1
                    except Exception:
                        bad_measure += 1
                for field in ("from_stop_id", "to_stop_id"):
                    sid = r.get(field, "")
                    if sid in stop_by_id:
                        stop_type = _safe_int(stop_by_id[sid].get("location_type")) or 0
                        if stop_type == 1 or str(stop_by_id[sid].get("stop_access", "")).strip() == "1":
                            bad_measure += 1
            if missing_from or missing_to: errors.append(f"pathways.txt: 존재하지 않는 정류장 참조 from={missing_from}, to={missing_to}")
            if bad_mode: errors.append(f"pathways.txt: pathway_mode 1~7이 아닌 항목 {bad_mode}개")
            if bad_direction: errors.append(f"pathways.txt: is_bidirectional은 0 또는 1이어야 하는 항목 {bad_direction}개")
            if bad_measure: errors.append(f"pathways.txt: 길이·소요시간·노드유형 오류 {bad_measure}개")
        known_route_types={0,1,2,3,4,5,6,7}
        unknown_types=sorted({str(r.get("route_type","")) for r in routes if str(r.get("route_type","" )).isdigit() and int(r.get("route_type")) not in known_route_types})
        if unknown_types: warnings.append("표준 기본 route_type 외 확장 유형이 포함되어 있습니다: "+", ".join(unknown_types[:12]))
        if not agencies: warnings.append("agency.txt에 기관 데이터가 없습니다.")
        feed_info=tables.get("feed_info.txt",[])
        if not feed_info: warnings.append("feed_info.txt가 없어 데이터 게시자·버전 메타데이터가 부족합니다.")
        if "frequencies.txt" in members:
            warnings.append("frequencies.txt가 포함되어 있습니다. 현재 경로 엔진은 배차간격 기반 운행을 지원하지 않습니다.")
        if any(name in members for name in ("locations.geojson","booking_rules.txt","stop_areas.txt","location_groups.txt")):
            warnings.append("GTFS Flex/수요응답 관련 파일이 포함되어 있습니다. 현재 B-ROUTE 경로 엔진은 해당 기능을 처리하지 않습니다.")
        zones={str(a.get("agency_timezone","")) for a in agencies if a.get("agency_timezone")}
        if zones and zones!={"Asia/Seoul"}:
            warnings.append("Asia/Seoul 이외의 agency_timezone이 포함되어 있습니다. 현재 경로 계산은 한국 시간대 기준이므로 별도 검증이 필요합니다.")
        if len(stop_times)>2_000_000: warnings.append("stop_times가 200만 행을 초과합니다. 대용량 COS staging/배치 가져오기가 권장됩니다.")
        uncompressed_bytes=sum(i.file_size for i in zf.infolist())
        import_blockers=[]
        if uncompressed_bytes>30*1024*1024: import_blockers.append("압축 해제 용량이 30MB를 초과하여 서버리스 함수에서 직접 가져오기에 부적합합니다.")
        if len(stop_times)>200_000: import_blockers.append("stop_times.txt가 20만 행을 초과하여 COS staging/배치 가져오기가 필요합니다.")
        if "frequencies.txt" in members: import_blockers.append("frequencies.txt의 배차간격 기반 운행을 현재 엔진이 처리하지 못합니다. 지원 importer 추가 전에는 활성화할 수 없습니다.")
        if any(name in members for name in ("locations.geojson","booking_rules.txt","stop_areas.txt","location_groups.txt")):
            import_blockers.append("GTFS Flex 데이터는 현재 엔진에서 지원하지 않아 활성화할 수 없습니다.")
        direct_import_ready=(not errors and not import_blockers)
        return {"valid":not errors,"direct_import_ready":direct_import_ready,"import_blockers":import_blockers,
                "sha256":hashlib.sha256(blob).hexdigest(),"file_size":len(blob),
                "total_uncompressed_bytes":uncompressed_bytes,"counts":counts,
                "errors":errors,"warnings":warnings,"agency_name":(agencies[0].get("agency_name","") if agencies else ""),
                "feed_info":(feed_info[0] if feed_info else {}),"route_types":sorted({str(r.get("route_type","")) for r in routes}),
                "coverage_note":"GTFS 구조 검증 결과이며 실제 노선 운행·전국 커버리지·시간표 현장 정확성을 보증하지 않습니다."}
    except zipfile.BadZipFile as exc:
        raise ValueError("올바른 GTFS ZIP 파일이 아닙니다.") from exc
    except UnicodeDecodeError as exc:
        raise ValueError("GTFS 텍스트 파일은 UTF-8 또는 UTF-8 BOM 인코딩이어야 합니다.") from exc

def import_gtfs_bytes(blob: bytes, name: str, source_id: str | None = None, source_version: str = "", effective_date: str = "", actor: dict[str, Any] | None = None) -> dict[str, Any]:
    try:
        validation = validate_gtfs_bytes(blob)
        if not validation["valid"]:
            raise ValueError("GTFS 사전검증 실패: " + " / ".join(validation["errors"][:5]))
        if not validation["direct_import_ready"]:
            raise ValueError("이 데이터는 대용량 배치 가져오기가 필요합니다: " + " / ".join(validation["import_blockers"]))
        zf = zipfile.ZipFile(io.BytesIO(blob))
        feed_id = uuid.uuid4().hex[:12]
        agencies = read_csv_from_zip(zf, "agency.txt")
        stops = read_csv_from_zip(zf, "stops.txt")
        routes = read_csv_from_zip(zf, "routes.txt")
        trips = read_csv_from_zip(zf, "trips.txt")
        stop_times = read_csv_from_zip(zf, "stop_times.txt")
        calendars = read_csv_from_zip(zf, "calendar.txt")
        exceptions = read_csv_from_zip(zf, "calendar_dates.txt")
        shapes = read_csv_from_zip(zf, "shapes.txt")
        transfers = read_csv_from_zip(zf, "transfers.txt")
        pathways = read_csv_from_zip(zf, "pathways.txt")
        agency_name = (agencies[0].get("agency_name", "") if agencies else "")
        now = datetime.now(TZ).isoformat()
        source_meta = {"source_url":"", "license_name":""}
        if source_id:
            with closing(db()) as check_con:
                source_row=check_con.execute("SELECT source_url,license_name,active,dataset_type FROM data_sources WHERE source_id=?",(source_id,)).fetchone()
                if not source_row or not source_row[2] or source_row[3] != "gtfs_static":
                    raise ValueError("활성 상태의 GTFS 정적 데이터 출처를 선택해야 합니다.")
                source_meta={"source_url":source_row[0],"license_name":source_row[1]}
        with closing(db()) as con:
            con.execute("INSERT INTO feeds(feed_id,name,agency,imported_at,stop_count,route_count,trip_count,source_id,source_version,effective_date,license_name,source_url,sha256,is_active) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,1)",
                        (feed_id, name, agency_name, now, len(stops), len(routes), len(trips), source_id, source_version[:80], effective_date[:10], source_meta["license_name"], source_meta["source_url"], validation["sha256"]))
            con.executemany("INSERT INTO stops(feed_id,stop_id,name,lat,lon,parent_station,location_type,wheelchair_boarding,platform_code) VALUES(?,?,?,?,?,?,?,?,?) ON CONFLICT(feed_id,stop_id) DO UPDATE SET name=excluded.name,lat=excluded.lat,lon=excluded.lon,parent_station=excluded.parent_station,location_type=excluded.location_type,wheelchair_boarding=excluded.wheelchair_boarding,platform_code=excluded.platform_code", [(feed_id, x.get("stop_id", ""), x.get("stop_name", "정류장"), float(x.get("stop_lat") or 0), float(x.get("stop_lon") or 0), x.get("parent_station", ""), int(x.get("location_type") or 0), int(x.get("wheelchair_boarding") or 0), x.get("platform_code", "")) for x in stops if x.get("stop_id") and x.get("stop_lat") and x.get("stop_lon")])
            con.executemany("INSERT INTO routes VALUES(?,?,?,?,?,?) ON CONFLICT(feed_id,route_id) DO UPDATE SET short_name=excluded.short_name,long_name=excluded.long_name,route_type=excluded.route_type,color=excluded.color", [(feed_id, x.get("route_id", ""), x.get("route_short_name", ""), x.get("route_long_name", ""), int(x.get("route_type") or 3), x.get("route_color", "")) for x in routes if x.get("route_id")])
            con.executemany("INSERT INTO trips VALUES(?,?,?,?,?,?,?) ON CONFLICT(feed_id,trip_id) DO UPDATE SET route_id=excluded.route_id,service_id=excluded.service_id,headsign=excluded.headsign,direction_id=excluded.direction_id,shape_id=excluded.shape_id", [(feed_id, x.get("trip_id", ""), x.get("route_id", ""), x.get("service_id", ""), x.get("trip_headsign", ""), x.get("direction_id", ""), x.get("shape_id", "")) for x in trips if x.get("trip_id")])
            con.executemany("INSERT INTO shapes VALUES(?,?,?,?,?) ON CONFLICT(feed_id,shape_id,sequence) DO UPDATE SET lat=excluded.lat,lon=excluded.lon", [(feed_id, x.get("shape_id", ""), int(x.get("shape_pt_sequence") or 0), float(x.get("shape_pt_lat") or 0), float(x.get("shape_pt_lon") or 0)) for x in shapes if x.get("shape_id") and x.get("shape_pt_lat") and x.get("shape_pt_lon")])
            con.executemany("INSERT INTO stop_times VALUES(?,?,?,?,?,?) ON CONFLICT(feed_id,trip_id,stop_sequence) DO UPDATE SET stop_id=excluded.stop_id,arrival_secs=excluded.arrival_secs,departure_secs=excluded.departure_secs", [(feed_id, x.get("trip_id", ""), x.get("stop_id", ""), int(x.get("stop_sequence") or 0), gtfs_time(x.get("arrival_time", "00:00:00")), gtfs_time(x.get("departure_time", x.get("arrival_time", "00:00:00")))) for x in stop_times if x.get("trip_id") and x.get("stop_id")])
            con.executemany("INSERT INTO calendars VALUES(?,?,?,?,?,?,?,?,?,?,?) ON CONFLICT(feed_id,service_id) DO UPDATE SET monday=excluded.monday,tuesday=excluded.tuesday,wednesday=excluded.wednesday,thursday=excluded.thursday,friday=excluded.friday,saturday=excluded.saturday,sunday=excluded.sunday,start_date=excluded.start_date,end_date=excluded.end_date", [(feed_id, x.get("service_id", ""), *[int(x.get(k) or 0) for k in ("monday","tuesday","wednesday","thursday","friday","saturday","sunday")], x.get("start_date", ""), x.get("end_date", "")) for x in calendars if x.get("service_id")])
            con.executemany("INSERT INTO calendar_dates VALUES(?,?,?,?) ON CONFLICT(feed_id,service_id,service_date) DO UPDATE SET exception_type=excluded.exception_type", [(feed_id, x.get("service_id", ""), x.get("date", ""), int(x.get("exception_type") or 0)) for x in exceptions if x.get("service_id") and x.get("date")])
            for x in transfers:
                tid = hashlib.sha256(json.dumps([feed_id,x.get("from_stop_id"),x.get("to_stop_id"),x.get("from_trip_id"),x.get("to_trip_id"),x.get("from_route_id"),x.get("to_route_id"),x.get("transfer_type")], ensure_ascii=False).encode()).hexdigest()
                con.execute("INSERT INTO gtfs_transfers(transfer_row_id,feed_id,from_stop_id,to_stop_id,from_trip_id,to_trip_id,from_route_id,to_route_id,transfer_type,min_transfer_time) VALUES(?,?,?,?,?,?,?,?,?,?) ON CONFLICT(transfer_row_id) DO UPDATE SET min_transfer_time=excluded.min_transfer_time", (tid,feed_id,x.get("from_stop_id",""),x.get("to_stop_id",""),x.get("from_trip_id",""),x.get("to_trip_id",""),x.get("from_route_id",""),x.get("to_route_id",""),int(x.get("transfer_type") or 0),int(x.get("min_transfer_time") or 0) if x.get("min_transfer_time") else None))
            con.executemany("INSERT INTO gtfs_pathways(feed_id,pathway_id,from_stop_id,to_stop_id,pathway_mode,is_bidirectional,length_m,traversal_time) VALUES(?,?,?,?,?,?,?,?) ON CONFLICT(feed_id,pathway_id) DO UPDATE SET from_stop_id=excluded.from_stop_id,to_stop_id=excluded.to_stop_id,pathway_mode=excluded.pathway_mode,is_bidirectional=excluded.is_bidirectional,length_m=excluded.length_m,traversal_time=excluded.traversal_time", [(feed_id,x.get("pathway_id",""),x.get("from_stop_id",""),x.get("to_stop_id",""),int(x.get("pathway_mode") or 1),int(x.get("is_bidirectional") or 0),_safe_float(x.get("length")),int(x.get("traversal_time") or 0) if x.get("traversal_time") else None) for x in pathways if x.get("pathway_id")])
            if source_id:
                con.execute("UPDATE feeds SET is_active=0 WHERE source_id=? AND feed_id<>?",(source_id,feed_id))
                con.execute("UPDATE data_releases SET status='archived' WHERE source_id=? AND status='active'",(source_id,))
            release_id=uuid.uuid4().hex
            created_by=str((actor or {}).get("email","owner-import"))
            con.execute("INSERT INTO data_releases(release_id,dataset,version,source,effective_date,notes,status,created_by,created_at,feed_id,source_id,checksum,validation_json,activated_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (release_id,source_id or "gtfs",source_version or now[:10],source_meta["source_url"] or name,effective_date[:10],"GTFS validation passed", "active", created_by, now, feed_id, source_id, validation["sha256"],json.dumps(validation,ensure_ascii=False),now))
            import_job=con.execute("SELECT job_id FROM data_import_jobs WHERE sha256=? AND status='validated' ORDER BY created_at DESC LIMIT 1",(validation["sha256"],)).fetchone()
            if import_job:
                con.execute("UPDATE data_import_jobs SET status='imported',imported_feed_id=?,source_id=COALESCE(source_id,?) WHERE job_id=?",(feed_id,source_id,import_job[0]))
            else:
                con.execute("INSERT INTO data_import_jobs(job_id,source_id,file_name,file_size,sha256,status,validation_json,created_by,created_at,imported_feed_id) VALUES(?,?,?,?,?,?,?,?,?,?)",
                    (uuid.uuid4().hex,source_id,safe_filename(name),len(blob),validation["sha256"],"imported",json.dumps(validation,ensure_ascii=False),created_by,now,feed_id))
            _audit(con,actor or {"sub":"owner-import","email":created_by},"gtfs.import","feed",feed_id,None,{"release_id":release_id,"sha256":validation["sha256"]},"GTFS 검증 후 가져오기")
            con.commit()
        return {"feed_id": feed_id, "release_id":release_id, "sha256":validation["sha256"], "validation":validation,
                "name": name, "agency": agency_name, "stops": len(stops), "routes": len(routes), "trips": len(trips), "stop_times": len(stop_times), "shape_points": len(shapes)}
    except zipfile.BadZipFile as exc:
        raise ValueError("올바른 GTFS ZIP 파일이 아닙니다.") from exc


@app.post("/admin/gtfs/validate")
async def validate_gtfs_upload(request: Request, file: UploadFile = File(...), source_id: str = Form(...), x_admin_token: str | None = Header(default=None)):
    if not _admin_authorized(request, x_admin_token):
        raise HTTPException(403, "총괄자 권한이 필요합니다.")
    require_durable_database()
    with closing(db()) as con:
        source_row=con.execute("SELECT active,dataset_type FROM data_sources WHERE source_id=?",(source_id,)).fetchone()
    if not source_row or not source_row[0] or source_row[1]!="gtfs_static":
        raise HTTPException(400,"활성 상태의 GTFS 정적 데이터 출처를 먼저 등록하고 선택해 주세요.")
    blob = await file.read(5 * 1024 * 1024 + 1)
    if len(blob) > 5 * 1024 * 1024:
        raise HTTPException(413, "현재 사전검증 업로드는 5MB 이하입니다. 대용량 COS staging은 다음 단계에서 연결합니다.")
    try:
        report=validate_gtfs_bytes(blob)
    except Exception as exc:
        raise HTTPException(400,str(exc)) from exc
    actor=_read_session(request) or {"email":"admin-token"}
    job_id=uuid.uuid4().hex
    with closing(db()) as con:
        con.execute("INSERT INTO data_import_jobs(job_id,source_id,file_name,file_size,sha256,status,validation_json,created_by,created_at,error_message) VALUES(?,?,?,?,?,?,?,?,?,?)",
            (job_id,source_id,safe_filename(file.filename or "feed.zip"),len(blob),report["sha256"],("validated" if report["direct_import_ready"] else "requires_staging") if report["valid"] else "rejected",json.dumps(report,ensure_ascii=False),str(actor.get("email","admin-token")),datetime.now(TZ).isoformat(),"" if report["valid"] else " / ".join(report["errors"][:5])))
        con.commit()
    return {"job_id":job_id,"status":("validated" if report["direct_import_ready"] else "requires_staging") if report["valid"] else "rejected","report":report}


@app.post("/admin/gtfs/import")
async def upload_gtfs(request: Request, file: UploadFile = File(...), source_id: str = Form(...), source_version: str = Form(default=""), effective_date: str = Form(default=""), x_admin_token: str | None = Header(default=None)):
    if not _admin_authorized(request, x_admin_token):
        raise HTTPException(403, "총괄자 권한이 필요합니다.")
    require_durable_database()
    blob = await file.read(5 * 1024 * 1024 + 1)
    if len(blob) > 5 * 1024 * 1024:
        raise HTTPException(413, "현재 직접 가져오기는 5MB 이하입니다. 대용량 COS staging 및 배치 가져오기는 후속 단계입니다.")
    if effective_date:
        try:
            datetime.strptime(effective_date,"%Y-%m-%d")
        except ValueError:
            raise HTTPException(400,"effective_date는 실제 날짜의 YYYY-MM-DD 형식이어야 합니다.")
    try:
        preflight=validate_gtfs_bytes(blob)
        if not preflight["valid"]:
            raise ValueError("GTFS 사전검증 실패: " + " / ".join(preflight["errors"][:5]))
        if not preflight["direct_import_ready"]:
            raise HTTPException(413,"대용량 데이터셋은 COS staging/배치 가져오기가 필요합니다: " + " / ".join(preflight["import_blockers"]))
        actor=_read_session(request) or {"sub":"admin-token","email":"admin-token"}
        result=import_gtfs_bytes(blob,file.filename or "GTFS feed",source_id,source_version,effective_date,actor)
        return result
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(400, str(exc)) from exc


def _safe_gtfs_filename(name: str) -> str:
    from pathlib import PurePosixPath
    raw = PurePosixPath((name or "feed.zip").replace("\\", "/")).name
    raw = re.sub(r"[^0-9A-Za-z가-힣._ -]", "_", raw).strip(" .")[:160]
    if not raw.lower().endswith(".zip"):
        raw = (raw.rsplit(".", 1)[0] if "." in raw else raw) + ".zip"
    return raw or "feed.zip"


def _cos_list_all_parts(client, bucket: str, key: str, upload_id: str) -> list[dict[str, Any]]:
    parts: list[dict[str, Any]] = []
    marker = 0
    while True:
        result = client.list_parts(Bucket=bucket, Key=key, UploadId=upload_id,
                                   PartNumberMarker=marker)
        current = result.get("Part", []) or []
        if isinstance(current, dict):
            current = [current]
        parts.extend(current)
        truncated = str(result.get("IsTruncated", "false")).lower() in ("true", "1")
        if not truncated:
            break
        marker = int(result.get("NextPartNumberMarker", 0) or 0)
        if marker <= 0 or len(parts) > 10000:
            raise RuntimeError("COS 분할 업로드 목록을 안전하게 읽지 못했습니다.")
    return parts


@app.post("/admin/gtfs/staging/init")
async def init_gtfs_staging(body: GtfsStagingInit, request: Request):
    _require_same_origin(request)
    actor = _admin_session(request)
    require_durable_database()
    if not cos_is_configured():
        raise HTTPException(503, "총괄자가 COS 서버 Secret을 설정해야 대용량 GTFS 업로드를 사용할 수 있습니다.")
    if body.file_size > GTFS_STAGING_MAX_BYTES:
        raise HTTPException(413, f"대용량 GTFS 업로드 최대 크기는 {GTFS_STAGING_MAX_BYTES // (1024*1024)}MB입니다.")
    part_count = math.ceil(body.file_size / GTFS_STAGING_PART_SIZE)
    if part_count > 10000:
        raise HTTPException(413, "COS 분할 업로드 조각 수가 10,000개를 초과합니다. GTFS_STAGING_PART_SIZE_MB를 높이거나 파일을 분리해 주세요.")
    if body.effective_date:
        try:
            datetime.strptime(body.effective_date, "%Y-%m-%d")
        except ValueError:
            raise HTTPException(400, "적용 기준일은 YYYY-MM-DD 형식이어야 합니다.")
    file_name = _safe_gtfs_filename(body.file_name)
    with closing(db()) as con:
        source = con.execute("SELECT name,active,dataset_type FROM data_sources WHERE source_id=?", (body.source_id,)).fetchone()
        if not source or not source[1] or source[2] != "gtfs_static":
            raise HTTPException(400, "활성 상태의 GTFS 정적 데이터 출처를 선택해 주세요.")
    job_id = uuid.uuid4().hex
    owner_prefix = hashlib.sha256(str(actor["sub"]).encode("utf-8")).hexdigest()[:20]
    object_key = f"gtfs-staging/{owner_prefix}/{job_id}/{file_name}"
    client = cos_client()
    created = {}
    try:
        created = client.create_multipart_upload(Bucket=os.environ["COS_BUCKET"].strip(), Key=object_key,
            ContentType="application/zip", Metadata={"broute-job-id": job_id, "broute-source-id": body.source_id})
        cos_upload_id = str(created["UploadId"])
        now = datetime.now(TZ).isoformat()
        with closing(db()) as con:
            con.execute("INSERT INTO gtfs_staging_uploads(job_id,source_id,file_name,expected_size,object_key,cos_upload_id,source_version,effective_date,expected_sha256,status,progress_percent,progress_phase,created_by,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (job_id, body.source_id, file_name, body.file_size, object_key, cos_upload_id,
                 body.source_version, body.effective_date, body.sha256.lower(), "uploading", 0, "uploading",
                 str(actor.get("email", "owner")), now, now))
            _audit(con, actor, "gtfs.staging.create", "gtfs_staging", job_id, None,
                   {"source_id": body.source_id, "file_name": file_name, "file_size": body.file_size}, "대용량 GTFS COS 업로드 시작")
            con.commit()
    except Exception as exc:
        try:
            client.abort_multipart_upload(Bucket=os.environ["COS_BUCKET"].strip(), Key=object_key, UploadId=str(created.get("UploadId", "")))
        except Exception:
            pass
        if isinstance(exc, HTTPException):
            raise
        raise HTTPException(502, "COS 분할 업로드를 시작하지 못했습니다.") from exc
    part_size = GTFS_STAGING_PART_SIZE
    return {"ok": True, "job_id": job_id, "file_name": file_name,
            "file_size": body.file_size, "part_size": part_size,
            "part_count": math.ceil(body.file_size / part_size),
            "url_ttl_seconds": GTFS_STAGING_URL_TTL,
            "message": "브라우저가 COS에 파일을 직접 업로드합니다. API 서버에는 ZIP 본문이 전달되지 않습니다."}


@app.post("/admin/gtfs/staging/sign-parts")
async def sign_gtfs_staging_parts(body: GtfsStagingSignParts, request: Request):
    _require_same_origin(request)
    actor = _admin_session(request)
    require_durable_database()
    with closing(db()) as con:
        row = con.execute("SELECT object_key,cos_upload_id,expected_size,status,created_by FROM gtfs_staging_uploads WHERE job_id=?", (body.job_id,)).fetchone()
    if not row or row[4] != str(actor.get("email", "")):
        raise HTTPException(404, "업로드 작업을 찾을 수 없습니다.")
    if row[3] != "uploading":
        raise HTTPException(409, "현재 분할 업로드 상태에서는 URL을 발급할 수 없습니다.")
    part_size = GTFS_STAGING_PART_SIZE
    part_count = math.ceil(int(row[2]) / part_size)
    if len(set(body.part_numbers)) != len(body.part_numbers) or any(n < 1 or n > part_count for n in body.part_numbers):
        raise HTTPException(400, "요청한 분할 번호가 올바르지 않습니다.")
    client = cos_client()
    bucket = os.environ["COS_BUCKET"].strip()
    urls = []
    try:
        for number in body.part_numbers:
            params = {"partNumber": str(number), "uploadId": str(row[1])}
            url = client.get_presigned_url(Bucket=bucket, Key=row[0], Method="PUT",
                                           Expired=GTFS_STAGING_URL_TTL, Params=params)
            urls.append({"part_number": number, "url": url})
    except Exception as exc:
        raise HTTPException(502, "COS 분할 업로드 URL 발급에 실패했습니다.") from exc
    return {"job_id": body.job_id, "urls": urls, "expires_in_seconds": GTFS_STAGING_URL_TTL,
            "required_headers": {}}


@app.post("/admin/gtfs/staging/{job_id}/complete")
async def complete_gtfs_staging(job_id: str, request: Request):
    _require_same_origin(request)
    actor = _admin_session(request)
    require_durable_database()
    with closing(db()) as con:
        row = con.execute("SELECT source_id,file_name,expected_size,object_key,cos_upload_id,status,created_by FROM gtfs_staging_uploads WHERE job_id=?", (job_id,)).fetchone()
    if not row or row[6] != str(actor.get("email", "")):
        raise HTTPException(404, "업로드 작업을 찾을 수 없습니다.")
    if row[5] != "uploading":
        raise HTTPException(409, "이미 완료되었거나 업로드 중이 아닌 작업입니다.")
    part_size = GTFS_STAGING_PART_SIZE
    expected_count = math.ceil(int(row[2]) / part_size)
    try:
        client = cos_client()
        bucket = os.environ["COS_BUCKET"].strip()
        parts = _cos_list_all_parts(client, bucket, row[3], row[4])
        parts = sorted(parts, key=lambda x: int(x.get("PartNumber", 0)))
        if len(parts) != expected_count or [int(p.get("PartNumber", 0)) for p in parts] != list(range(1, expected_count + 1)):
            raise HTTPException(400, f"업로드된 조각이 완전하지 않습니다. {len(parts)}/{expected_count}개")
        actual_sizes = [int(p.get("Size", 0)) for p in parts]
        expected_sizes = [part_size] * (expected_count - 1) + [int(row[2]) - part_size * (expected_count - 1)]
        if actual_sizes != expected_sizes:
            raise HTTPException(400, "업로드된 조각의 크기가 원본 파일 크기와 일치하지 않습니다.")
        client.complete_multipart_upload(Bucket=bucket, Key=row[3], UploadId=row[4],
                                         MultipartUpload={"Part": [{"PartNumber": int(p["PartNumber"]), "ETag": p["ETag"]} for p in parts]})
        now = datetime.now(TZ).isoformat()
        with closing(db()) as con:
            con.execute("UPDATE gtfs_staging_uploads SET status='queued',progress_percent=0,progress_phase='queued',updated_at=? WHERE job_id=? AND status='uploading'", (now, job_id))
            _audit(con, actor, "gtfs.staging.queued", "gtfs_staging", job_id,
                   {"status": "uploading"}, {"status": "queued", "parts": expected_count}, "COS 업로드 완료 및 가져오기 대기열 등록")
            con.commit()
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(502, "COS 업로드 완료 처리에 실패했습니다. 업로드 상태를 확인해 주세요.") from exc
    return {"ok": True, "job_id": job_id, "status": "queued", "part_count": expected_count,
            "message": "대용량 GTFS 파일이 COS에 저장되었습니다. GTFS worker가 배치 가져오기를 수행합니다."}


@app.get("/admin/gtfs/staging/jobs")
async def list_gtfs_staging_jobs(request: Request, limit: int = Query(default=50, ge=1, le=200)):
    _admin_session(request)
    require_durable_database()
    with closing(db()) as con:
        rows = con.execute("SELECT job_id,source_id,file_name,expected_size,status,progress_percent,progress_phase,processed_rows,created_by,created_at,updated_at,completed_at,feed_id,release_id,error_message,actual_sha256 FROM gtfs_staging_uploads ORDER BY created_at DESC LIMIT ?", (limit,)).fetchall()
    with closing(db()) as con:
        worker = con.execute("SELECT worker_id,status,last_seen,last_error FROM gtfs_worker_heartbeats ORDER BY last_seen DESC LIMIT 1").fetchone()
    worker_info = None if not worker else {"worker_id": worker[0], "status": worker[1], "last_seen": worker[2], "last_error": worker[3]}
    return {"worker": worker_info, "jobs": [{"job_id": r[0], "source_id": r[1], "file_name": r[2], "file_size": r[3], "status": r[4],
        "progress_percent": r[5], "progress_phase": r[6], "processed_rows": r[7], "created_by": r[8],
        "created_at": r[9], "updated_at": r[10], "completed_at": r[11], "feed_id": r[12],
        "release_id": r[13], "error_message": r[14], "sha256": r[15]} for r in rows]}


@app.post("/admin/gtfs/staging/{job_id}/retry")
async def retry_gtfs_staging(job_id: str, request: Request):
    _require_same_origin(request)
    actor = _admin_session(request)
    require_durable_database()
    now = datetime.now(TZ).isoformat()
    with closing(db()) as con:
        row = con.execute("SELECT status,created_by FROM gtfs_staging_uploads WHERE job_id=?", (job_id,)).fetchone()
        if not row or row[1] != str(actor.get("email", "")):
            raise HTTPException(404, "작업을 찾을 수 없습니다.")
        if row[0] != "failed":
            raise HTTPException(409, "실패한 작업만 다시 대기열에 등록할 수 있습니다.")
        con.execute("UPDATE gtfs_staging_uploads SET status='queued',progress_percent=0,progress_phase='queued',processed_rows=0,error_message='',updated_at=? WHERE job_id=?", (now, job_id))
        _audit(con, actor, "gtfs.staging.retry", "gtfs_staging", job_id, {"status": "failed"}, {"status": "queued"}, "GTFS 배치 가져오기 재시도")
        con.commit()
    return {"ok": True, "job_id": job_id, "status": "queued"}


@app.delete("/admin/gtfs/staging/{job_id}")
async def cancel_gtfs_staging(job_id: str, request: Request):
    _require_same_origin(request)
    actor = _admin_session(request)
    require_durable_database()
    with closing(db()) as con:
        row = con.execute("SELECT object_key,cos_upload_id,status,created_by FROM gtfs_staging_uploads WHERE job_id=?", (job_id,)).fetchone()
    if not row or row[3] != str(actor.get("email", "")):
        raise HTTPException(404, "작업을 찾을 수 없습니다.")
    if row[2] not in ("uploading", "queued", "failed"):
        raise HTTPException(409, "현재 작업 상태에서는 취소할 수 없습니다.")
    try:
        client = cos_client()
        bucket = os.environ["COS_BUCKET"].strip()
        if row[2] == "uploading":
            client.abort_multipart_upload(Bucket=bucket, Key=row[0], UploadId=row[1])
        else:
            client.delete_object(Bucket=bucket, Key=row[0])
    except Exception as exc:
        raise HTTPException(502, "COS 객체 정리 실패로 작업을 취소하지 못했습니다.") from exc
    now = datetime.now(TZ).isoformat()
    with closing(db()) as con:
        con.execute("UPDATE gtfs_staging_uploads SET status='cancelled',progress_phase='cancelled',updated_at=? WHERE job_id=?", (now, job_id))
        _audit(con, actor, "gtfs.staging.cancel", "gtfs_staging", job_id, {"status": row[2]}, {"status": "cancelled"}, "대용량 GTFS 작업 취소")
        con.commit()
    return {"ok": True, "job_id": job_id, "status": "cancelled"}


@app.get("/admin/data/sources")
async def list_data_sources(request: Request):
    _admin_session(request); require_durable_database()
    with closing(db()) as con:
        rows=con.execute("SELECT source_id,name,provider,dataset_type,transport_modes_json,country,region,source_url,license_name,update_frequency,notes,active,created_at,updated_at FROM data_sources ORDER BY created_at DESC").fetchall()
    return {"sources":[{"source_id":r[0],"name":r[1],"provider":r[2],"dataset_type":r[3],"transport_modes":json.loads(r[4] or "[]"),"country":r[5],"region":r[6],"source_url":r[7],"license_name":r[8],"update_frequency":r[9],"notes":r[10],"active":bool(r[11]),"created_at":r[12],"updated_at":r[13]} for r in rows]}


@app.post("/admin/data/sources")
async def create_data_source(body: DataSourceCreate, request: Request):
    _require_same_origin(request); actor=_admin_session(request); require_durable_database()
    source_id="src_"+uuid.uuid4().hex[:16]; now=datetime.now(TZ).isoformat()
    with closing(db()) as con:
        con.execute("INSERT INTO data_sources(source_id,name,provider,dataset_type,transport_modes_json,country,region,source_url,license_name,update_frequency,notes,active,created_by,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (source_id,body.name,body.provider,body.dataset_type,json.dumps(body.transport_modes),body.country.upper(),body.region,body.source_url,body.license_name,body.update_frequency,body.notes,1,str(actor["sub"]),now,now))
        _audit(con,actor,"data_source.create","data_source",source_id,None,body.model_dump(),"교통 데이터 출처 등록")
        con.commit()
    return {"ok":True,"source_id":source_id}


@app.patch("/admin/data/sources/{source_id}")
async def patch_data_source(source_id: str, body: DataSourcePatch, request: Request):
    _require_same_origin(request); actor=_admin_session(request); require_durable_database()
    with closing(db()) as con:
        row=con.execute("SELECT active,name,provider FROM data_sources WHERE source_id=?",(source_id,)).fetchone()
        if not row: raise HTTPException(404,"데이터 출처를 찾을 수 없습니다.")
        before={"active":bool(row[0])}; after={"active":body.active}
        con.execute("UPDATE data_sources SET active=?,updated_at=? WHERE source_id=?",(1 if body.active else 0,datetime.now(TZ).isoformat(),source_id))
        _audit(con,actor,"data_source.update","data_source",source_id,before,after,body.reason); con.commit()
    return {"ok":True,"source_id":source_id,"active":body.active}


@app.get("/admin/data/releases")
async def list_data_releases(request: Request, limit: int = Query(default=100,ge=1,le=300)):
    _admin_session(request); require_durable_database()
    with closing(db()) as con:
        rows=con.execute("SELECT release_id,dataset,version,source,effective_date,notes,status,created_by,created_at,feed_id,source_id,checksum,activated_at FROM data_releases ORDER BY created_at DESC LIMIT ?",(limit,)).fetchall()
    return {"releases":[{"release_id":r[0],"dataset":r[1],"version":r[2],"source":r[3],"effective_date":r[4],"notes":r[5],"status":r[6],"created_by":r[7],"created_at":r[8],"feed_id":r[9],"source_id":r[10],"checksum":r[11],"activated_at":r[12]} for r in rows]}


@app.post("/admin/data/releases/{release_id}/activate")
async def activate_data_release(release_id: str, request: Request):
    _require_same_origin(request); actor=_admin_session(request); require_durable_database()
    with closing(db()) as con:
        row=con.execute("SELECT feed_id,source_id,status FROM data_releases WHERE release_id=?",(release_id,)).fetchone()
        if not row or not row[0]: raise HTTPException(404,"복구할 데이터 릴리스를 찾을 수 없습니다.")
        feed=con.execute("SELECT feed_id FROM feeds WHERE feed_id=?",(row[0],)).fetchone()
        if not feed: raise HTTPException(409,"해당 릴리스의 교통 데이터가 존재하지 않습니다.")
        if row[1]: con.execute("UPDATE feeds SET is_active=0 WHERE source_id=?",(row[1],))
        con.execute("UPDATE feeds SET is_active=1 WHERE feed_id=?",(row[0],))
        if row[1]: con.execute("UPDATE data_releases SET status='archived' WHERE source_id=? AND status='active'",(row[1],))
        con.execute("UPDATE data_releases SET status='active',activated_at=? WHERE release_id=?",(datetime.now(TZ).isoformat(),release_id))
        _audit(con,actor,"data_release.activate","data_release",release_id,{"status":row[2]},{"status":"active","feed_id":row[0]},"교통 데이터 릴리스 복구")
        con.commit()
    return {"ok":True,"release_id":release_id,"feed_id":row[0]}


@app.get("/admin/data/import-jobs")
async def list_data_import_jobs(request: Request, limit: int = Query(default=100,ge=1,le=300)):
    _admin_session(request); require_durable_database()
    with closing(db()) as con:
        rows=con.execute("SELECT job_id,source_id,file_name,file_size,sha256,status,validation_json,created_by,created_at,imported_feed_id,error_message FROM data_import_jobs ORDER BY created_at DESC LIMIT ?",(limit,)).fetchall()
    return {"jobs":[{"job_id":r[0],"source_id":r[1],"file_name":r[2],"file_size":r[3],"sha256":r[4],"status":r[5],"validation":json.loads(r[6] or "{}"),"created_by":r[7],"created_at":r[8],"imported_feed_id":r[9],"error_message":r[10]} for r in rows]}


@app.get("/gtfs/feeds")
async def gtfs_feeds():
    with closing(db()) as con:
        rows = [dict(r) for r in con.execute("SELECT feed_id,name,agency,imported_at,stop_count,route_count,trip_count,source_id,source_version,effective_date,license_name,source_url,sha256,is_active FROM feeds WHERE is_active=1 ORDER BY imported_at DESC")]
    return {"feeds": rows, "count": len(rows)}


def haversine_m(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    r = 6371000
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp, dl = math.radians(lat2-lat1), math.radians(lon2-lon1)
    a = math.sin(dp/2)**2 + math.cos(p1)*math.cos(p2)*math.sin(dl/2)**2
    return 2*r*math.asin(math.sqrt(a))



def classify_route_type(raw_route_type: Any) -> str:
    """Map standard and common GTFS extended route types to app transport modes."""
    try:
        route_type = int(raw_route_type if raw_route_type not in (None, "") else 3)
    except (TypeError, ValueError):
        route_type = 3
    # Standard bus plus extended coach, bus and trolleybus families.
    if route_type == 3 or 200 <= route_type < 300 or 700 <= route_type < 900:
        return "bus"
    # Standard rail/tram/subway and extended rail, urban rail and tram families.
    if route_type in (0, 1, 2, 5, 6, 7) or 100 <= route_type < 200 or 400 <= route_type < 500 or 900 <= route_type < 1000:
        return "rail"
    return "other"

def nearest_gtfs_stops(lat: float, lon: float, max_walk_m: int, limit: int = 8) -> list[dict[str, Any]]:
    dlat = max_walk_m / 110540
    dlon = max_walk_m / max(10000, 111320 * math.cos(math.radians(lat)))
    with closing(db()) as con:
        rows = con.execute("SELECT feed_id,stop_id,name,lat,lon FROM stops WHERE location_type IN (0,4) AND lat BETWEEN ? AND ? AND lon BETWEEN ? AND ?",
                           (lat-dlat, lat+dlat, lon-dlon, lon+dlon)).fetchall()
    out = []
    for row in rows:
        d = haversine_m(lat, lon, row["lat"], row["lon"])
        if d <= max_walk_m:
            out.append({"feed_id": row["feed_id"], "stop_id": row["stop_id"], "name": row["name"], "lat": row["lat"], "lon": row["lon"], "distance_m": d})
    return sorted(out, key=lambda x: x["distance_m"])[:limit]


def active_services(con: sqlite3.Connection, feed_id: str, service_date: date) -> tuple[set[str], bool]:
    """Return services for this date and whether an expired reference calendar was reused.

    If a calendar row covers the requested date, its weekday flag is authoritative.
    We only reuse an archived weekday pattern when the requested date is outside
    that service's published range. This is explicitly marked as reference data.
    """
    day_column = ["monday","tuesday","wednesday","thursday","friday","saturday","sunday"][service_date.weekday()]
    ds = service_date.strftime("%Y%m%d")
    rows = con.execute(
        f"SELECT service_id,start_date,end_date,{day_column} AS active FROM calendars WHERE feed_id=?",
        (feed_id,),
    ).fetchall()
    services: set[str] = set()
    reference_used = False
    for row in rows:
        in_range = (row["start_date"] or "00000000") <= ds <= (row["end_date"] or "99999999")
        if in_range and row["active"] == 1:
            services.add(row["service_id"])
        elif not in_range and row["active"] == 1:
            services.add(row["service_id"])
            reference_used = True
    exception_rows = con.execute(
        "SELECT service_id,exception_type FROM calendar_dates WHERE feed_id=? AND service_date=?",
        (feed_id, ds),
    ).fetchall()
    for row in exception_rows:
        if row["exception_type"] == 1:
            services.add(row["service_id"])
        elif row["exception_type"] == 2:
            services.discard(row["service_id"])

    # Feeds that publish only calendar_dates (rather than calendar.txt) can
    # still supply a weekday reference pattern when their only date is stale.
    if not rows and not exception_rows:
        historical = con.execute(
            "SELECT service_id,service_date,exception_type FROM calendar_dates WHERE feed_id=? AND exception_type=1",
            (feed_id,),
        ).fetchall()
        for row in historical:
            try:
                old_date = datetime.strptime(row["service_date"], "%Y%m%d").date()
            except ValueError:
                continue
            if old_date.weekday() == service_date.weekday():
                services.add(row["service_id"])
                reference_used = True
    return services, reference_used


def build_connections(service_date: date, after_ts: float, before_ts: float) -> tuple[
    dict[tuple[str,str], list[dict[str, Any]]],
    dict[str, dict[str, Any]],
    dict[tuple[str,str,str], list[dict[str, Any]]],
    dict[tuple[str,str,str], list[dict[str, Any]]],
]:
    by_from: dict[tuple[str,str], list[dict[str, Any]]] = defaultdict(list)
    stop_meta: dict[str, dict[str, Any]] = {}
    transfer_rules: dict[tuple[str,str,str], list[dict[str, Any]]] = defaultdict(list)
    linked_transfer_rules: dict[tuple[str,str,str], list[dict[str, Any]]] = defaultdict(list)
    with closing(db()) as con:
        feeds = [r[0] for r in con.execute("SELECT feed_id FROM feeds WHERE is_active=1")]
        for feed_id in feeds:
            stops = con.execute("SELECT stop_id,name,lat,lon,parent_station,location_type,wheelchair_boarding,platform_code FROM stops WHERE feed_id=?", (feed_id,)).fetchall()
            for st in stops:
                stop_meta[f"{feed_id}|{st['stop_id']}"] = {
                    "feed_id": feed_id, "stop_id": st["stop_id"], "name": st["name"],
                    "lat": st["lat"], "lon": st["lon"], "parent_station": st["parent_station"] or "",
                    "location_type": st["location_type"] or 0, "wheelchair_boarding": st["wheelchair_boarding"] or 0,
                    "platform_code": st["platform_code"] or ""
                }
            for tr in con.execute("SELECT from_stop_id,to_stop_id,from_trip_id,to_trip_id,from_route_id,to_route_id,transfer_type,min_transfer_time FROM gtfs_transfers WHERE feed_id=?", (feed_id,)):
                row = dict(tr)
                if row.get("from_stop_id") and row.get("to_stop_id"):
                    transfer_rules[(feed_id,row["from_stop_id"],row["to_stop_id"])].append(row)
                if row.get("from_trip_id") and row.get("to_trip_id") and int(row.get("transfer_type") or 0) in (4,5):
                    linked_transfer_rules[(feed_id,row["from_trip_id"],row["to_trip_id"])].append(row)
            for offset in (-1, 0, 1):
                service_day = service_date + timedelta(days=offset)
                services, used_reference = active_services(con, feed_id, service_day)
                if not services:
                    continue
                service_ids = list(services)
                for chunk_start in range(0, len(service_ids), 400):
                    chunk = service_ids[chunk_start:chunk_start+400]
                    qmarks = ",".join("?" for _ in chunk)
                    sql = f"""
                    WITH ordered AS (
                      SELECT st.feed_id,st.trip_id,st.stop_id,st.stop_sequence,st.arrival_secs,st.departure_secs,
                             LEAD(st.stop_id) OVER (PARTITION BY st.feed_id,st.trip_id ORDER BY st.stop_sequence) AS to_stop,
                             LEAD(st.arrival_secs) OVER (PARTITION BY st.feed_id,st.trip_id ORDER BY st.stop_sequence) AS to_arrival_secs
                      FROM stop_times st
                      JOIN trips active_trip ON active_trip.feed_id=st.feed_id AND active_trip.trip_id=st.trip_id
                      WHERE st.feed_id=? AND active_trip.service_id IN ({qmarks})
                    )
                    SELECT a.trip_id,a.stop_id AS from_stop,a.to_stop,a.departure_secs,a.to_arrival_secs AS arrival_secs,
                           t.route_id,t.service_id,COALESCE(r.short_name,r.long_name,r.route_id) AS route_name,
                           COALESCE(r.color,'') AS route_color,COALESCE(r.route_type,3) AS route_type,t.headsign,t.shape_id
                    FROM ordered a
                    JOIN trips t ON t.feed_id=a.feed_id AND t.trip_id=a.trip_id
                    LEFT JOIN routes r ON r.feed_id=t.feed_id AND r.route_id=t.route_id
                    WHERE a.to_stop IS NOT NULL
                    """
                    for row in con.execute(sql, [feed_id, *chunk]):
                        dep = datetime.combine(service_day, datetime.min.time(), TZ).timestamp() + row["departure_secs"]
                        arr = datetime.combine(service_day, datetime.min.time(), TZ).timestamp() + row["arrival_secs"]
                        if arr < after_ts - 3600 or dep > before_ts:
                            continue
                        key = (feed_id, row["from_stop"])
                        by_from[key].append({"feed_id": feed_id, "trip_id": row["trip_id"], "from_stop": row["from_stop"], "to_stop": row["to_stop"],
                            "dep": dep, "arr": arr, "route_id": row["route_id"], "route_name": row["route_name"], "route_color": row["route_color"],
                            "route_type": row["route_type"], "headsign": row["headsign"], "shape_id": row["shape_id"], "reference_schedule": used_reference})
    for key in by_from:
        by_from[key].sort(key=lambda x: x["dep"])
    return by_from, stop_meta, transfer_rules, linked_transfer_rules

def _pathway_seconds(pathway_mode: int, length_m: float | None, traversal_time: int | None) -> int:
    if traversal_time and traversal_time > 0:
        return max(1, int(traversal_time))
    if pathway_mode == 5:  # elevator: conservative default for wait + ride
        return 90
    if pathway_mode in (6, 7):  # fare/exit gates
        return 15
    speed = 0.55 if pathway_mode == 2 else (0.65 if pathway_mode == 4 else 1.0)
    return max(1, int(math.ceil((length_m or 30.0) / speed)))


def _station_pathways_exist(con, feed_id: str, station_id: str) -> bool:
    row = con.execute("""
        SELECT 1 FROM gtfs_pathways p
        JOIN stops a ON a.feed_id=p.feed_id AND a.stop_id=p.from_stop_id
        JOIN stops b ON b.feed_id=p.feed_id AND b.stop_id=p.to_stop_id
        WHERE p.feed_id=?
          AND (a.stop_id=? OR a.parent_station=? OR b.stop_id=? OR b.parent_station=?)
        LIMIT 1
    """, (feed_id, station_id, station_id, station_id, station_id)).fetchone()
    return bool(row)


def walk_neighbors(stop: dict[str, Any], max_m: int = 350) -> list[tuple[tuple[str,str], float, dict[str,Any]]]:
    out: dict[tuple[str,str], tuple[float,dict[str,Any]]] = {}
    with closing(db()) as con:
        # Explicit station pathways are exhaustive: if the station defines them,
        # never invent a shortcut between sibling platforms.
        path_rows = con.execute(
            "SELECT p.*,s.name,s.lat,s.lon FROM gtfs_pathways p JOIN stops s ON s.feed_id=p.feed_id AND s.stop_id=p.to_stop_id WHERE p.feed_id=? AND p.from_stop_id=?",
            (stop["feed_id"],stop["stop_id"])).fetchall()
        for row in path_rows:
            seconds = _pathway_seconds(int(row["pathway_mode"]), row["length_m"], row["traversal_time"])
            meta = {"name":row["name"],"lat":row["lat"],"lon":row["lon"],"distance_m":row["length_m"] or 0,
                    "source":"GTFS pathways", "pathway_mode":row["pathway_mode"]}
            out[(row["feed_id"],row["to_stop_id"])] = (seconds/60,meta)
        reverse_rows = con.execute(
            "SELECT p.*,s.name,s.lat,s.lon FROM gtfs_pathways p JOIN stops s ON s.feed_id=p.feed_id AND s.stop_id=p.from_stop_id WHERE p.feed_id=? AND p.to_stop_id=? AND p.is_bidirectional=1",
            (stop["feed_id"],stop["stop_id"])).fetchall()
        for row in reverse_rows:
            seconds = _pathway_seconds(int(row["pathway_mode"]), row["length_m"], row["traversal_time"])
            meta = {"name":row["name"],"lat":row["lat"],"lon":row["lon"],"distance_m":row["length_m"] or 0,
                    "source":"GTFS pathways (bidirectional)", "pathway_mode":row["pathway_mode"]}
            out[(row["feed_id"],row["from_stop_id"])] = (seconds/60,meta)
        parent = stop.get("parent_station") or ""
        if parent and not _station_pathways_exist(con, stop["feed_id"], parent):
            siblings = con.execute("SELECT feed_id,stop_id,name,lat,lon FROM stops WHERE feed_id=? AND parent_station=? AND stop_id<>? AND location_type IN (0,4)",
                                   (stop["feed_id"],parent,stop["stop_id"])).fetchall()
            for row in siblings:
                key=(row["feed_id"],row["stop_id"])
                if key in out: continue
                dist=haversine_m(stop["lat"],stop["lon"],row["lat"],row["lon"])
                seconds=max(120,int(math.ceil(dist/0.8)))
                out[key]=(seconds/60,{"name":row["name"],"lat":row["lat"],"lon":row["lon"],"distance_m":dist,
                                      "source":"GTFS parent_station fallback"})
        # Nearby cross-feed physical transfers are limited to actual boarding locations.
        dlat=max_m/110540
        dlon=max_m/max(10000,111320*math.cos(math.radians(stop["lat"])))
        # Prefer explicit station entrances across feeds. Connecting a nearby
        # bus stop straight to a rail platform can bypass station pathways,
        # security/fare gates and platform access time. If the rail feed has no
        # entrance records in range, fall back to platforms/boarding areas.
        bounds=(stop["lat"]-dlat,stop["lat"]+dlat,stop["lon"]-dlon,stop["lon"]+dlon)
        rows=con.execute("SELECT feed_id,stop_id,name,lat,lon,parent_station FROM stops WHERE location_type=2 AND lat<>0 AND lon<>0 AND lat BETWEEN ? AND ? AND lon BETWEEN ? AND ?", bounds).fetchall()
        if not rows:
            rows=con.execute("SELECT feed_id,stop_id,name,lat,lon,parent_station FROM stops WHERE location_type IN (0,4) AND lat<>0 AND lon<>0 AND lat BETWEEN ? AND ? AND lon BETWEEN ? AND ?", bounds).fetchall()
    for row in rows:
        # The geometric fallback is only for stitching distinct datasets (e.g.
        # bus feed to rail feed). Same-feed connectivity must come from GTFS
        # pathways, parent_station or explicit transfer rules, not straight-line guesses.
        if row["feed_id"] == stop["feed_id"]:
            continue
        key=(row["feed_id"],row["stop_id"])
        dist=haversine_m(stop["lat"],stop["lon"],row["lat"],row["lon"])
        if dist>max_m or key in out: continue
        mins=max(1,int(math.ceil(dist/75)))
        out[key]=(mins,{"name":row["name"],"lat":row["lat"],"lon":row["lon"],"distance_m":dist,"source":"nearby stop walk"})
    return [(key,mins,meta) for key,(mins,meta) in out.items()]


def _stop_aliases(stop_meta: dict[str, Any] | None, fallback_stop_id: str) -> list[str]:
    if not stop_meta:
        return [fallback_stop_id]
    values = [fallback_stop_id]
    parent = (stop_meta.get("parent_station") or "").strip()
    if parent:
        values.append(parent)
    return list(dict.fromkeys(x for x in values if x))


def _best_gtfs_transfer_rule(rules: list[dict[str,Any]], from_trip: str, to_trip: str,
                             from_route: str, to_route: str) -> dict[str,Any] | None:
    applicable=[]
    seen_rules=set()
    for rule in rules:
        identity=tuple((rule.get(k) or "") for k in ("from_stop_id","to_stop_id","from_trip_id","to_trip_id","from_route_id","to_route_id","transfer_type","min_transfer_time"))
        if identity in seen_rules:
            continue
        seen_rules.add(identity)
        ft=rule.get("from_trip_id") or ""; tt=rule.get("to_trip_id") or ""
        fr=rule.get("from_route_id") or ""; tr=rule.get("to_route_id") or ""
        if ft and ft!=from_trip: continue
        if tt and tt!=to_trip: continue
        if fr and fr!=from_route: continue
        if tr and tr!=to_route: continue
        if ft and tt: rank=6
        elif (ft and tr) or (fr and tt): rank=5
        elif ft or tt: rank=4
        elif fr and tr: rank=3
        elif fr or tr: rank=2
        else: rank=1
        applicable.append((rank,rule))
    if not applicable: return None
    applicable.sort(key=lambda item:item[0],reverse=True)
    # Equal maximal matches are invalid GTFS. Refuse ambiguous routing instead of
    # selecting an arbitrary rule based on file row order.
    if len(applicable)>1 and applicable[0][0] == applicable[1][0]:
        raise ValueError("GTFS transfers.txt에서 동일 우선순위의 환승 규칙이 충돌합니다.")
    return applicable[0][1]

def transit_leg(start: Waypoint, end: Waypoint, depart_dt: datetime, max_walk_m: int, preference: str, required_route: str | None, mode: str = "transit") -> dict[str, Any] | None:
    starts = nearest_gtfs_stops(start.lat, start.lon, max_walk_m)
    ends = nearest_gtfs_stops(end.lat, end.lon, max_walk_m)
    if not starts or not ends:
        return None
    start_keys = {(x["feed_id"],x["stop_id"]): x for x in starts}
    end_keys = {(x["feed_id"],x["stop_id"]): x for x in ends}
    start_ts = depart_dt.timestamp()
    by_from, stop_meta, transfer_rules, linked_transfer_rules = build_connections(depart_dt.date(), start_ts, start_ts + 36*3600)
    if not by_from:
        return None
    # GTFS linked-trip rules (transfer_type 4/5) are only meaningful at the
    # last stop of the incoming trip and the first stop of the outgoing trip.
    # Derive those boundaries from the scheduled ride edges, rather than
    # accidentally allowing a linked transfer at an intermediate station.
    trip_first_stop: dict[tuple[str, str], tuple[float, str]] = {}
    trip_last_stop: dict[tuple[str, str], tuple[float, str]] = {}
    for (edge_feed, _origin), edge_list in by_from.items():
        for scheduled_edge in edge_list:
            trip_key = (edge_feed, scheduled_edge["trip_id"])
            first = trip_first_stop.get(trip_key)
            if first is None or scheduled_edge["dep"] < first[0]:
                trip_first_stop[trip_key] = (scheduled_edge["dep"], scheduled_edge["from_stop"])
            last = trip_last_stop.get(trip_key)
            if last is None or scheduled_edge["arr"] > last[0]:
                trip_last_stop[trip_key] = (scheduled_edge["arr"], scheduled_edge["to_stop"])
    # A label records the currently boarded trip. Keeping trip in the state permits zero-transfer continuation.
    import heapq
    q=[]; serial=0
    # required-route-used is part of the state so a slower path using the requested line is not discarded.
    State = tuple[str,str,str|None,str|None,str|None,str|None,float,bool]
    best: dict[State, float] = {}
    arrival_at: dict[State, float] = {}
    prev: dict[State, tuple[State,dict[str,Any]] | None] = {}
    transfers_by_state: dict[State,int] = {}
    walk_by_state: dict[State,int] = {}
    rides_used: dict[State,bool] = {}
    footpath_cache: dict[tuple[str,str], list[Any]] = {}
    walk_penalty = 0 if preference == "fast" else (2.5 if preference == "walk" else 0)
    transfer_penalty = 12 if preference == "transfer" else 0
    for key,x in start_keys.items():
        walk_min = int(math.ceil(x["distance_m"]/75))
        st=(key[0],key[1],None,None,None,None,0.0,False)
        t=start_ts+walk_min*60
        score=t+walk_min*walk_penalty*60
        best[st]=score;arrival_at[st]=t;prev[st]=None;transfers_by_state[st]=0;walk_by_state[st]=walk_min;rides_used[st]=False
        heapq.heappush(q,(score,serial,st));serial+=1
    best_goal_score=None; best_goal_arrival=None; goal_walk=0; goal_state=None
    req = (required_route or "").strip().lower()
    max_states=65000; visited=0
    while q and visited < max_states:
        score,_,state=heapq.heappop(q); visited+=1
        if score != best.get(state): continue
        now=arrival_at[state]
        feed_id,stop_id,current_trip,current_route_id,last_ride_feed,last_ride_stop,last_arrival_epoch,req_seen=state
        meta=stop_meta.get(f"{feed_id}|{stop_id}")
        if not meta: continue
        if (feed_id,stop_id) in end_keys and rides_used.get(state, False):
            # Walking is allowed for access/egress and transfers, but a transit
            # result must contain at least one actual scheduled ride. Without this
            # guard, nearby records in separate feeds can create a fake all-walk
            # "transit" route and hide the rail/bus itinerary.
            d=end_keys[(feed_id,stop_id)]["distance_m"]
            w=int(math.ceil(d/75))
            goal_time=now+w*60
            goal_score=goal_time+(walk_by_state.get(state,0)+w)*walk_penalty*60+transfers_by_state.get(state,0)*transfer_penalty*60
            if (not req or req_seen) and (best_goal_score is None or goal_score<best_goal_score):
                best_goal_score=goal_score;best_goal_arrival=goal_time;goal_walk=w;goal_state=state
        if best_goal_score is not None and score > best_goal_score: break
        foot_key=(feed_id,stop_id)
        if foot_key not in footpath_cache:
            footpath_cache[foot_key]=walk_neighbors(meta)
        for neighbor, mins, nmeta in footpath_cache[foot_key]:
            ns=(neighbor[0],neighbor[1],current_trip,current_route_id,last_ride_feed,last_ride_stop,last_arrival_epoch,req_seen); nt=now+mins*60
            total_walk=walk_by_state.get(state,0)+mins
            new_score=nt+total_walk*walk_penalty*60+transfers_by_state.get(state,0)*transfer_penalty*60
            if new_score < best.get(ns,float("inf")):
                best[ns]=new_score;arrival_at[ns]=nt;prev[ns]=(state,{"kind":"walk_transfer","from":meta,"to":nmeta,"minutes":mins})
                transfers_by_state[ns]=transfers_by_state.get(state,0);walk_by_state[ns]=total_walk;rides_used[ns]=rides_used.get(state,False)
                heapq.heappush(q,(new_score,serial,ns));serial+=1
        edges=list(by_from.get((feed_id,stop_id),[]))
        # GTFS transfer_type=4 can link two different stop IDs for consecutive
        # trips operated by the same vehicle. Such a continuation has no
        # passenger walking edge, so inject only the next trip's first ride
        # edge when both trip boundaries and the physical endpoint are valid.
        if current_trip is not None and last_ride_feed == feed_id:
            incoming_last = trip_last_stop.get((feed_id, current_trip))
            if incoming_last and stop_id == incoming_last[1]:
                from_meta_for_link = stop_meta.get(f"{feed_id}|{stop_id}")
                from_aliases_for_link = _stop_aliases(from_meta_for_link, stop_id)
                existing_link_edges = {(e["trip_id"], e["from_stop"], e["dep"]) for e in edges}
                for (link_feed, from_trip, to_trip), link_rules in linked_transfer_rules.items():
                    if link_feed != feed_id or from_trip != current_trip or not link_rules:
                        continue
                    outgoing_first = trip_first_stop.get((feed_id, to_trip))
                    if not outgoing_first:
                        continue
                    first_stop_id = outgoing_first[1]
                    to_meta_for_link = stop_meta.get(f"{feed_id}|{first_stop_id}")
                    if not to_meta_for_link:
                        continue
                    to_aliases_for_link = _stop_aliases(to_meta_for_link, first_stop_id)
                    same_parent = bool(from_meta_for_link.get("parent_station") and
                                       from_meta_for_link.get("parent_station") == to_meta_for_link.get("parent_station"))
                    close_endpoints = haversine_m(from_meta_for_link.get("lat") or 0,
                                                  from_meta_for_link.get("lon") or 0,
                                                  to_meta_for_link.get("lat") or 0,
                                                  to_meta_for_link.get("lon") or 0) <= 100
                    if first_stop_id != stop_id and not (same_parent or close_endpoints):
                        continue
                    for linked_edge in by_from.get((feed_id, first_stop_id), []):
                        if linked_edge["trip_id"] != to_trip:
                            continue
                        try:
                            link_rule = _best_gtfs_transfer_rule(link_rules, current_trip, to_trip,
                                                                current_route_id or "", linked_edge.get("route_id") or "")
                        except ValueError:
                            continue
                        if not link_rule or int(link_rule.get("transfer_type", 0)) != 4:
                            continue
                        rule_from = (link_rule.get("from_stop_id") or "").strip()
                        rule_to = (link_rule.get("to_stop_id") or "").strip()
                        if rule_from and rule_from not in from_aliases_for_link:
                            continue
                        if rule_to and rule_to not in to_aliases_for_link:
                            continue
                        key = (linked_edge["trip_id"], linked_edge["from_stop"], linked_edge["dep"])
                        if key not in existing_link_edges:
                            edges.append({**linked_edge, "_linked_in_seat": True})
                            existing_link_edges.add(key)
        if not edges: continue
        chosen=[]; route_counts=defaultdict(int)
        for edge in edges:
            if edge["dep"] < now - 15: continue
            edge_mode = classify_route_type(edge.get("route_type", 3))
            if mode == "bus" and edge_mode != "bus":
                continue
            if mode == "rail" and edge_mode != "rail":
                continue
            if mode == "transit" and edge_mode not in ("bus", "rail"):
                continue
            same_trip = current_trip is not None and edge["trip_id"] == current_trip and last_ride_feed == edge["feed_id"]
            transfer_rule = None
            in_seat = False
            if not same_trip and current_trip is not None and last_ride_feed and last_ride_stop:
                from_meta = stop_meta.get(f"{last_ride_feed}|{last_ride_stop}")
                to_meta = stop_meta.get(f"{edge['feed_id']}|{edge['from_stop']}")
                from_aliases = _stop_aliases(from_meta, last_ride_stop)
                to_aliases = _stop_aliases(to_meta, edge["from_stop"])
                rule_list=[]
                if last_ride_feed == edge["feed_id"]:
                    for from_alias in from_aliases:
                        for to_alias in to_aliases:
                            rule_list.extend(transfer_rules.get((last_ride_feed,from_alias,to_alias), []))
                    rule_list.extend(linked_transfer_rules.get((last_ride_feed,current_trip,edge["trip_id"]), []))
                try:
                    transfer_rule = _best_gtfs_transfer_rule(rule_list, current_trip, edge["trip_id"], current_route_id or "", edge["route_id"] or "")
                except ValueError:
                    # A feed with ambiguous equally-specific rules is unsafe for this connection.
                    continue
                if transfer_rule:
                    transfer_type = int(transfer_rule.get("transfer_type", 0))
                    rule_from = (transfer_rule.get("from_stop_id") or "").strip()
                    rule_to = (transfer_rule.get("to_stop_id") or "").strip()
                    if rule_from and rule_from not in from_aliases: continue
                    if rule_to and rule_to not in to_aliases: continue
                    if transfer_type == 3:
                        continue  # GTFS explicitly forbids this transfer.
                    if transfer_type in (4, 5):
                        # Linked-trip rules apply at trip boundaries only.
                        incoming_last = trip_last_stop.get((last_ride_feed, current_trip))
                        outgoing_first = trip_first_stop.get((edge["feed_id"], edge["trip_id"]))
                        if not incoming_last or not outgoing_first:
                            continue
                        if stop_id != incoming_last[1] or edge["from_stop"] != outgoing_first[1]:
                            continue
                    if transfer_type == 4:
                        # In-seat transfer: no alighting, walking or re-boarding.
                        # Different stop IDs are allowed only when the linked
                        # trip endpoints describe the same physical interchange.
                        same_parent = bool(from_meta and to_meta and from_meta.get("parent_station") and
                                           from_meta.get("parent_station") == to_meta.get("parent_station"))
                        close_endpoints = bool(from_meta and to_meta and
                                               haversine_m(from_meta.get("lat") or 0, from_meta.get("lon") or 0,
                                                           to_meta.get("lat") or 0, to_meta.get("lon") or 0) <= 100)
                        if stop_id != edge["from_stop"] and not (same_parent or close_endpoints):
                            continue
                        in_seat = True
                        required_transfer_seconds = 0
                    elif transfer_type == 5:
                        # GTFS says in-seat is not allowed: passenger must alight and re-board.
                        if not rule_from and not rule_to:
                            same_parent = bool(from_meta and to_meta and from_meta.get("parent_station") and
                                               from_meta.get("parent_station") == to_meta.get("parent_station"))
                            if last_ride_stop != edge["from_stop"] and not same_parent:
                                continue
                        minimum = transfer_rule.get("min_transfer_time")
                        required_transfer_seconds = int(minimum) if minimum not in (None, "") else 240
                    elif transfer_type == 2:
                        required_transfer_seconds = int(transfer_rule.get("min_transfer_time") or 0)
                    elif transfer_type == 1:
                        # Timed connection: provider declares the connection is coordinated.
                        required_transfer_seconds = int(transfer_rule.get("min_transfer_time") or 0)
                    else:  # transfer_type 0 (recommended) or default
                        required_transfer_seconds = int(transfer_rule.get("min_transfer_time") or 240)
                else:
                    # No explicit transfer record: conservative minimum connection buffer.
                    required_transfer_seconds = 240
                if edge["dep"] < max(now, last_arrival_epoch + required_transfer_seconds):
                    continue
            rn=edge["route_name"] or edge["route_id"]
            if route_counts[rn] >= 3: continue
            route_counts[rn]+=1
            chosen.append((edge, transfer_rule, in_seat))
            if len(chosen)>=70: break
        for e, edge_transfer_rule, edge_in_seat in chosen:
            this_req=req_seen or (bool(req) and (req in str(e["route_name"]).lower() or req in str(e["route_id"]).lower()))
            nstate=(feed_id,e["to_stop"],e["trip_id"],e["route_id"],feed_id,e["to_stop"],e["arr"],this_req)
            nt=e["arr"]
            already_boarded=rides_used.get(state,False)
            tr=transfers_by_state.get(state,0)+(1 if already_boarded and current_trip!=e["trip_id"] and not edge_in_seat else 0)
            total_walk=walk_by_state.get(state,0)
            new_score=nt+tr*transfer_penalty*60+total_walk*walk_penalty*60
            if new_score < best.get(nstate,float("inf")):
                best[nstate]=new_score;arrival_at[nstate]=nt;prev[nstate]=(state,{"kind":"ride","edge":e,"transfer_rule":edge_transfer_rule,"in_seat_transfer":edge_in_seat})
                transfers_by_state[nstate]=tr;walk_by_state[nstate]=total_walk;rides_used[nstate]=True
                heapq.heappush(q,(new_score,serial,nstate));serial+=1
    if goal_state is None:
        return None
    path=[];cur=goal_state
    while cur is not None:
        pr=prev.get(cur)
        if pr is None: break
        parent,action=pr;path.append(action);cur=parent
    root_state=cur
    path.reverse()
    reference_schedule_used = any(
        action.get("kind") == "ride" and action.get("edge", {}).get("reference_schedule", False)
        for action in path
    )
    applied_transfer_rules = [action.get("transfer_rule") for action in path if action.get("kind") == "ride" and action.get("transfer_rule")]
    steps=[]
    root_key=(root_state[0],root_state[1]) if root_state else (starts[0]["feed_id"],starts[0]["stop_id"])
    root_meta=stop_meta.get(f"{root_key[0]}|{root_key[1]}",{})
    start_walk_m=next((x["distance_m"] for x in starts if (x["feed_id"],x["stop_id"])==root_key),starts[0]["distance_m"])
    start_walk_min=int(math.ceil(start_walk_m/75))
    if start_walk_min:
        s=next((x for x in starts if (x["feed_id"],x["stop_id"])==root_key),starts[0])
        steps.append({"mode":"walk","from":start.name,"to":s["name"],"minutes":start_walk_min,"from_point":[start.lat,start.lon],"to_point":[s["lat"],s["lon"]]})
    ride_group=None
    for action in path:
        if action["kind"]=="walk_transfer":
            if ride_group:
                steps.append(ride_group);ride_group=None
            steps.append({"mode":"walk","from":action["from"]["name"],"to":action["to"]["name"],"minutes":action["minutes"],
                          "from_point":[action["from"]["lat"],action["from"]["lon"]],"to_point":[action["to"]["lat"],action["to"]["lon"]],
                          "source":action["to"].get("source", "GTFS walking connection")})
            continue
        e=action["edge"]
        from_meta=stop_meta.get(f"{e['feed_id']}|{e['from_stop']}",{})
        to_meta=stop_meta.get(f"{e['feed_id']}|{e['to_stop']}",{})
        if ride_group and ride_group["trip_id"]==e["trip_id"]:
            ride_group["to"]=to_meta.get("name",e["to_stop"]);ride_group["to_point"]=[to_meta.get("lat"),to_meta.get("lon")]
            ride_group["arrival_epoch"]=e["arr"];ride_group["minutes"]=max(1,int(round((ride_group["arrival_epoch"]-ride_group["departure_epoch"])/60)))
            ride_group["points"].append([to_meta.get("lat"),to_meta.get("lon")])
        else:
            if ride_group: steps.append(ride_group)
            route_type = int(e.get("route_type", 3) or 3)
            ride_mode = classify_route_type(route_type)
            trule = action.get("transfer_rule")
            transfer_type = int(trule.get("transfer_type", 0)) if trule else None
            ride_group={"mode":ride_mode,"route_type":route_type,"trip_id":e["trip_id"],"feed_id":e["feed_id"],"shape_id":e.get("shape_id"),"route_id":e["route_id"],"route":e["route_name"],"headsign":e["headsign"],
                        "from":from_meta.get("name",e["from_stop"]),"to":to_meta.get("name",e["to_stop"]),"minutes":max(1,int(round((e["arr"]-e["dep"])/60))),
                        "departure_epoch":e["dep"],"arrival_epoch":e["arr"],"departure_time":datetime.fromtimestamp(e["dep"],TZ).strftime("%H:%M"),
                        "arrival_time":datetime.fromtimestamp(e["arr"],TZ).strftime("%H:%M"),"color":e["route_color"],
                        "from_point":[from_meta.get("lat"),from_meta.get("lon")],"to_point":[to_meta.get("lat"),to_meta.get("lon")],
                        "points":[[from_meta.get("lat"),from_meta.get("lon")],[to_meta.get("lat"),to_meta.get("lon")]]}
            if transfer_type is not None:
                ride_group["transfer_rule_type"] = transfer_type
                ride_group["transfer_note"] = {0:"권장 환승 규칙 적용",1:"시간 연계 환승 규칙 적용",2:"최소 환승시간 적용",3:"환승 불가",4:"동일 차량 좌석 내 환승",5:"하차 후 재승차 규칙 적용"}.get(transfer_type,"환승 규칙 적용")
    if ride_group: steps.append(ride_group)
    for ride_step in [x for x in steps if x.get("mode") in ("bus", "rail") and x.get("shape_id")]:
        with closing(db()) as con:
            shape_rows=con.execute("SELECT lat,lon FROM shapes WHERE feed_id=? AND shape_id=? ORDER BY sequence",(ride_step["feed_id"],ride_step["shape_id"])).fetchall()
        shape_pts=[[r["lat"],r["lon"]] for r in shape_rows]
        if len(shape_pts)>=2:
            a=ride_step["from_point"];b=ride_step["to_point"]
            ia=min(range(len(shape_pts)),key=lambda i:(shape_pts[i][0]-a[0])**2+(shape_pts[i][1]-a[1])**2)
            ib=min(range(len(shape_pts)),key=lambda i:(shape_pts[i][0]-b[0])**2+(shape_pts[i][1]-b[1])**2)
            segment=shape_pts[ia:ib+1] if ia<=ib else list(reversed(shape_pts[ib:ia+1]))
            if len(segment)>=2: ride_step["points"]=segment
    if goal_walk:
        end_stop=end_keys[(goal_state[0],goal_state[1])]
        steps.append({"mode":"walk","from":end_stop["name"],"to":end.name,"minutes":goal_walk,
                      "from_point":[end_stop["lat"],end_stop["lon"]],"to_point":[end.lat,end.lon]})
    arrival_dt=datetime.fromtimestamp(best_goal_arrival,TZ)
    rides=[s for s in steps if s["mode"] in ("bus", "rail")]
    walk_min=sum(s["minutes"] for s in steps if s["mode"]=="walk")
    ride_min=sum(s["minutes"] for s in rides)
    transfers=transfers_by_state.get(goal_state, max(0,len(rides)-1))
    return {"steps":steps,"arrival":arrival_dt.isoformat(),"arrival_epoch":best_goal_arrival,"ride_minutes":ride_min,
            "walk_minutes":walk_min,"transfers":transfers,"lines":list(dict.fromkeys(s["route"] for s in rides)),
            "reference_schedule_used":reference_schedule_used,"gtfs_transfer_rules_applied":len(applied_transfer_rules),
            "wait_minutes":max(0,int(round((best_goal_arrival-start_ts)/60))-ride_min-walk_min)}


@app.post("/route/plan")
async def plan_route(req: PlanRequest):
    require_durable_database()
    with closing(db()) as con:
        if _setting_value(con, "maintenance_mode", False):
            raise HTTPException(503, "현재 B-ROUTE 점검 중입니다. 잠시 후 다시 이용해 주세요.")
        if not _setting_value(con, "route_search_enabled", True):
            raise HTTPException(503, "총괄자가 경로 검색을 일시 중지했습니다.")
        feed_count=con.execute("SELECT COUNT(*) FROM feeds WHERE is_active=1").fetchone()[0]
    if not feed_count:
        raise HTTPException(503, "활성 상태의 실제 대중교통 경로 데이터가 아직 등록되지 않았습니다. GTFS ZIP을 등록하면 해당 지역의 실제 노선·정류장·시간표로 경로를 계산합니다. 장소 검색·지도·GPS·경유지 설정은 이미 사용할 수 있습니다.")
    try:
        depart = datetime.fromisoformat(req.departure_time) if req.departure_time else datetime.now(TZ)
        if depart.tzinfo is None: depart=depart.replace(tzinfo=TZ)
        depart=depart.astimezone(TZ)
    except ValueError:
        raise HTTPException(400, "출발 날짜와 시간을 확인해 주세요.")
    waypoints=req.waypoints
    if len(waypoints)<2:
        raise HTTPException(400,"출발지와 도착지를 지정해야 합니다.")
    def build_itinerary(required_leg: int | None):
        current_time=depart
        steps=[]; summaries=[]; ride_total=walk_total=transfer_total=0; reference_schedule_used=False; transfer_rules_applied=0
        for idx in range(len(waypoints)-1):
            a,b=waypoints[idx],waypoints[idx+1]
            force=req.required_route if required_leg==idx else None
            leg=transit_leg(a,b,current_time,req.max_walk_m,req.preference,force,req.mode)
            if not leg:
                return None
            steps.extend(leg["steps"])
            ride_total+=leg["ride_minutes"];walk_total+=leg["walk_minutes"];transfer_total+=leg["transfers"]
            reference_schedule_used = reference_schedule_used or leg.get("reference_schedule_used", False)
            transfer_rules_applied += int(leg.get("gtfs_transfer_rules_applied", 0))
            current_time=datetime.fromisoformat(leg["arrival"])
            summaries.append({"from":a.name,"to":b.name,"arrival":leg["arrival"],"lines":leg["lines"],"ride_minutes":leg["ride_minutes"],"walk_minutes":leg["walk_minutes"],"transfers":leg["transfers"]})
            if idx < len(waypoints)-2:
                stay=waypoints[idx+1].stay_minutes
                if stay>0:
                    steps.append({"mode":"stay","at":b.name,"minutes":stay,"point":[b.lat,b.lon]})
                    current_time+=timedelta(minutes=stay)
        return {"current":current_time,"steps":steps,"summaries":summaries,"ride":ride_total,"walk":walk_total,"transfers":transfer_total,"reference_schedule_used":reference_schedule_used,"gtfs_transfer_rules_applied":transfer_rules_applied}
    chosen=None
    # A required line may appear in any leg. Try each possible leg instead of forcing it on every leg.
    attempts=range(len(waypoints)-1) if req.required_route else [None]
    for required_leg in attempts:
        candidate=build_itinerary(required_leg)
        if candidate is None: continue
        lines=[str(s.get("route", "")) for s in candidate["steps"] if s.get("mode") in ("bus", "rail")]
        if req.required_route and not any(req.required_route.lower() in x.lower() for x in lines):
            continue
        if chosen is None or candidate["current"] < chosen["current"]:
            chosen=candidate
    if chosen is None:
        if req.required_route:
            raise HTTPException(404, f"'{req.required_route}' 노선을 포함하는 전체 경로를 찾지 못했습니다. 노선명/번호 또는 GTFS 제공 지역을 확인하세요.")
        raise HTTPException(404, "선택한 구간의 대중교통 경로를 찾지 못했습니다. 해당 지역 GTFS가 있는지, 정류장까지 허용 도보 거리를 늘릴 수 있는지 확인하세요.")
    current=chosen["current"];all_steps=chosen["steps"];leg_summaries=chosen["summaries"]
    ride=chosen["ride"];walk=chosen["walk"];transfers=chosen["transfers"]
    total=int(round((current-depart).total_seconds()/60))
    stay_total=sum(w.stay_minutes for w in waypoints[1:-1])
    wait_total=max(0,total-ride-walk-stay_total)
    reference_schedule_used=bool(chosen.get("reference_schedule_used"))
    transfer_rules_applied=int(chosen.get("gtfs_transfer_rules_applied",0))
    notice=("현재 요청일에 유효한 시간표가 없어 과거 기준일의 같은 요일 시간표를 참고 계산했습니다. 실제 운행·휴일 운행·배차간격·실시간 지연을 보장하지 않습니다." if reference_schedule_used else "GTFS 정적 시간표 기반 계산입니다. 실시간 지연·교통상황은 반영되지 않을 수 있습니다.")
    if transfer_rules_applied:
        notice += f" GTFS 환승 규칙 {transfer_rules_applied}건을 적용했습니다."
    return {"status":"ok","source":"GTFS static schedule","schedule_quality":"reference_weekday" if reference_schedule_used else "calendar_valid",
            "depart_at":depart.isoformat(),"arrive_at":current.isoformat(),
            "total_minutes":total,"ride_minutes":ride,"walk_minutes":walk,"stay_minutes":stay_total,"wait_minutes":wait_total,
            "transfer_count":transfers,"lines":list(dict.fromkeys(s["route"] for s in all_steps if s["mode"] in ("bus", "rail"))),
            "steps":all_steps,"legs":leg_summaries,"data_updated_at":datetime.now(TZ).isoformat(),
            "notice":notice}


@app.get("/projects")
async def list_projects(request: Request):
    require_durable_database()
    claims = require_user(request)
    with closing(db()) as con:
        rows = con.execute("SELECT p.project_id,p.name,p.description,p.owner_sub,m.role,"
                           "(SELECT COUNT(*) FROM project_members x WHERE x.project_id=p.project_id),"
                           "(SELECT COUNT(*) FROM project_routes r WHERE r.project_id=p.project_id),p.created_at,p.updated_at "
                           "FROM projects p JOIN project_members m ON m.project_id=p.project_id "
                           "WHERE m.user_sub=? AND p.archived_at IS NULL ORDER BY p.updated_at DESC",
                           (str(claims["sub"]),)).fetchall()
    return {"projects": [_project_list_row(row) for row in rows], "limits": {"projects_per_owner": 5, "members_per_project": 10, "routes_per_project": 100}}


@app.post("/projects")
async def create_project(body: ProjectCreateRequest, request: Request):
    _require_same_origin(request)
    require_durable_database()
    claims = require_user(request)
    project_id, now = uuid.uuid4().hex, datetime.now(TZ).isoformat()
    with closing(db()) as con:
        _lock_user(con, str(claims["sub"]))
        count = con.execute("SELECT COUNT(*) FROM projects WHERE owner_sub=? AND archived_at IS NULL", (str(claims["sub"]),)).fetchone()[0]
        if int(count) >= 5:
            raise HTTPException(429, "무료 기본 한도에서는 프로젝트를 최대 5개까지 만들 수 있습니다.")
        con.execute("INSERT INTO projects(project_id,owner_sub,name,description,created_at,updated_at) VALUES(?,?,?,?,?,?)",
                    (project_id, str(claims["sub"]), body.name.strip(), body.description.strip(), now, now))
        con.execute("INSERT INTO project_members(project_id,user_sub,email,role,invited_by,joined_at) VALUES(?,?,?,?,?,?)",
                    (project_id, str(claims["sub"]), str(claims.get("email", "")), "owner", str(claims["sub"]), now))
        con.commit()
    return {"ok": True, "project_id": project_id, "name": body.name.strip(), "role": "owner"}


@app.get("/projects/{project_id}")
async def get_project(project_id: str, request: Request):
    require_durable_database()
    claims = require_user(request)
    with closing(db()) as con:
        role = _project_member(con, project_id, claims)
        row = con.execute("SELECT project_id,name,description,owner_sub,created_at,updated_at FROM projects WHERE project_id=?", (project_id,)).fetchone()
        return {"project": {"project_id": row[0], "name": row[1], "description": row[2], "owner_sub": row[3],
                            "created_at": row[4], "updated_at": row[5], "role": role}}


@app.patch("/projects/{project_id}")
async def update_project(project_id: str, body: ProjectUpdateRequest, request: Request):
    _require_same_origin(request)
    require_durable_database()
    claims = require_user(request)
    with closing(db()) as con:
        _project_member(con, project_id, claims, ("owner",))
        con.execute("UPDATE projects SET name=?,description=?,updated_at=? WHERE project_id=?",
                    (body.name.strip(), body.description.strip(), datetime.now(TZ).isoformat(), project_id))
        con.commit()
    return {"ok": True}


@app.delete("/projects/{project_id}")
async def archive_project(project_id: str, request: Request):
    _require_same_origin(request)
    require_durable_database()
    claims = require_user(request)
    with closing(db()) as con:
        _project_member(con, project_id, claims, ("owner",))
        con.execute("UPDATE projects SET archived_at=?,updated_at=? WHERE project_id=?",
                    (datetime.now(TZ).isoformat(), datetime.now(TZ).isoformat(), project_id))
        con.commit()
    return {"ok": True, "archived": True}


@app.get("/projects/{project_id}/members")
async def list_project_members(project_id: str, request: Request):
    require_durable_database()
    claims = require_user(request)
    with closing(db()) as con:
        _project_member(con, project_id, claims)
        rows = con.execute("SELECT user_sub,email,role,joined_at FROM project_members WHERE project_id=? ORDER BY CASE role WHEN 'owner' THEN 0 WHEN 'editor' THEN 1 ELSE 2 END,joined_at",
                           (project_id,)).fetchall()
    return {"members": [{"user_sub": r[0], "email": r[1], "role": r[2], "joined_at": r[3]} for r in rows]}


@app.post("/projects/{project_id}/invites")
async def create_project_invite(project_id: str, body: ProjectInviteRequest, request: Request):
    _require_same_origin(request)
    require_durable_database()
    claims = require_user(request)
    if not invite_email_configured():
        raise HTTPException(503, "프로젝트 초대 메일이 아직 설정되지 않았습니다. 운영 서버에 RESEND_API_KEY와 인증된 INVITE_FROM_EMAIL을 등록해 주세요.")
    recipient = _normalise_email(body.email)
    now = datetime.now(TZ)
    now_iso = now.isoformat()
    raw_token = secrets.token_urlsafe(32)
    invite_id = uuid.uuid4().hex
    event_id = uuid.uuid4().hex
    expires_at = (now + timedelta(days=7)).isoformat()
    with closing(db()) as con:
        _project_member(con, project_id, claims, ("owner",))
        _lock_project(con, project_id)
        _lock_invite_email_quota(con)
        if _invite_email_quota_count(con, now) >= INVITE_EMAIL_DAILY_LIMIT:
            raise HTTPException(429, "오늘의 프로젝트 초대 메일 한도에 도달했습니다. 무료 이메일 한도 보호를 위해 내일 다시 시도해 주세요.")
        member_count = int(con.execute("SELECT COUNT(*) FROM project_members WHERE project_id=?", (project_id,)).fetchone()[0])
        if member_count >= 10:
            raise HTTPException(429, "무료 기본 한도에서는 프로젝트당 최대 10명까지 참여할 수 있습니다.")
        pending = int(con.execute("SELECT COUNT(*) FROM project_invites WHERE project_id=? AND accepted_at IS NULL AND revoked_at IS NULL AND expires_at>?",
                                  (project_id, now_iso)).fetchone()[0])
        if pending >= 10:
            raise HTTPException(429, "프로젝트당 대기 중인 초대는 최대 10개까지 만들 수 있습니다.")
        existing = con.execute("SELECT 1 FROM project_members WHERE project_id=? AND lower(email)=? LIMIT 1",
                               (project_id, recipient)).fetchone()
        if existing:
            raise HTTPException(409, "해당 이메일은 이미 프로젝트 구성원입니다.")
        con.execute("INSERT INTO project_invites(invite_id,project_id,invite_email,role,token_hash,created_by,created_at,expires_at,email_status,send_attempts,current_email_event_id) VALUES(?,?,?,?,?,?,?,?,?,?,?)",
                    (invite_id, project_id, recipient, body.role, _hash_capability(raw_token),
                     str(claims["sub"]), now_iso, expires_at, "sending", 1, event_id))
        con.execute("INSERT INTO project_invite_email_events(event_id,invite_id,project_id,recipient_email,provider,status,actor_sub,created_at) VALUES(?,?,?,?,?,?,?,?)",
                    (event_id, invite_id, project_id, recipient, "resend", "sending", str(claims["sub"]), now_iso))
        project = con.execute("SELECT name FROM projects WHERE project_id=?", (project_id,)).fetchone()
        con.commit()
    invite_url = _effective_origin(request) + "/#invite=" + raw_token
    try:
        message_id = await _send_project_invite_email(
            recipient=recipient, project_name=str(project[0]), role=body.role,
            invite_url=invite_url, expires_at=expires_at, idempotency_key=f"broute-invite-{event_id}")
    except Exception as exc:
        error_code = str(exc)[:60] if isinstance(exc, RuntimeError) else "email_send_failed"
        _record_invite_email_result(event_id, invite_id, status="failed", now=datetime.now(TZ).isoformat(), error_code=error_code)
        raise HTTPException(502, "초대 메일을 전송하지 못했습니다. 발신 도메인 인증·Resend API 키·일일 한도를 확인한 뒤 재전송해 주세요.") from exc
    accepted_at_provider = datetime.now(TZ).isoformat()
    _record_invite_email_result(event_id, invite_id, status="accepted", now=accepted_at_provider, message_id=message_id)
    return {"ok": True, "invite_id": invite_id, "project_name": str(project[0]),
            "email": recipient, "role": body.role, "expires_at": expires_at,
            "email_status": "accepted", "provider": "resend",
            "message": "초대 메일 발송 요청이 접수되었습니다. 받는 사람이 메일의 '프로젝트 참가하기' 버튼을 눌러 로그인한 뒤 수락하면 참여가 완료됩니다."}


@app.get("/projects/{project_id}/invites")
async def list_project_invites(project_id: str, request: Request):
    require_durable_database()
    claims = require_user(request)
    with closing(db()) as con:
        _project_member(con, project_id, claims, ("owner",))
        rows = con.execute("SELECT invite_id,invite_email,role,created_at,expires_at,accepted_at,revoked_at,email_status,email_sent_at,email_error_code,send_attempts FROM project_invites WHERE project_id=? ORDER BY created_at DESC LIMIT 50",
                           (project_id,)).fetchall()
    return {"invites": [{"invite_id":r[0],"email":r[1],"role":r[2],"created_at":r[3],"expires_at":r[4],
                         "accepted_at":r[5],"revoked_at":r[6],"email_status":r[7],"email_sent_at":r[8],
                         "email_error_code":r[9],"send_attempts":r[10]} for r in rows]}


@app.post("/projects/{project_id}/invites/{invite_id}/resend")
async def resend_project_invite(project_id: str, invite_id: str, request: Request):
    _require_same_origin(request)
    require_durable_database()
    claims = require_user(request)
    if not invite_email_configured():
        raise HTTPException(503, "프로젝트 초대 메일 설정이 없습니다.")
    now = datetime.now(TZ)
    now_iso = now.isoformat()
    raw_token = secrets.token_urlsafe(32)
    event_id = uuid.uuid4().hex
    expires_at = (now + timedelta(days=7)).isoformat()
    with closing(db()) as con:
        _project_member(con, project_id, claims, ("owner",))
        _lock_project(con, project_id)
        _lock_invite_email_quota(con)
        if _invite_email_quota_count(con, now) >= INVITE_EMAIL_DAILY_LIMIT:
            raise HTTPException(429, "오늘의 초대 메일 한도에 도달했습니다.")
        row = con.execute("SELECT invite_email,role,accepted_at,revoked_at FROM project_invites WHERE project_id=? AND invite_id=?",
                          (project_id, invite_id)).fetchone()
        if not row:
            raise HTTPException(404, "초대 기록을 찾을 수 없습니다.")
        if row[2] or row[3]:
            raise HTTPException(410, "수락되었거나 취소된 초대는 재전송할 수 없습니다.")
        project = con.execute("SELECT name FROM projects WHERE project_id=?", (project_id,)).fetchone()
        con.execute("UPDATE project_invites SET token_hash=?,expires_at=?,email_status='sending',email_message_id='',email_sent_at=NULL,email_error_code='',send_attempts=send_attempts+1,current_email_event_id=? WHERE invite_id=?",
                    (_hash_capability(raw_token), expires_at, event_id, invite_id))
        con.execute("INSERT INTO project_invite_email_events(event_id,invite_id,project_id,recipient_email,provider,status,actor_sub,created_at) VALUES(?,?,?,?,?,?,?,?)",
                    (event_id, invite_id, project_id, str(row[0]), "resend", "sending", str(claims["sub"]), now_iso))
        con.commit()
    invite_url = _effective_origin(request) + "/#invite=" + raw_token
    try:
        message_id = await _send_project_invite_email(
            recipient=str(row[0]), project_name=str(project[0]), role=str(row[1]),
            invite_url=invite_url, expires_at=expires_at, idempotency_key=f"broute-invite-{event_id}")
    except Exception as exc:
        error_code = str(exc)[:60] if isinstance(exc, RuntimeError) else "email_send_failed"
        _record_invite_email_result(event_id, invite_id, status="failed", now=datetime.now(TZ).isoformat(), error_code=error_code)
        raise HTTPException(502, "초대 메일 재전송에 실패했습니다. 발신 도메인과 API 설정을 확인해 주세요.") from exc
    _record_invite_email_result(event_id, invite_id, status="accepted", now=datetime.now(TZ).isoformat(), message_id=message_id)
    return {"ok": True, "invite_id": invite_id, "email": str(row[0]), "email_status": "accepted",
            "expires_at": expires_at, "message": "새 초대 메일 발송 요청을 접수했습니다. 이전 메일의 링크는 더 이상 사용할 수 없습니다."}


def _preview_project_invite_token(token: str):
    require_durable_database()
    if len(token) < 32 or len(token) > 160:
        raise HTTPException(404, "초대 링크를 찾을 수 없습니다.")
    with closing(db()) as con:
        row = con.execute("SELECT i.invite_email,i.role,i.expires_at,i.accepted_at,i.revoked_at,p.name,p.archived_at,i.email_status "
                           "FROM project_invites i JOIN projects p ON p.project_id=i.project_id WHERE i.token_hash=?",
                           (_hash_capability(token),)).fetchone()
    if not row or row[3] or row[4] or row[6] or datetime.fromisoformat(str(row[2])) <= datetime.now(TZ):
        raise HTTPException(410, "초대 링크가 만료·취소되었거나 이미 사용되었습니다.")
    if row[7] not in ("accepted", "sent", "delivered", "delivery_delayed", "legacy_link"):
        raise HTTPException(410, "초대 메일이 반송되었거나 전송에 실패했습니다. 프로젝트 소유자에게 재전송을 요청해 주세요.")
    return {"valid": True, "project_name": row[5], "invite_email": row[0], "role": row[1],
            "expires_at": row[2], "email_status": row[7],
            "mailbox_proof": "one_time_email_link", "requires_account_confirmation_if_mismatch": True}


@app.get("/project-invites/{token}")
async def preview_project_invite_legacy(token: str):
    # Kept temporarily for old 1.9x API clients. The 1.94 frontend uses the
    # POST body endpoint below so raw capability tokens are not URL-logged.
    return _preview_project_invite_token(token)


@app.post("/project-invites/preview")
async def preview_project_invite(body: ProjectInvitePreviewRequest, request: Request):
    _require_same_origin(request)
    return _preview_project_invite_token(body.token)


async def _accept_project_invite_token(token: str, body: ProjectInviteAcceptRequest, request: Request):
    _require_same_origin(request)
    require_durable_database()
    claims = require_user(request)
    if len(token) < 32 or len(token) > 160:
        raise HTTPException(404, "초대 링크를 찾을 수 없습니다.")
    now = datetime.now(TZ).isoformat()
    with closing(db()) as con:
        token_hash = _hash_capability(token)
        # First locate the parent project without a row lock. All project
        # membership/invite writers lock the project before the invite row;
        # keeping this order avoids PostgreSQL deadlocks against resend.
        initial = con.execute("SELECT invite_id,project_id FROM project_invites WHERE token_hash=?", (token_hash,)).fetchone()
        if not initial:
            raise HTTPException(410, "초대 링크가 만료·교체되었거나 이미 사용되었습니다.")
        invite_id = str(initial[0])
        project_id = str(initial[1])
        _lock_project(con, project_id)
        if DB_IS_POSTGRES:
            row = con.execute("SELECT invite_id,project_id,role,expires_at,accepted_at,revoked_at,invite_email,email_status,token_hash FROM project_invites WHERE invite_id=? FOR UPDATE",
                              (invite_id,)).fetchone()
        else:
            con.execute("UPDATE project_invites SET accepted_at=accepted_at WHERE invite_id=?", (invite_id,))
            row = con.execute("SELECT invite_id,project_id,role,expires_at,accepted_at,revoked_at,invite_email,email_status,token_hash FROM project_invites WHERE invite_id=?",
                              (invite_id,)).fetchone()
        if (not row or not hmac.compare_digest(str(row[8]), token_hash) or row[4] or row[5]
                or datetime.fromisoformat(str(row[3])) <= datetime.now(TZ)):
            raise HTTPException(410, "초대 링크가 만료·교체되었거나 이미 사용되었습니다.")
        if row[7] not in ("accepted", "legacy_link"):
            raise HTTPException(410, "메일 발송이 확인되지 않은 초대입니다.")
        invited_email = _normalise_email(row[6])
        signed_in_email = _normalise_email(claims.get("email", ""))
        email_matches = bool(signed_in_email and hmac.compare_digest(signed_in_email, invited_email))
        # The one-time secret link delivered to the mailbox is the mailbox
        # proof. Provider email claims can be absent or mutable (notably
        # Microsoft), so they are not treated as proof of mailbox ownership.
        # If the signed-in B-ROUTE account differs, require an explicit choice
        # before attaching the project to that account.
        if not email_matches and not body.confirm_current_account:
            raise HTTPException(409, "초대 메일 버튼을 연 계정과 현재 로그인 계정의 이메일이 다릅니다. 현재 로그인 계정에 프로젝트 참여 권한을 부여하려면 화면의 확인 버튼을 눌러 주세요.")
        current_account_email = _normalise_email(claims.get("email", ""))
        if not current_account_email and not body.confirm_current_account:
            raise HTTPException(409, "현재 로그인 계정에 이메일 정보가 없습니다. 이 계정으로 참여하려면 화면에서 확인해 주세요.")
        project = con.execute("SELECT archived_at FROM projects WHERE project_id=?", (project_id,)).fetchone()
        if not project or project[0]:
            raise HTTPException(410, "프로젝트가 보관 처리되었습니다.")
        existing = con.execute("SELECT role FROM project_members WHERE project_id=? AND user_sub=?",
                               (project_id, str(claims["sub"]))).fetchone()
        if existing:
            raise HTTPException(409, "이미 프로젝트 구성원입니다.")
        members = int(con.execute("SELECT COUNT(*) FROM project_members WHERE project_id=?", (project_id,)).fetchone()[0])
        if members >= 10:
            raise HTTPException(429, "프로젝트 구성원 한도에 도달했습니다.")
        con.execute("INSERT INTO project_members(project_id,user_sub,email,role,invited_by,joined_at) VALUES(?,?,?,?,?,?)",
                    (project_id, str(claims["sub"]), str(claims.get("email", "")), str(row[2]), "invite", now))
        accepted = con.execute("UPDATE project_invites SET accepted_by=?,accepted_at=? WHERE invite_id=? AND accepted_at IS NULL AND revoked_at IS NULL",
                               (str(claims["sub"]), now, row[0]))
        if accepted.rowcount == 0:
            raise HTTPException(410, "초대 링크가 이미 사용되었습니다.")
        con.execute("UPDATE projects SET updated_at=? WHERE project_id=?", (now, project_id))
        con.commit()
    return {"ok": True, "project_id": project_id, "role": str(row[2]),
            "joined_account_email": str(claims.get("email", "")),
            "invited_email": invited_email}


@app.post("/project-invites/accept")
async def accept_project_invite(body: ProjectInviteAcceptRequest, request: Request):
    if not body.token:
        raise HTTPException(422, "초대 토큰이 필요합니다.")
    return await _accept_project_invite_token(body.token, body, request)


@app.post("/project-invites/{token}/accept")
async def accept_project_invite_legacy(token: str, body: ProjectInviteAcceptRequest, request: Request):
    # Compatibility endpoint for clients deployed before 1.94. New UI sends
    # the token in the POST body through /project-invites/accept.
    return await _accept_project_invite_token(token, body, request)


@app.delete("/projects/{project_id}/invites/{invite_id}")
async def revoke_project_invite(project_id: str, invite_id: str, request: Request):
    _require_same_origin(request)
    require_durable_database()
    claims = require_user(request)
    with closing(db()) as con:
        _project_member(con, project_id, claims, ("owner",))
        cur = con.execute("UPDATE project_invites SET revoked_at=? WHERE invite_id=? AND project_id=? AND accepted_at IS NULL AND revoked_at IS NULL",
                          (datetime.now(TZ).isoformat(), invite_id, project_id))
        if cur.rowcount == 0:
            raise HTTPException(404, "취소할 초대를 찾을 수 없습니다.")
        con.commit()
    return {"ok": True}


@app.patch("/projects/{project_id}/members/{member_sub:path}")
async def update_project_member(project_id: str, member_sub: str, body: ProjectRoleUpdateRequest, request: Request):
    _require_same_origin(request)
    require_durable_database()
    claims = require_user(request)
    with closing(db()) as con:
        _project_member(con, project_id, claims, ("owner",))
        row = con.execute("SELECT role FROM project_members WHERE project_id=? AND user_sub=?", (project_id, member_sub)).fetchone()
        if not row or row[0] == "owner":
            raise HTTPException(404, "변경할 구성원을 찾을 수 없습니다.")
        con.execute("UPDATE project_members SET role=? WHERE project_id=? AND user_sub=?", (body.role, project_id, member_sub))
        con.commit()
    return {"ok": True, "role": body.role}


@app.delete("/projects/{project_id}/members/{member_sub:path}")
async def remove_project_member(project_id: str, member_sub: str, request: Request):
    _require_same_origin(request)
    require_durable_database()
    claims = require_user(request)
    with closing(db()) as con:
        role = _project_member(con, project_id, claims)
        row = con.execute("SELECT role FROM project_members WHERE project_id=? AND user_sub=?", (project_id, member_sub)).fetchone()
        if not row or row[0] == "owner":
            raise HTTPException(404, "삭제할 구성원을 찾을 수 없습니다.")
        if role != "owner" and str(claims["sub"]) != member_sub:
            raise HTTPException(403, "총괄자 또는 본인만 구성원을 제거할 수 있습니다.")
        con.execute("DELETE FROM project_members WHERE project_id=? AND user_sub=?", (project_id, member_sub))
        con.commit()
    return {"ok": True}


@app.get("/projects/{project_id}/routes")
async def list_project_routes(project_id: str, request: Request):
    require_durable_database()
    claims = require_user(request)
    with closing(db()) as con:
        role = _project_member(con, project_id, claims)
        rows = con.execute("SELECT route_id,title,version,created_by,updated_by,created_at,updated_at FROM project_routes WHERE project_id=? ORDER BY updated_at DESC",
                           (project_id,)).fetchall()
    return {"routes": [{"route_id":r[0],"title":r[1],"version":r[2],"created_by":r[3],"updated_by":r[4],"created_at":r[5],"updated_at":r[6]} for r in rows], "role": role}


@app.post("/projects/{project_id}/routes")
async def create_project_route(project_id: str, body: ProjectRouteCreateRequest, request: Request):
    _require_same_origin(request)
    require_durable_database()
    claims = require_user(request)
    _validate_project_route(body.plan, body.result)
    now, route_id = datetime.now(TZ).isoformat(), uuid.uuid4().hex
    with closing(db()) as con:
        _project_member(con, project_id, claims, ("owner", "editor"))
        _lock_project(con, project_id)
        count = int(con.execute("SELECT COUNT(*) FROM project_routes WHERE project_id=?", (project_id,)).fetchone()[0])
        if count >= 100:
            raise HTTPException(429, "무료 기본 한도에서는 프로젝트당 경로를 최대 100개까지 보관할 수 있습니다.")
        con.execute("INSERT INTO project_routes(route_id,project_id,title,plan_json,result_json,version,created_by,updated_by,created_at,updated_at) VALUES(?,?,?,?,?,1,?,?,?,?)",
                    (route_id, project_id, body.title.strip(), json.dumps(body.plan, ensure_ascii=False),
                     json.dumps(body.result, ensure_ascii=False), str(claims["sub"]), str(claims["sub"]), now, now))
        con.execute("UPDATE projects SET updated_at=? WHERE project_id=?", (now, project_id))
        con.commit()
    return {"ok": True, "route_id": route_id, "version": 1}


@app.get("/projects/{project_id}/routes/{route_id}")
async def get_project_route(project_id: str, route_id: str, request: Request):
    require_durable_database()
    claims = require_user(request)
    with closing(db()) as con:
        _project_member(con, project_id, claims)
        row = con.execute("SELECT title,plan_json,result_json,version,created_by,updated_by,created_at,updated_at FROM project_routes WHERE project_id=? AND route_id=?",
                          (project_id, route_id)).fetchone()
    if not row:
        raise HTTPException(404, "프로젝트 경로를 찾을 수 없습니다.")
    return {"route": {"route_id": route_id, "title": row[0], "plan": json.loads(row[1]), "result": json.loads(row[2]),
                       "version": row[3], "created_by": row[4], "updated_by": row[5], "created_at": row[6], "updated_at": row[7]}}


@app.put("/projects/{project_id}/routes/{route_id}")
async def update_project_route(project_id: str, route_id: str, body: ProjectRouteUpdateRequest, request: Request):
    _require_same_origin(request)
    require_durable_database()
    claims = require_user(request)
    _validate_project_route(body.plan, body.result)
    now = datetime.now(TZ).isoformat()
    with closing(db()) as con:
        _project_member(con, project_id, claims, ("owner", "editor"))
        # Serialize updates to the project before comparing versions. PostgreSQL
        # takes a row lock; SQLite takes a write reservation through _lock_project.
        _lock_project(con, project_id)
        row = con.execute("SELECT title,plan_json,result_json,version,updated_by FROM project_routes WHERE project_id=? AND route_id=?",
                          (project_id, route_id)).fetchone()
        if not row:
            raise HTTPException(404, "프로젝트 경로를 찾을 수 없습니다.")
        current_version = int(row[3])
        if current_version != body.expected_version:
            raise HTTPException(409, f"다른 구성원이 먼저 수정했습니다. 현재 버전은 {current_version}입니다. 최신 경로를 다시 열고 수정해 주세요.")
        next_version = current_version + 1
        con.execute("INSERT INTO project_route_versions(version_id,project_id,route_id,version,title,plan_json,result_json,saved_by,created_at) VALUES(?,?,?,?,?,?,?,?,?)",
                    (uuid.uuid4().hex, project_id, route_id, current_version, row[0], row[1], row[2], str(row[4]), now))
        updated = con.execute("UPDATE project_routes SET title=?,plan_json=?,result_json=?,version=?,updated_by=?,updated_at=? WHERE project_id=? AND route_id=? AND version=?",
                    (body.title.strip(), json.dumps(body.plan, ensure_ascii=False), json.dumps(body.result, ensure_ascii=False),
                     next_version, str(claims["sub"]), now, project_id, route_id, current_version))
        if updated.rowcount != 1:
            raise HTTPException(409, "경로가 동시에 변경되었습니다. 최신 경로를 다시 열어 주세요.")
        con.execute("UPDATE projects SET updated_at=? WHERE project_id=?", (now, project_id))
        con.commit()
    return {"ok": True, "route_id": route_id, "version": next_version}


@app.delete("/projects/{project_id}/routes/{route_id}")
async def delete_project_route(project_id: str, route_id: str, request: Request):
    _require_same_origin(request)
    require_durable_database()
    claims = require_user(request)
    with closing(db()) as con:
        _project_member(con, project_id, claims, ("owner", "editor"))
        cur = con.execute("DELETE FROM project_routes WHERE project_id=? AND route_id=?", (project_id, route_id))
        if cur.rowcount == 0:
            raise HTTPException(404, "삭제할 프로젝트 경로를 찾을 수 없습니다.")
        con.commit()
    return {"ok": True}


@app.get("/projects/{project_id}/routes/{route_id}/versions")
async def list_project_route_versions(project_id: str, route_id: str, request: Request):
    require_durable_database()
    claims = require_user(request)
    with closing(db()) as con:
        _project_member(con, project_id, claims)
        exists = con.execute("SELECT 1 FROM project_routes WHERE project_id=? AND route_id=?", (project_id, route_id)).fetchone()
        if not exists:
            raise HTTPException(404, "프로젝트 경로를 찾을 수 없습니다.")
        rows = con.execute("SELECT version_id,version,title,saved_by,created_at FROM project_route_versions WHERE project_id=? AND route_id=? ORDER BY version DESC LIMIT 30",
                           (project_id, route_id)).fetchall()
    return {"versions": [{"version_id":r[0],"version":r[1],"title":r[2],"saved_by":r[3],"created_at":r[4]} for r in rows]}


@app.post("/projects/{project_id}/routes/{route_id}/versions/{version_id}/restore")
async def restore_project_route_version(project_id: str, route_id: str, version_id: str, request: Request):
    _require_same_origin(request)
    require_durable_database()
    claims = require_user(request)
    now = datetime.now(TZ).isoformat()
    with closing(db()) as con:
        _project_member(con, project_id, claims, ("owner", "editor"))
        _lock_project(con, project_id)
        current = con.execute("SELECT title,plan_json,result_json,version,updated_by FROM project_routes WHERE project_id=? AND route_id=?",
                              (project_id, route_id)).fetchone()
        old = con.execute("SELECT title,plan_json,result_json,version FROM project_route_versions WHERE version_id=? AND project_id=? AND route_id=?",
                          (version_id, project_id, route_id)).fetchone()
        if not current or not old:
            raise HTTPException(404, "복구할 경로 버전을 찾을 수 없습니다.")
        next_version = int(current[3]) + 1
        con.execute("INSERT INTO project_route_versions(version_id,project_id,route_id,version,title,plan_json,result_json,saved_by,created_at) VALUES(?,?,?,?,?,?,?,?,?)",
                    (uuid.uuid4().hex, project_id, route_id, int(current[3]), current[0], current[1], current[2], str(current[4]), now))
        con.execute("UPDATE project_routes SET title=?,plan_json=?,result_json=?,version=?,updated_by=?,updated_at=? WHERE project_id=? AND route_id=?",
                    (old[0], old[1], old[2], next_version, str(claims["sub"]), now, project_id, route_id))
        con.commit()
    return {"ok": True, "restored_from_version": int(old[3]), "new_version": next_version}


@app.post("/projects/{project_id}/routes/{route_id}/shares")
async def create_project_route_share(project_id: str, route_id: str, body: ProjectShareRequest, request: Request):
    _require_same_origin(request)
    require_durable_database()
    claims = require_user(request)
    token, share_id, now = secrets.token_urlsafe(32), uuid.uuid4().hex, datetime.now(TZ)
    expires = (now + timedelta(days=body.expires_days)).isoformat()
    with closing(db()) as con:
        _project_member(con, project_id, claims, ("owner", "editor"))
        route = con.execute("SELECT 1 FROM project_routes WHERE project_id=? AND route_id=?", (project_id, route_id)).fetchone()
        if not route:
            raise HTTPException(404, "공유할 프로젝트 경로를 찾을 수 없습니다.")
        active = int(con.execute("SELECT COUNT(*) FROM project_route_shares WHERE project_id=? AND revoked_at IS NULL AND expires_at>?",
                                 (project_id, now.isoformat())).fetchone()[0])
        if active >= 100:
            raise HTTPException(429, "프로젝트당 활성 공유 링크는 최대 100개까지 만들 수 있습니다.")
        con.execute("INSERT INTO project_route_shares(share_id,project_id,route_id,token_hash,created_by,created_at,expires_at,max_views) VALUES(?,?,?,?,?,?,?,?)",
                    (share_id, project_id, route_id, _hash_capability(token), str(claims["sub"]), now.isoformat(), expires, body.max_views))
        con.commit()
    return {"ok": True, "share_id": share_id, "url": _effective_origin(request) + "/?project_share=" + token,
            "read_only": True, "expires_at": expires, "max_views": body.max_views}


@app.get("/public/project-shares/{token}")
async def get_public_project_route_share(token: str):
    require_durable_database()
    if len(token) < 32 or len(token) > 160:
        raise HTTPException(404, "공유 경로를 찾을 수 없습니다.")
    with closing(db()) as con:
        row = con.execute("SELECT s.share_id,s.project_id,s.route_id,s.expires_at,s.revoked_at,s.view_count,s.max_views,"
                           "r.title,r.plan_json,r.result_json,p.name,p.archived_at FROM project_route_shares s "
                           "JOIN project_routes r ON r.route_id=s.route_id AND r.project_id=s.project_id "
                           "JOIN projects p ON p.project_id=s.project_id WHERE s.token_hash=?",
                           (_hash_capability(token),)).fetchone()
        if not row or row[4] or row[11] or datetime.fromisoformat(str(row[3])) <= datetime.now(TZ) or int(row[5]) >= int(row[6]):
            raise HTTPException(410, "공유 링크가 만료·취소되었거나 열람 한도에 도달했습니다.")
        updated = con.execute("UPDATE project_route_shares SET view_count=view_count+1 WHERE share_id=? AND view_count<max_views", (row[0],))
        if updated.rowcount == 0:
            raise HTTPException(410, "공유 링크의 열람 한도에 도달했습니다.")
        con.commit()
    return {"read_only": True, "project_name": row[10], "title": row[7], "plan": json.loads(row[8]),
            "result": json.loads(row[9]), "expires_at": row[3], "views_remaining": max(0, int(row[6])-int(row[5])-1)}


@app.delete("/projects/{project_id}/routes/{route_id}/shares/{share_id}")
async def revoke_project_route_share(project_id: str, route_id: str, share_id: str, request: Request):
    _require_same_origin(request)
    require_durable_database()
    claims = require_user(request)
    with closing(db()) as con:
        _project_member(con, project_id, claims, ("owner", "editor"))
        cur = con.execute("UPDATE project_route_shares SET revoked_at=? WHERE share_id=? AND project_id=? AND route_id=? AND revoked_at IS NULL",
                          (datetime.now(TZ).isoformat(), share_id, project_id, route_id))
        if cur.rowcount == 0:
            raise HTTPException(404, "취소할 공유 링크를 찾을 수 없습니다.")
        con.commit()
    return {"ok": True}


@app.post("/shares")
async def create_share(body: ShareRequest, request: Request):
    _require_same_origin(request)
    require_durable_database()
    claims = require_user(request)
    _validate_project_route(body.plan, body.result)
    token = secrets.token_urlsafe(32)
    share_id = uuid.uuid4().hex
    now = datetime.now(TZ)
    expires = (now + timedelta(days=body.expires_days)).isoformat()
    with closing(db()) as con:
        _lock_user(con, str(claims["sub"]))
        count = con.execute("SELECT COUNT(*) FROM route_shares WHERE owner_sub=? AND revoked_at IS NULL AND expires_at>?",
                            (str(claims["sub"]), now.isoformat())).fetchone()[0]
        if int(count) >= 100:
            raise HTTPException(429, "활성 경로 공유 링크는 계정당 최대 100개까지 만들 수 있습니다.")
        con.execute("INSERT INTO route_shares(share_id,token_hash,owner_sub,plan_json,result_json,created_at,expires_at,max_views) VALUES(?,?,?,?,?,?,?,?)",
                    (share_id, _hash_capability(token), str(claims["sub"]), json.dumps(body.plan, ensure_ascii=False),
                     json.dumps(body.result, ensure_ascii=False), now.isoformat(), expires, body.max_views))
        con.commit()
    url = _effective_origin(request) + "/?share=" + token
    return {"share_id": share_id, "share_token": token, "url": url, "read_only": True,
            "expires_at": expires, "max_views": body.max_views}


@app.get("/shares/{share_id}")
async def get_share(share_id: str):
    # Public links still depend on durable expiry/view counters; do not fall
    # back to an ephemeral local database in production.
    require_durable_database()
    # New public links use random bearer tokens stored only as SHA-256 hashes.
    token_hash = _hash_capability(share_id)
    with closing(db()) as con:
        row = con.execute("SELECT plan_json,result_json,expires_at,revoked_at,view_count,max_views FROM route_shares WHERE token_hash=?", (token_hash,)).fetchone()
        if row:
            if row[3] or datetime.fromisoformat(str(row[2])) <= datetime.now(TZ) or int(row[4]) >= int(row[5]):
                raise HTTPException(410, "공유 링크가 만료되었거나 열람 한도에 도달했습니다.")
            updated = con.execute("UPDATE route_shares SET view_count=view_count+1 WHERE token_hash=? AND view_count<max_views", (token_hash,))
            if updated.rowcount == 0:
                raise HTTPException(410, "공유 링크의 열람 한도에 도달했습니다.")
            con.commit()
            return {"plan": json.loads(row[0]), "result": json.loads(row[1]), "read_only": True,
                    "expires_at": row[2], "views_remaining": max(0, int(row[5])-int(row[4])-1)}
        legacy = con.execute("SELECT plan_json FROM shares WHERE share_id=?", (share_id,)).fetchone()
    if not legacy:
        raise HTTPException(404, "공유 경로를 찾을 수 없습니다.")
    return {"plan": json.loads(legacy[0]), "result": {}, "read_only": True, "legacy": True}


@app.delete("/shares/{share_id}")
async def revoke_share(share_id: str, request: Request):
    _require_same_origin(request)
    claims = require_user(request)
    require_durable_database()
    with closing(db()) as con:
        row = con.execute("SELECT owner_sub FROM route_shares WHERE share_id=?", (share_id,)).fetchone()
        if not row or str(row[0]) != str(claims["sub"]):
            raise HTTPException(404, "공유 링크를 찾을 수 없습니다.")
        con.execute("UPDATE route_shares SET revoked_at=? WHERE share_id=?", (datetime.now(TZ).isoformat(), share_id))
        con.commit()
    return {"ok": True}


@app.post("/feedback")
async def save_feedback(body: FeedbackRequest, request: Request):
    _require_same_origin(request)
    require_durable_database()
    claims = require_user(request)
    with closing(db()) as con:
        if not _setting_value(con, "feedback_enabled", True):
            raise HTTPException(503, "현재 문의 접수를 일시 중지했습니다.")
        fid=uuid.uuid4().hex
        payload=body.model_dump()
        con.execute("INSERT INTO feedback(feedback_id,payload_json,created_at,user_sub,user_email,status,admin_reply,reviewed_at) VALUES(?,?,?,?,?,?,?,?)",
                    (fid,json.dumps(payload,ensure_ascii=False),datetime.now(TZ).isoformat(),str(claims["sub"]),str(claims.get("email","")),"received","",None))
        con.commit()
    return {"ok":True,"feedback_id":fid,"status":"received"}


@app.get("/me/feedback")
async def my_feedback(request: Request):
    claims = require_user(request)
    with closing(db()) as con:
        rows=con.execute("SELECT feedback_id,payload_json,created_at,status,admin_reply,reviewed_at FROM feedback WHERE user_sub=? ORDER BY created_at DESC LIMIT 50",(str(claims["sub"]),)).fetchall()
    return {"feedback":[{"id":r[0],"payload":json.loads(r[1]),"created_at":r[2],"status":r[3],"admin_reply":r[4],"reviewed_at":r[5]} for r in rows]}


@app.get("/admin/feedback")
async def list_feedback(request: Request, limit: int = Query(default=100, ge=1, le=300)):
    _admin_session(request)
    with closing(db()) as con:
        rows=con.execute("SELECT feedback_id,payload_json,created_at,user_email,status,admin_reply,reviewed_at FROM feedback ORDER BY created_at DESC LIMIT ?",(limit,)).fetchall()
    return {"feedback":[{"id":r[0],"payload":json.loads(r[1]),"created_at":r[2],"user_email":r[3],"status":r[4],"admin_reply":r[5],"reviewed_at":r[6]} for r in rows]}


@app.patch("/admin/feedback/{feedback_id}")
async def update_feedback(feedback_id: str, body: FeedbackUpdateRequest, request: Request):
    _require_same_origin(request)
    actor = _admin_session(request)
    require_durable_database()
    with closing(db()) as con:
        row=con.execute("SELECT status,admin_reply FROM feedback WHERE feedback_id=?",(feedback_id,)).fetchone()
        if not row:
            raise HTTPException(404,"문의 내용을 찾을 수 없습니다.")
        before={"status":row[0],"admin_reply":row[1]}
        after={"status":body.status,"admin_reply":body.admin_reply.strip()}
        now=datetime.now(TZ).isoformat()
        con.execute("UPDATE feedback SET status=?,admin_reply=?,reviewed_at=? WHERE feedback_id=?",(body.status,body.admin_reply.strip(),now,feedback_id))
        _audit(con,actor,"feedback.update","feedback",feedback_id,before,after,"총괄자 문의 처리")
        con.commit()
    return {"ok":True,"feedback_id":feedback_id,"status":body.status}


ALLOWED_SETTINGS = {"cloud_quota_mb": (50, 1000), "max_cloud_file_mb": (1, 5)}
DEFAULT_SETTINGS = {"cloud_quota_mb": CLOUD_QUOTA_DEFAULT_MB, "max_cloud_file_mb": 5,
                    "maintenance_mode": False, "feedback_enabled": True, "route_search_enabled": True}


@app.get("/admin/settings")
async def get_admin_settings(request: Request):
    _admin_session(request)
    with closing(db()) as con:
        values={key:_setting_value(con,key,default) for key,default in DEFAULT_SETTINGS.items()}
        rows=con.execute("SELECT setting_key,updated_by,updated_at FROM app_settings").fetchall()
    metadata={r[0]:{"updated_by":r[1],"updated_at":r[2]} for r in rows}
    return {"settings":values,"metadata":metadata,"secret_settings_editable":False}


@app.patch("/admin/settings")
async def patch_admin_settings(body: AdminSettingsPatch, request: Request):
    _require_same_origin(request)
    actor=_admin_session(request)
    require_durable_database()
    if not body.values:
        raise HTTPException(400,"변경할 설정값이 없습니다.")
    validated={}
    for key,value in body.values.items():
        if key not in DEFAULT_SETTINGS:
            raise HTTPException(400,f"수정할 수 없는 설정 항목입니다: {key}")
        if key in ALLOWED_SETTINGS:
            lo,hi=ALLOWED_SETTINGS[key]
            if isinstance(value,bool) or not isinstance(value,int) or not lo<=value<=hi:
                raise HTTPException(400,f"{key} 값은 {lo}~{hi} 범위의 정수여야 합니다.")
        elif not isinstance(value,bool):
            raise HTTPException(400,f"{key} 값은 참/거짓이어야 합니다.")
        validated[key]=value
    with closing(db()) as con:
        for key,value in validated.items():
            before=_setting_value(con,key,DEFAULT_SETTINGS[key])
            con.execute("INSERT INTO app_settings(setting_key,value_json,updated_by,updated_at) VALUES(?,?,?,?) "
                        "ON CONFLICT(setting_key) DO UPDATE SET value_json=excluded.value_json,updated_by=excluded.updated_by,updated_at=excluded.updated_at",
                        (key,json.dumps(value),str(actor["sub"]),datetime.now(TZ).isoformat()))
            _audit(con,actor,"settings.update","setting",key,{"value":before},{"value":value},body.reason)
        con.commit()
    return {"ok":True,"updated":validated}


@app.get("/admin/audit")
async def get_admin_audit(request: Request, limit: int = Query(default=100, ge=1, le=300)):
    _admin_session(request)
    with closing(db()) as con:
        rows=con.execute("SELECT log_id,actor_email,action,target_type,target_id,before_json,after_json,reason,created_at FROM admin_audit_logs ORDER BY created_at DESC LIMIT ?",(limit,)).fetchall()
    return {"logs":[{"id":r[0],"actor_email":r[1],"action":r[2],"target_type":r[3],"target_id":r[4],
        "before":json.loads(r[5]) if r[5] else None,"after":json.loads(r[6]) if r[6] else None,"reason":r[7],"created_at":r[8]} for r in rows]}


@app.post("/admin/audit/{log_id}/rollback")
async def rollback_admin_setting(log_id: str, request: Request):
    _require_same_origin(request)
    actor=_admin_session(request)
    require_durable_database()
    with closing(db()) as con:
        row=con.execute("SELECT action,target_type,target_id,before_json,after_json FROM admin_audit_logs WHERE log_id=?",(log_id,)).fetchone()
        if not row or row[0]!="settings.update" or row[1]!="setting":
            raise HTTPException(400,"이 로그는 설정값 복구 대상이 아닙니다.")
        key=row[2]
        if key not in DEFAULT_SETTINGS:
            raise HTTPException(400,"허용되지 않은 설정 복구 대상입니다.")
        old=json.loads(row[3]) if row[3] else None
        current=_setting_value(con,key,DEFAULT_SETTINGS[key])
        restored=old.get("value") if old else DEFAULT_SETTINGS[key]
        if old is None:
            raise HTTPException(400,"초기 설정값이 없는 항목은 자동 복구할 수 없습니다.")
        con.execute("INSERT INTO app_settings(setting_key,value_json,updated_by,updated_at) VALUES(?,?,?,?) "
                    "ON CONFLICT(setting_key) DO UPDATE SET value_json=excluded.value_json,updated_by=excluded.updated_by,updated_at=excluded.updated_at",
                    (key,json.dumps(restored),str(actor["sub"]),datetime.now(TZ).isoformat()))
        _audit(con,actor,"settings.rollback","setting",key,{"value":current},{"value":restored},f"로그 {log_id} 기준 복구")
        con.commit()
    return {"ok":True,"setting":key,"restored_value":restored}


@app.get("/me/cloud-files")
async def list_cloud_files(request: Request):
    claims=require_user(request)
    require_durable_database()
    with closing(db()) as con:
        rows=con.execute("SELECT file_id,file_name,size_bytes,created_at FROM cloud_files WHERE owner_sub=? ORDER BY created_at DESC",(str(claims["sub"]),)).fetchall()
        used=con.execute("SELECT COALESCE(SUM(size_bytes),0) FROM cloud_files WHERE owner_sub=?",(str(claims["sub"]),)).fetchone()[0]
        quota=int(_setting_value(con,"cloud_quota_mb",CLOUD_QUOTA_DEFAULT_MB))*1024*1024
    return {"files":[{"id":r[0],"name":r[1],"size_bytes":r[2],"created_at":r[3]} for r in rows],"used_bytes":int(used),"quota_bytes":quota}


@app.post("/me/cloud-files")
async def upload_cloud_file(request: Request, file: UploadFile = File(...)):
    _require_same_origin(request)
    claims=require_user(request)
    require_durable_database()
    if not cos_is_configured():
        raise HTTPException(503,"총괄자가 COS 서버 Secret을 설정해야 클라우드 보관함을 사용할 수 있습니다.")
    with closing(db()) as con:
        max_bytes=int(_setting_value(con,"max_cloud_file_mb",5))*1024*1024
    data=await file.read(max_bytes+1)
    if len(data)>max_bytes:
        raise HTTPException(413,f"단일 .broute 파일은 {max_bytes//(1024*1024)}MB 이하만 업로드할 수 있습니다. 서버 업로드 안전 한도입니다.")
    try:
        payload=json.loads(data.decode("utf-8"))
    except Exception as exc:
        raise HTTPException(400,"올바른 UTF-8 JSON 파일이 아닙니다.") from exc
    if payload.get("format")!="B-ROUTE" or type(payload.get("schema_version")) is not int or payload["schema_version"] not in (1,):
        raise HTTPException(400,"지원하는 B-ROUTE 파일 형식이 아닙니다.")
    request_data=payload.get("request")
    def valid_file_point(point):
        if not isinstance(point,dict):
            return False
        try:
            lat=float(point.get("lat")); lon=float(point.get("lon"))
            return math.isfinite(lat) and math.isfinite(lon) and -90<=lat<=90 and -180<=lon<=180
        except (TypeError,ValueError):
            return False
    vias=request_data.get("vias",[]) if isinstance(request_data,dict) else None
    if not isinstance(request_data,dict) or not valid_file_point(request_data.get("origin")) or not valid_file_point(request_data.get("destination")) or not isinstance(vias,list) or not all(valid_file_point(point) for point in vias):
        raise HTTPException(400,"경로 파일의 출발지·도착지·경유지 좌표가 올바르지 않습니다.")
    name=safe_filename(file.filename or "route.broute")
    sub=str(claims["sub"])
    owner_prefix=hashlib.sha256(sub.encode("utf-8")).hexdigest()[:24]
    file_id=uuid.uuid4().hex
    object_key=f"broute-users/{owner_prefix}/{file_id}.broute"
    with closing(db()) as con:
        # Lock a per-user row on PostgreSQL so simultaneous uploads cannot bypass the quota check.
        if DB_IS_POSTGRES:
            con.execute("SELECT user_sub FROM users WHERE user_sub=? FOR UPDATE",(sub,)).fetchone()
        used=con.execute("SELECT COALESCE(SUM(size_bytes),0) FROM cloud_files WHERE owner_sub=?",(sub,)).fetchone()[0]
        quota=int(_setting_value(con,"cloud_quota_mb",CLOUD_QUOTA_DEFAULT_MB))*1024*1024
        if int(used)+len(data)>quota:
            raise HTTPException(413,"클라우드 보관함 용량(계정당 설정 한도)을 초과합니다. 기존 파일을 삭제한 뒤 다시 시도해 주세요.")
        client=None
        object_uploaded=False
        try:
            client=cos_client()
            client.put_object(Bucket=os.environ["COS_BUCKET"].strip(),Key=object_key,Body=data,
                              ContentType="application/json; charset=utf-8",EnableMD5=True)
            object_uploaded=True
            con.execute("INSERT INTO cloud_files(file_id,owner_sub,file_name,object_key,size_bytes,content_type,created_at) VALUES(?,?,?,?,?,?,?)",
                        (file_id,sub,name,object_key,len(data),"application/json",datetime.now(TZ).isoformat()))
            con.commit()
        except HTTPException:
            raise
        except Exception as exc:
            if object_uploaded and client is not None:
                try:
                    client.delete_object(Bucket=os.environ["COS_BUCKET"].strip(),Key=object_key)
                except Exception:
                    pass  # A later orphan-object cleanup task can remove a failed compensation.
            raise HTTPException(502,"COS 파일 저장 또는 메타데이터 기록에 실패했습니다. 잠시 후 다시 시도해 주세요.") from exc
    return {"ok":True,"file":{"id":file_id,"name":name,"size_bytes":len(data)}}


@app.get("/me/cloud-files/{file_id}/download")
async def cloud_file_download(file_id: str, request: Request):
    claims=require_user(request)
    require_durable_database()
    if not cos_is_configured():
        raise HTTPException(503,"클라우드 저장소가 설정되지 않았습니다.")
    with closing(db()) as con:
        row=con.execute("SELECT file_name,object_key FROM cloud_files WHERE file_id=? AND owner_sub=?",(file_id,str(claims["sub"]))).fetchone()
    if not row:
        raise HTTPException(404,"파일을 찾을 수 없습니다.")
    try:
        url=cos_client().get_presigned_url(Method="GET",Bucket=os.environ["COS_BUCKET"].strip(),Key=row[1],Expired=300)
    except Exception as exc:
        raise HTTPException(502,"다운로드 링크를 만들지 못했습니다.") from exc
    return {"url":url,"name":row[0],"expires_in_seconds":300}


@app.delete("/me/cloud-files/{file_id}")
async def delete_cloud_file(file_id: str, request: Request):
    _require_same_origin(request)
    claims=require_user(request)
    require_durable_database()
    with closing(db()) as con:
        row=con.execute("SELECT object_key FROM cloud_files WHERE file_id=? AND owner_sub=?",(file_id,str(claims["sub"]))).fetchone()
        if not row:
            raise HTTPException(404,"파일을 찾을 수 없습니다.")
        try:
            cos_client().delete_object(Bucket=os.environ["COS_BUCKET"].strip(),Key=row[0])
        except Exception as exc:
            raise HTTPException(502,"클라우드 파일 삭제에 실패했습니다. 보관함 기록은 유지됩니다.") from exc
        con.execute("DELETE FROM cloud_files WHERE file_id=? AND owner_sub=?",(file_id,str(claims["sub"])))
        con.commit()
    return {"ok":True,"deleted":file_id}

