"""Verify that existing 1.92 project route-history databases migrate safely to 1.93."""
from __future__ import annotations

import importlib.util
import os
import sqlite3
import sys
import tempfile
from pathlib import Path

TMP = Path(tempfile.mkdtemp(prefix="broute193-schema-migration-"))
DB = TMP / "legacy.sqlite3"
os.environ.update({
    "APP_ENV": "development",
    "DATA_DIR": str(TMP / "data"),
    "DATABASE_PATH": str(DB),
    "APP_ORIGIN": "https://testserver",
    "SESSION_SECRET": "migration-test-secret-" + "x" * 32,
})

# Simulate the 1.92 table shape: no title column in project_route_versions.
with sqlite3.connect(DB) as legacy:
    legacy.execute("""CREATE TABLE project_route_versions (
        version_id TEXT PRIMARY KEY, project_id TEXT NOT NULL, route_id TEXT NOT NULL,
        version INTEGER NOT NULL, plan_json TEXT NOT NULL,
        result_json TEXT NOT NULL DEFAULT '{}', saved_by TEXT NOT NULL,
        created_at TEXT NOT NULL
    )""")

ROOT = Path(__file__).resolve().parents[2]
API_PATH = ROOT / "cloud-functions" / "api" / "index.py"
spec = importlib.util.spec_from_file_location("broute193_schema_migration_api", API_PATH)
api = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = api
spec.loader.exec_module(api)
api.init_db()

with sqlite3.connect(DB) as migrated:
    columns = {row[1] for row in migrated.execute("PRAGMA table_info(project_route_versions)").fetchall()}
assert "title" in columns
print("PASS: existing 1.92 project_route_versions schema migrates to 1.93 with title history field")
