"""Explicit CORS allowlist and secure cross-origin cookie setting tests; no network calls."""
import os
import tempfile
from pathlib import Path

TMP = Path(tempfile.mkdtemp(prefix="broute-beta2-cors-"))
os.environ.update({
    "APP_ENV": "development",
    "APP_VERSION": "2.0.0-beta.2",
    "DATA_DIR": str(TMP / "data"),
    "DATABASE_PATH": str(TMP / "data" / "cors.sqlite3"),
    "APP_ORIGIN": "https://api.broute.example",
    "APP_ALLOWED_ORIGINS": "https://tester.github.io;https://preview.broute.example",
    "SESSION_COOKIE_SAMESITE": "none",
    "SESSION_SECRET": "cross-origin-test-secret-" + "z" * 32,
})

import sys
ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "cloud-functions"))
from fastapi.testclient import TestClient
from api import index as api_module

with TestClient(api_module.app, base_url="https://api.broute.example") as client:
    # CORS response must echo only the exact allowlisted frontend origin.
    good = client.get("/health", headers={"Origin": "https://tester.github.io"})
    assert good.status_code == 200, good.text
    assert good.headers.get("access-control-allow-origin") == "https://tester.github.io"
    assert good.headers.get("access-control-allow-credentials") == "true"

    preflight = client.options("/auth/logout", headers={
        "Origin": "https://tester.github.io",
        "Access-Control-Request-Method": "POST",
        "Access-Control-Request-Headers": "content-type",
    })
    assert preflight.status_code == 200, preflight.text
    assert preflight.headers.get("access-control-allow-origin") == "https://tester.github.io"

    logout = client.post("/auth/logout", headers={"Origin": "https://tester.github.io"})
    assert logout.status_code == 200, logout.text
    cookies = logout.headers.get_list("set-cookie")
    assert cookies and all("SameSite=none" in item and "Secure" in item for item in cookies)

    # A non-allowlisted website cannot use credentialed browser access or the
    # state-changing same-origin-guarded endpoint.
    denied_cors = client.get("/health", headers={"Origin": "https://evil.example"})
    assert "access-control-allow-origin" not in denied_cors.headers
    denied_write = client.post("/auth/logout", headers={"Origin": "https://evil.example"})
    assert denied_write.status_code == 403, denied_write.text

print("PASS: explicit CORS allowlist, preflight, allowed origin guard, denied origin guard and Secure SameSite=None cookies")
