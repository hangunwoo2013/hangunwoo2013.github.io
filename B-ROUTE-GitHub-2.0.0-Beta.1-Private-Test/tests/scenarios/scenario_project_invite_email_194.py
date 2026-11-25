"""Transactional project invitation emails, mailbox-bound acceptance and resend tests.
All provider HTTP calls are intercepted with httpx.MockTransport; no email is sent.
"""
from __future__ import annotations

import importlib.util
import json
import os
import re
import sqlite3
import tempfile
from datetime import datetime
from pathlib import Path

import httpx

TMP = Path(tempfile.mkdtemp(prefix="broute194-invite-email-"))
DB_PATH = TMP / "data" / "legacy.sqlite3"
DB_PATH.parent.mkdir(parents=True, exist_ok=True)
os.environ.update({
    "APP_ENV": "development",
    "DATA_DIR": str(TMP / "data"),
    "DATABASE_PATH": str(DB_PATH),
    "APP_ORIGIN": "https://broute.test",
    "GOOGLE_ADMIN_SUB": "owner-google-sub",
    "GOOGLE_ADMIN_EMAIL": "owner@example.com",
    "GOOGLE_CLIENT_ID": "google-client-test",
    "NAVER_CLIENT_ID": "naver-client-test",
    "NAVER_CLIENT_SECRET": "naver-secret-test",
    "NAVER_REDIRECT_URI": "https://broute.test/api/auth/naver/callback",
    "MICROSOFT_CLIENT_ID": "microsoft-client-test",
    "MICROSOFT_CLIENT_SECRET": "microsoft-secret-test",
    "MICROSOFT_TENANT": "common",
    "MICROSOFT_REDIRECT_URI": "https://broute.test/api/auth/microsoft/callback",
    "SESSION_SECRET": "invite-email-test-secret-" + "x" * 32,
    "RESEND_API_KEY": "re_test_mock_secret",
    "INVITE_FROM_EMAIL": "invites@broute.example.test",
    "INVITE_FROM_NAME": "B-ROUTE",
    "INVITE_REPLY_TO_EMAIL": "broute.site.app@gmail.com",
    "RESEND_WEBHOOK_SECRET": "",
    "INVITE_EMAIL_DAILY_LIMIT": "80",
})

# Create a 1.93-shaped table before importing the new app, then verify 1.94
# adds delivery columns automatically without losing existing invitation data.
legacy = sqlite3.connect(DB_PATH)
legacy.execute("""CREATE TABLE projects (
    project_id TEXT PRIMARY KEY, owner_sub TEXT NOT NULL, name TEXT NOT NULL,
    description TEXT NOT NULL DEFAULT '', created_at TEXT NOT NULL, updated_at TEXT NOT NULL,
    archived_at TEXT
)""")
legacy.execute("""CREATE TABLE project_invites (
    invite_id TEXT PRIMARY KEY, project_id TEXT NOT NULL, invite_email TEXT NOT NULL,
    role TEXT NOT NULL CHECK(role IN ('editor','viewer')), token_hash TEXT NOT NULL UNIQUE,
    created_by TEXT NOT NULL, created_at TEXT NOT NULL, expires_at TEXT NOT NULL,
    accepted_by TEXT, accepted_at TEXT, revoked_at TEXT
)""")
legacy.commit()
legacy.close()

ROOT = Path(__file__).resolve().parents[2]
API_PATH = ROOT / "cloud-functions" / "api" / "index.py"
import sys
spec = importlib.util.spec_from_file_location("broute194_invite_email_api", API_PATH)
api = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = api
spec.loader.exec_module(api)
api.init_db()

with sqlite3.connect(DB_PATH) as check:
    columns = {row[1] for row in check.execute("PRAGMA table_info(project_invites)")}
assert {"email_status", "email_message_id", "email_sent_at", "email_error_code", "send_attempts", "current_email_event_id"}.issubset(columns)

mode = {"status": 200, "invalid_json": False}
sent_payloads = []
def resend_handler(request: httpx.Request):
    assert request.url == "https://api.resend.com/emails"
    assert request.headers.get("Authorization") == "Bearer re_test_mock_secret"
    assert request.headers.get("Idempotency-Key", "").startswith("broute-invite-")
    payload = json.loads(request.content.decode("utf-8"))
    sent_payloads.append(payload)
    if mode["status"] >= 400:
        return httpx.Response(mode["status"], json={"message": "mock failure - body must not leak"})
    if mode["invalid_json"]:
        return httpx.Response(200, json={"unexpected": True})
    return httpx.Response(200, json={"id": f"mock-resend-{len(sent_payloads)}"})
api.RESEND_HTTP_TRANSPORT = lambda: httpx.MockTransport(resend_handler)

from fastapi.testclient import TestClient
headers = {"Origin": "https://broute.test"}
def client_for(claims):
    c = TestClient(api.app)
    c.cookies.set(api.SESSION_COOKIE, api._session_token(claims))
    return c

owner_claims = api._provider_user_session("google", "owner-google-sub", "owner@example.com", "Owner", True)
naver_claims = api._provider_user_session("naver", "naver:friend-sub", "friend@naver.com", "Naver Friend", False)
outlook_claims = api._provider_user_session("microsoft", "microsoft:tenant:outlook-sub", "friend@outlook.com", "Outlook Friend", False)
wrong_claims = api._provider_user_session("microsoft", "microsoft:tenant:wrong-sub", "other@example.com", "Wrong", False)
owner = client_for(owner_claims)
naver = client_for(naver_claims)
outlook = client_for(outlook_claims)
wrong = client_for(wrong_claims)

assert owner.get("/auth/config").json()["project_invite_email_enabled"] is True
created = owner.post("/projects", json={"name": "메일 초대 테스트", "description": "1.94"}, headers=headers)
assert created.status_code == 200, created.text
project_id = created.json()["project_id"]

# Invite creation sends an actual transactional-email request and does not
# disclose the bearer invitation URL to the project-owner browser.
invite = owner.post(f"/projects/{project_id}/invites", json={"email": "friend@naver.com", "role": "editor"}, headers=headers)
assert invite.status_code == 200, invite.text
assert invite.json()["email_status"] == "accepted"
assert "invite_url" not in invite.json() and "token" not in invite.json()
payload = sent_payloads[-1]
assert payload["to"] == ["friend@naver.com"]
assert payload["reply_to"] == "broute.site.app@gmail.com"
assert "프로젝트 참가하기" in payload["html"]
assert "프로젝트 참가하기" in payload["text"]
assert "현재 로그인 계정" in payload["html"]
match = re.search(r'href="https://broute\.test/#invite=([^"&]+)"', payload["html"])
assert match, payload["html"]
token = match.group(1)
preview = owner.post("/project-invites/preview", json={"token": token}, headers=headers)
assert preview.status_code == 200, preview.text
# The new client sends the token in a same-origin POST body, not the API URL.
assert preview.request.url.path == "/project-invites/preview" and token not in str(preview.request.url)
# Preview requests are safe for mail security scanners and never consume the invite.
preview_repeat = owner.post("/project-invites/preview", json={"token": token}, headers=headers)
assert preview_repeat.status_code == 200
assert preview_repeat.request.url.path == "/project-invites/preview" and token not in str(preview_repeat.request.url)
assert json.loads(preview_repeat.request.content)["token"] == token
# Legacy GET preview remains available for old 1.9x clients only.
assert owner.get(f"/project-invites/{token}").status_code == 200
assert preview.json()["mailbox_proof"] == "one_time_email_link"
assert preview.headers.get("cache-control") == "no-store, max-age=0"
assert preview.headers.get("referrer-policy") == "no-referrer"
assert owner.get(f"/projects/{project_id}/members").json()["members"] == [
    {"user_sub": "owner-google-sub", "email": "owner@example.com", "role": "owner", "joined_at": owner.get(f"/projects/{project_id}/members").json()["members"][0]["joined_at"]}
]
# Link click alone does not add the user. The logged-in identity must match
# the mailbox address to which the invite was sent.
# The invitation link itself proves access to the target mailbox. A
# mismatched sign-in account must explicitly confirm which B-ROUTE identity
# should receive the project membership.
mismatch_accept = wrong.post("/project-invites/accept", json={"token": token}, headers=headers)
assert mismatch_accept.status_code == 409
assert mismatch_accept.request.url.path == "/project-invites/accept" and token not in str(mismatch_accept.request.url)
assert json.loads(mismatch_accept.request.content)["token"] == token
assert naver.post("/project-invites/accept", json={"token": token}, headers=headers).status_code == 200
assert naver.post("/project-invites/accept", json={"token": token}, headers=headers).status_code == 410

# A user may intentionally accept into a different provider account after
# opening the link from the invited mailbox; the account choice is explicit.
third = owner.post(f"/projects/{project_id}/invites", json={"email": "shared-mailbox@example.com", "role": "viewer"}, headers=headers)
assert third.status_code == 200, third.text
third_token = re.search(r'href="https://broute\.test/#invite=([^"&]+)"', sent_payloads[-1]["html"]).group(1)
assert wrong.post("/project-invites/accept", json={"token": third_token, "confirm_current_account": True}, headers=headers).status_code == 200
members_after_mismatch = owner.get(f"/projects/{project_id}/members").json()["members"]
assert any(m["user_sub"] == wrong_claims["sub"] and m["email"] == "other@example.com" for m in members_after_mismatch)
# New API routes keep the raw capability in JSON bodies, not path segments.
assert preview.request.url.path == "/project-invites/preview"

# Resending rotates the capability: the old mail's link becomes invalid.
second = owner.post(f"/projects/{project_id}/invites", json={"email": "friend@outlook.com", "role": "viewer"}, headers=headers)
assert second.status_code == 200, second.text
second_token = re.search(r'href="https://broute\.test/#invite=([^"&]+)"', sent_payloads[-1]["html"]).group(1)
second_id = second.json()["invite_id"]
resent = owner.post(f"/projects/{project_id}/invites/{second_id}/resend", headers=headers)
assert resent.status_code == 200, resent.text
third_token = re.search(r'href="https://broute\.test/#invite=([^"&]+)"', sent_payloads[-1]["html"]).group(1)
assert third_token != second_token
assert owner.post("/project-invites/preview", json={"token": second_token}, headers=headers).status_code == 410
assert owner.post("/project-invites/preview", json={"token": third_token}, headers=headers).status_code == 200
assert outlook.post("/project-invites/accept", json={"token": third_token}, headers=headers).status_code == 200

# Failed provider requests are recorded safely and can be retried by the owner.
mode["status"] = 400
failed = owner.post(f"/projects/{project_id}/invites", json={"email": "retry@example.com", "role": "viewer"}, headers=headers)
assert failed.status_code == 502
failed_list = owner.get(f"/projects/{project_id}/invites").json()["invites"]
failed_row = next(x for x in failed_list if x["email"] == "retry@example.com")
assert failed_row["email_status"] == "failed" and failed_row["email_error_code"] == "resend_http_400"
assert "mock failure" not in failed.text
failed_token = re.search(r'href="https://broute\.test/#invite=([^"&]+)"', sent_payloads[-1]["html"]).group(1)
assert owner.post("/project-invites/preview", json={"token": failed_token}, headers=headers).status_code == 410
mode["status"] = 200
retried = owner.post(f"/projects/{project_id}/invites/{failed_row['invite_id']}/resend", headers=headers)
assert retried.status_code == 200, retried.text
recovered_token = re.search(r'href="https://broute\.test/#invite=([^"&]+)"', sent_payloads[-1]["html"]).group(1)
assert owner.post("/project-invites/preview", json={"token": recovered_token}, headers=headers).status_code == 200

# Stale completion from an older, slower send cannot overwrite the newest
# resend state on the invitation row.
with sqlite3.connect(DB_PATH) as con:
    events = con.execute("SELECT event_id FROM project_invite_email_events WHERE invite_id=?", (failed_row["invite_id"],)).fetchall()
    current_before = con.execute("SELECT current_email_event_id,email_status FROM project_invites WHERE invite_id=?", (failed_row["invite_id"],)).fetchone()
old_event_id = next(row[0] for row in events if row[0] != current_before[0])
assert len(events) >= 2 and current_before[0]
api._record_invite_email_result(old_event_id, failed_row["invite_id"], status="failed", now=datetime.now(api.TZ).isoformat(), error_code="stale_old_attempt")
with sqlite3.connect(DB_PATH) as con:
    current_after = con.execute("SELECT current_email_event_id,email_status,email_error_code FROM project_invites WHERE invite_id=?", (failed_row["invite_id"],)).fetchone()
assert current_after == (current_before[0], "accepted", "")

# App-level free-tier cap is enforced before any additional API call.
current_count = len(sent_payloads)
api.INVITE_EMAIL_DAILY_LIMIT = current_count
before = len(sent_payloads)
capped = owner.post(f"/projects/{project_id}/invites", json={"email": "cap@example.com", "role": "viewer"}, headers=headers)
assert capped.status_code == 429 and len(sent_payloads) == before

# Missing mail configuration fails closed and creates no invitation row.
api.INVITE_EMAIL_DAILY_LIMIT = 80
old_key = api.RESEND_API_KEY
api.RESEND_API_KEY = ""
before_rows = len(owner.get(f"/projects/{project_id}/invites").json()["invites"])
not_configured = owner.post(f"/projects/{project_id}/invites", json={"email": "noconfig@example.com", "role": "viewer"}, headers=headers)
assert not_configured.status_code == 503
assert len(owner.get(f"/projects/{project_id}/invites").json()["invites"]) == before_rows
api.RESEND_API_KEY = old_key

# Owner-only controls: editor cannot resend or inspect the invite list.
assert naver.get(f"/projects/{project_id}/invites").status_code == 403
assert naver.post(f"/projects/{project_id}/invites/{second_id}/resend", headers=headers).status_code == 403

print("PASS: 1.94 Resend invite CTA, one-time mailbox-link proof, explicit account selection, fragment token, no auto-accept, resend rotation, stale-send protection, retry, failure handling, daily quota and legacy DB migration")
