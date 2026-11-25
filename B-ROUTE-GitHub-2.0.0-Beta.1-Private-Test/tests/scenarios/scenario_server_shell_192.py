"""Same-origin frontend/API mount smoke tests; local SQLite only."""
import os
import tempfile
from pathlib import Path

TMP = Path(tempfile.mkdtemp(prefix="broute192-server-"))
os.environ.update({
    "APP_ENV": "development",
    "DATA_DIR": str(TMP / "data"),
    "DATABASE_PATH": str(TMP / "data" / "server.sqlite3"),
    "APP_ORIGIN": "http://testserver",
    "SESSION_SECRET": "server-shell-test-secret-" + "x" * 32,
    "GOOGLE_CLIENT_ID": "google-client-test",
    "GOOGLE_ADMIN_SUB": "owner-shell-test",
})

import sys
ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from fastapi.testclient import TestClient
from server import app

with TestClient(app) as client:
    home = client.get("/")
    assert home.status_code == 200
    assert "B-ROUTE" in home.text and "프로젝트" in home.text
    manifest = client.get("/manifest.json")
    assert manifest.status_code == 200 and "2.0.0-beta.1" in manifest.text
    health = client.get("/api/health")
    assert health.status_code == 200, health.text
    assert health.json()["version"] == "2.0.0-beta.1"
    assert health.json()["readiness"]["beta_ready"] is False
    assert health.json()["readiness"]["checks"]["release_gate_approved"] is False
    auth = client.get("/api/auth/config")
    assert auth.status_code == 200
    assert auth.json()["google_signin_enabled"] is True
    admin = client.get("/admin.html")
    assert admin.status_code == 200 and "B-ROUTE 2.0.0-beta.1" in admin.text
    # Local development must not publish dotfiles or project source files.
    assert client.get("/.env").status_code == 404
    assert client.get("/server.py").status_code == 404
    protected = client.get("/api/projects")
    assert protected.status_code == 401

    # Health and the owner-only admin readiness panel must expose the same checks.
    from api import index as api_module
    owner_claims = {"sub": "owner-shell-test", "provider": "google", "email": "owner@example.test",
                    "email_verified": True, "exp": 4102444800}
    client.cookies.set(api_module.SESSION_COOKIE, api_module._session_token(owner_claims))
    status = client.get("/api/admin/config/status")
    assert status.status_code == 200, status.text
    assert status.json()["beta_readiness"]["checks"] == health.json()["readiness"]["checks"]

print("PASS: single-origin frontend/API mount, static assets, 2.0 Beta health, protected routes and consistent beta readiness")
