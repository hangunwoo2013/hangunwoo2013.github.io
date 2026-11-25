"""B-ROUTE 1.92 collaboration, multi-provider identity and read-only share tests.
All identities/records are synthetic; no external OAuth/API calls are made.
"""
import importlib.util
import json
import re
import os
import httpx
import tempfile
import time
from pathlib import Path
from urllib.parse import urlparse, parse_qs

TMP = Path(tempfile.mkdtemp(prefix="broute192-projects-"))
os.environ.update({
    "APP_ENV": "development",
    "DATA_DIR": str(TMP / "data"),
    "DATABASE_PATH": str(TMP / "data" / "test.sqlite3"),
    "APP_ORIGIN": "https://testserver",
    "GOOGLE_ADMIN_SUB": "google-owner-sub",
    "GOOGLE_ADMIN_EMAIL": "owner@example.com",
    "GOOGLE_CLIENT_ID": "google-client-test",
    "NAVER_CLIENT_ID": "naver-client-test",
    "NAVER_CLIENT_SECRET": "naver-secret-test",
    "NAVER_REDIRECT_URI": "https://testserver/api/auth/naver/callback",
    "MICROSOFT_CLIENT_ID": "microsoft-client-test",
    "MICROSOFT_CLIENT_SECRET": "microsoft-secret-test",
    "MICROSOFT_TENANT": "common",
    "MICROSOFT_REDIRECT_URI": "https://testserver/api/auth/microsoft/callback",
    "SESSION_SECRET": "s" * 48,
    "RESEND_API_KEY": "re_test_server_only_key",
    "INVITE_FROM_EMAIL": "invites@broute.example.test",
    "INVITE_FROM_NAME": "B-ROUTE",
    "INVITE_EMAIL_DAILY_LIMIT": "80",
})
ROOT = Path(__file__).resolve().parents[2]
API_PATH = ROOT / "cloud-functions" / "api" / "index.py"
spec = importlib.util.spec_from_file_location("broute192_projects_api", API_PATH)
api = importlib.util.module_from_spec(spec)
import sys
sys.modules[spec.name] = api
spec.loader.exec_module(api)
api.init_db()

# All outgoing mail is intercepted locally; no external email is sent.
outbound_emails = []
def resend_mock(request):
    assert request.url.host == "api.resend.com"
    assert request.url.path == "/emails"
    assert request.headers.get("Authorization") == "Bearer re_test_server_only_key"
    payload = json.loads(request.content.decode("utf-8"))
    outbound_emails.append(payload)
    return httpx.Response(200, json={"id": f"mock-email-{len(outbound_emails)}"})
api.RESEND_HTTP_TRANSPORT = lambda: httpx.MockTransport(resend_mock)

def latest_invite_token():
    assert outbound_emails, "No invitation email was generated"
    match = re.search(r'href="https://testserver/#invite=([^"&]+)"', outbound_emails[-1]["html"])
    assert match, outbound_emails[-1]["html"]
    return match.group(1)

from fastapi.testclient import TestClient

headers = {"Origin": "https://testserver"}
owner_claims = api._provider_user_session("google", "google-owner-sub", "owner@example.com", "Owner", True)
editor_claims = api._provider_user_session("naver", "naver:naver-sub-1", "friend@naver.com", "Naver Friend", False)
viewer_claims = api._provider_user_session("microsoft", "microsoft:tenant-1:object-2", "friend@outlook.com", "Outlook Friend", False)


def auth_client(claims=None):
    c = TestClient(api.app)
    if claims:
        c.cookies.set(api.SESSION_COOKIE, api._session_token(claims))
    return c

owner = auth_client(owner_claims)
editor = auth_client(editor_claims)
viewer = auth_client(viewer_claims)

# Auth providers are advertised only when their complete server config exists.
config = owner.get("/auth/config").json()
assert config["google_signin_enabled"] is True
assert config["naver_signin_enabled"] is True
assert config["microsoft_signin_enabled"] is True
assert owner.get("/auth/me").json()["is_owner"] is True
assert editor.get("/auth/me").json()["is_owner"] is False

# Owner authorization is tied to Google provider identity, never an email or
# an identically-spelled subject emitted by another provider.
forged_naver = dict(owner_claims, provider="naver", email_verified=True)
assert api._is_owner(forged_naver) is False

# Unauthenticated callers cannot create projects.
assert TestClient(api.app).post("/projects", json={"name": "차량 답사"}, headers=headers).status_code == 401

# Project and first route creation.
created = owner.post("/projects", json={"name": "부산 답사 프로젝트", "description": "버스·철도 경로 공동 편집"}, headers=headers)
assert created.status_code == 200, created.text
project_id = created.json()["project_id"]
assert owner.get("/projects").json()["projects"][0]["role"] == "owner"

plan = {
    "origin": {"id": "start", "name": "부산역", "lat": 35.1151, "lon": 129.0412},
    "destination": {"id": "end", "name": "서면역", "lat": 35.1579, "lon": 129.0595},
    "vias": [], "transport_mode": "combined"
}
route_created = owner.post(f"/projects/{project_id}/routes", json={
    "title": "부산역에서 서면", "plan": plan,
    "result": {"status": "ok", "total_minutes": 24, "steps": []}
}, headers=headers)
assert route_created.status_code == 200, route_created.text
route_id = route_created.json()["route_id"]

# A Naver account can accept an editor invitation even though the provider
# profile email is deliberately not treated as verified identity.
invite = owner.post(f"/projects/{project_id}/invites", json={"email": "friend@naver.com", "role": "editor"}, headers=headers)
assert invite.status_code == 200, invite.text
assert invite.json()["email_status"] == "accepted" and "invite_url" not in invite.json()
assert outbound_emails[-1]["to"] == ["friend@naver.com"]
assert "프로젝트 참가하기" in outbound_emails[-1]["html"]
assert "B-ROUTE" in outbound_emails[-1]["subject"]
invite_token = latest_invite_token()
preview = owner.post("/project-invites/preview", json={"token": invite_token}, headers=headers)
assert preview.status_code == 200 and preview.headers.get("cache-control") == "no-store, max-age=0"
assert invite_token not in str(preview.request.url)
wrong_identity = auth_client(api._provider_user_session("microsoft", "microsoft:wrong:sub", "someoneelse@example.com", "Wrong"))
assert wrong_identity.post("/project-invites/accept", json={"token": invite_token}, headers=headers).status_code == 409
accepted = editor.post("/project-invites/accept", json={"token": invite_token}, headers=headers)
assert accepted.status_code == 200, accepted.text
assert accepted.json()["role"] == "editor"
assert editor.get(f"/projects/{project_id}").json()["project"]["role"] == "editor"

# Microsoft personal/work account style subject can accept a viewer invitation.
invite2 = owner.post(f"/projects/{project_id}/invites", json={"email": "friend@outlook.com", "role": "viewer"}, headers=headers)
assert invite2.status_code == 200, invite2.text
invite_token2 = latest_invite_token()
accepted2 = viewer.post("/project-invites/accept", json={"token": invite_token2}, headers=headers)
assert accepted2.status_code == 200, accepted2.text
assert accepted2.json()["role"] == "viewer"

# All three members can see routes; only owner/editor can mutate them.
assert viewer.get(f"/projects/{project_id}/routes").status_code == 200
assert viewer.post(f"/projects/{project_id}/routes", json={"title": "금지", "plan": plan}, headers=headers).status_code == 403
assert editor.post(f"/projects/{project_id}/routes", json={"title": "편집자 추가", "plan": plan}, headers=headers).status_code == 200
update = editor.put(f"/projects/{project_id}/routes/{route_id}", json={
    "title": "편집자가 수정한 경로", "plan": plan,
    "result": {"status": "ok", "total_minutes": 22, "steps": []},
    "expected_version": 1
}, headers=headers)
assert update.status_code == 200, update.text
assert update.json()["version"] == 2
# A stale editor must not overwrite a version committed by another member.
stale = owner.put(f"/projects/{project_id}/routes/{route_id}", json={
    "title": "오래된 화면의 덮어쓰기", "plan": plan,
    "result": {"status": "ok", "total_minutes": 99, "steps": []},
    "expected_version": 1
}, headers=headers)
assert stale.status_code == 409, stale.text
assert "현재 버전은 2" in stale.json()["detail"]
current = editor.get(f"/projects/{project_id}/routes/{route_id}").json()["route"]
assert current["version"] == 2 and current["result"]["total_minutes"] == 22
# A real concurrent race from two authenticated editors: exactly one writer wins.
race_route = owner.post(f"/projects/{project_id}/routes", json={
    "title": "동시 편집 테스트", "plan": plan,
    "result": {"status": "ok", "total_minutes": 30, "steps": []}
}, headers=headers)
assert race_route.status_code == 200, race_route.text
race_route_id = race_route.json()["route_id"]
def race_save(claims, title, minutes):
    c = auth_client(claims)
    return c.put(f"/projects/{project_id}/routes/{race_route_id}", json={
        "title": title, "plan": plan,
        "result": {"status": "ok", "total_minutes": minutes, "steps": []},
        "expected_version": 1
    }, headers=headers)
from concurrent.futures import ThreadPoolExecutor
with ThreadPoolExecutor(max_workers=2) as pool:
    futures = [pool.submit(race_save, editor_claims, "동시 저장 A", 31),
               pool.submit(race_save, owner_claims, "동시 저장 B", 32)]
    race_results = [f.result(timeout=20) for f in futures]
assert sorted(r.status_code for r in race_results) == [200, 409], [r.status_code for r in race_results]
race_current = owner.get(f"/projects/{project_id}/routes/{race_route_id}").json()["route"]
assert race_current["version"] == 2 and race_current["result"]["total_minutes"] in (31, 32)
# Missing expected_version is rejected by the request model.
missing_version = editor.put(f"/projects/{project_id}/routes/{route_id}", json={
    "title": "버전 없는 저장", "plan": plan, "result": {}
}, headers=headers)
assert missing_version.status_code == 422
assert viewer.put(f"/projects/{project_id}/routes/{route_id}", json={
    "title": "뷰어 변경", "plan": plan, "expected_version": 2
}, headers=headers).status_code == 403
versions = owner.get(f"/projects/{project_id}/routes/{route_id}/versions")
assert versions.status_code == 200 and versions.json()["versions"]
assert versions.json()["versions"][0]["title"] == "부산역에서 서면"
assert versions.json()["versions"][0]["saved_by"] == owner_claims["sub"]
version_id = versions.json()["versions"][0]["version_id"]
restored = owner.post(f"/projects/{project_id}/routes/{route_id}/versions/{version_id}/restore", headers=headers)
assert restored.status_code == 200, restored.text
restored_route = owner.get(f"/projects/{project_id}/routes/{route_id}").json()["route"]
assert restored_route["title"] == "부산역에서 서면"

# Project route share: public, read-only, expires/view-limited, and revocable.
project_share = owner.post(f"/projects/{project_id}/routes/{route_id}/shares",
                           json={"expires_days": 7, "max_views": 1}, headers=headers)
assert project_share.status_code == 200, project_share.text
public_project_token = parse_qs(urlparse(project_share.json()["url"]).query)["project_share"][0]
public_project = TestClient(api.app)
assert public_project.get(f"/public/project-shares/{public_project_token}").status_code == 200
assert public_project.get(f"/public/project-shares/{public_project_token}").status_code == 410
assert viewer.delete(f"/projects/{project_id}/routes/{route_id}/shares/{project_share.json()['share_id']}", headers=headers).status_code == 403
assert owner.delete(f"/projects/{project_id}/routes/{route_id}/shares/{project_share.json()['share_id']}", headers=headers).status_code == 200

# Ordinary share is also public read-only; the original route has no mutation
# endpoint exposed through the capability token.
normal_share = owner.post("/shares", json={"plan": plan, "result": {"total_minutes": 22}, "max_views": 1}, headers=headers)
assert normal_share.status_code == 200, normal_share.text
share_token = normal_share.json()["share_token"]
assert public_project.get(f"/shares/{share_token}").status_code == 200
assert public_project.get(f"/shares/{share_token}").status_code == 410
assert owner.delete(f"/shares/{normal_share.json()['share_id']}", headers=headers).status_code == 200

# One-use invitations reject replay; a second accept cannot silently add members.
assert editor.post("/project-invites/accept", json={"token": invite_token}, headers=headers).status_code == 410

# Bounded free-tier quotas are returned and checked server-side.
limits = owner.get("/projects").json()["limits"]
assert limits == {"projects_per_owner": 5, "members_per_project": 10, "routes_per_project": 100}
assert len(owner.get(f"/projects/{project_id}/members").json()["members"]) == 3

print("PASS: 1.94 auth identities, owner isolation, emailed cross-provider invitations, mailbox-link proof, explicit account choice, optimistic edit conflicts, versions and read-only shares")
