"""Resend delivery webhook signature, idempotency and delivery-state tests."""
from __future__ import annotations
import base64, hashlib, hmac, importlib.util, json, os, sqlite3, tempfile, time
from datetime import datetime
from pathlib import Path
import httpx
TMP=Path(tempfile.mkdtemp(prefix="broute195-webhook-")); DB=TMP/"data"/"broute.sqlite3"; DB.parent.mkdir(parents=True)
secret=b"test-resend-webhook-secret-195"
os.environ.update({"APP_ENV":"development","DATA_DIR":str(DB.parent),"DATABASE_PATH":str(DB),"APP_ORIGIN":"https://broute.test","SESSION_SECRET":"webhook-test-secret-"+"z"*32,"GOOGLE_ADMIN_SUB":"owner-sub","GOOGLE_ADMIN_EMAIL":"owner@example.com","GOOGLE_CLIENT_ID":"google-test","RESEND_API_KEY":"re_test","INVITE_FROM_EMAIL":"invite@broute.example.test","INVITE_REPLY_TO_EMAIL":"broute.site.app@gmail.com","RESEND_WEBHOOK_SECRET":"whsec_"+base64.b64encode(secret).decode()})
ROOT=Path(__file__).resolve().parents[2]; spec=importlib.util.spec_from_file_location("broute195_webhook_api",ROOT/"cloud-functions/api/index.py"); api=importlib.util.module_from_spec(spec); import sys; sys.modules[spec.name]=api; spec.loader.exec_module(api); api.init_db()
mode={"n":0}
def handler(req):
 mode["n"]+=1
 return httpx.Response(200,json={"id":f"resend-msg-{mode['n']}"})
api.RESEND_HTTP_TRANSPORT=lambda: httpx.MockTransport(handler)
from fastapi.testclient import TestClient
claims=api._provider_user_session("google","owner-sub","owner@example.com","Owner",True)
c=TestClient(api.app); c.cookies.set(api.SESSION_COOKIE,api._session_token(claims)); h={"Origin":"https://broute.test"}
project=c.post("/projects",json={"name":"웹훅 검증","description":""},headers=h); assert project.status_code==200,project.text; pid=project.json()["project_id"]
inv=c.post(f"/projects/{pid}/invites",json={"email":"target@example.com","role":"viewer"},headers=h); assert inv.status_code==200,inv.text; iid=inv.json()["invite_id"]
with sqlite3.connect(DB) as con: msg=con.execute("SELECT provider_message_id FROM project_invite_email_events WHERE invite_id=? ORDER BY created_at DESC LIMIT 1",(iid,)).fetchone()[0]
assert msg=="resend-msg-1"
def send(event_id, typ, ts=None, signature_override=None):
 timestamp=str(int(time.time()) if ts is None else ts); body=json.dumps({"type":typ,"data":{"email_id":msg}},separators=(",",":")).encode(); signed=event_id.encode()+b"."+timestamp.encode()+b"."+body; sig=base64.b64encode(hmac.new(secret,signed,hashlib.sha256).digest()).decode(); headers={"svix-id":event_id,"svix-timestamp":timestamp,"svix-signature":signature_override or ("v1,"+sig)}; return c.post("/webhooks/resend",content=body,headers=headers)
assert c.post("/webhooks/resend",content=b"{}",headers={"svix-id":"bad","svix-timestamp":str(int(time.time())),"svix-signature":"v1,invalid"}).status_code==401
assert send("evt-delivered-195","email.delivered").json()["status"]=="delivered"
assert send("evt-delivered-195","email.delivered").json()["duplicate"] is True
with sqlite3.connect(DB) as con: state=con.execute("SELECT email_status FROM project_invites WHERE invite_id=?",(iid,)).fetchone()[0]
assert state=="delivered",state
# A later-arriving lower-priority 'sent' event must not regress delivered state.
assert send("evt-sent-late-195","email.sent").json()["status"]=="sent"
with sqlite3.connect(DB) as con: state=con.execute("SELECT email_status FROM project_invites WHERE invite_id=?",(iid,)).fetchone()[0]
assert state=="delivered",state
assert send("evt-bounced-195","email.bounced").json()["status"]=="bounced"
with sqlite3.connect(DB) as con: state=con.execute("SELECT email_status FROM project_invites WHERE invite_id=?",(iid,)).fetchone()[0]
assert state=="bounced",state
# Suppressed is a terminal delivery state too; it must outrank earlier events
# and be visible on both the email event and invitation.
assert api._email_delivery_priority("suppressed") > api._email_delivery_priority("bounced")
assert api.resend_webhook_secret_configured() is True
old_webhook_secret=api.RESEND_WEBHOOK_SECRET
api.RESEND_WEBHOOK_SECRET="whsec_not-valid-base64%%%"
assert api.resend_webhook_secret_configured() is False
api.RESEND_WEBHOOK_SECRET="whsec_"
assert api.resend_webhook_secret_configured() is False
invalid_secret_response=c.post("/webhooks/resend",content=b"{}",headers={"svix-id":"empty-secret","svix-timestamp":str(int(time.time())),"svix-signature":"v1,not-valid"})
assert invalid_secret_response.status_code==503,invalid_secret_response.text
api.RESEND_WEBHOOK_SECRET=old_webhook_secret
assert send("evt-suppressed-195","email.suppressed").json()["status"]=="suppressed"
with sqlite3.connect(DB) as con:
    state,error=con.execute("SELECT email_status,email_error_code FROM project_invites WHERE invite_id=?",(iid,)).fetchone()
assert (state,error)==("suppressed","suppressed"),(state,error)
# Simulate the rare race where Resend's webhook arrives before the send API
# response has persisted its provider message ID. The event must be reconciled.
second=c.post(f"/projects/{pid}/invites",json={"email":"race@example.com","role":"viewer"},headers=h); assert second.status_code==200
second_iid=second.json()["invite_id"]
with sqlite3.connect(DB) as con:
    row=con.execute("SELECT event_id,provider_message_id FROM project_invite_email_events WHERE invite_id=? ORDER BY created_at DESC LIMIT 1",(second_iid,)).fetchone()
    second_event,second_msg=row
    con.execute("UPDATE project_invite_email_events SET provider_message_id='' WHERE event_id=?",(second_event,))
    con.execute("UPDATE project_invites SET email_status='sending',email_message_id='' WHERE invite_id=?",(second_iid,))
    con.commit()
api._apply_resend_delivery_event("evt-race-delivered-195","email.delivered",second_msg,datetime.now(api.TZ).isoformat(),hashlib.sha256(b"race").hexdigest())
api._record_invite_email_result(second_event,second_iid,status="accepted",now=datetime.now(api.TZ).isoformat(),message_id=second_msg)
with sqlite3.connect(DB) as con: raced=con.execute("SELECT email_status FROM project_invites WHERE invite_id=?",(second_iid,)).fetchone()[0]
assert raced=="delivered",raced
# Reject stale signed deliveries as well as invalid signatures.
old_ts=str(int(time.time())-1000); body=b"{}"; stale_signed=b"stale-evt."+old_ts.encode()+b"."+body; stale_sig=base64.b64encode(hmac.new(secret,stale_signed,hashlib.sha256).digest()).decode()
stale=c.post("/webhooks/resend",content=body,headers={"svix-id":"stale-evt","svix-timestamp":old_ts,"svix-signature":"v1,"+stale_sig}); assert stale.status_code==400
# The API app is mounted by the public web shell at /api. Verify the actual
# externally reachable URL, not only the unmounted sub-app route.
from server import app as shell_app
with TestClient(shell_app) as shell:
    body=json.dumps({"type":"email.sent","data":{"email_id":"unknown-provider-message"}},separators=(",",":")).encode()
    event_id="evt-mounted-path-195"; timestamp=str(int(time.time()))
    signed=event_id.encode()+b"."+timestamp.encode()+b"."+body
    signature=base64.b64encode(hmac.new(secret,signed,hashlib.sha256).digest()).decode()
    headers={"svix-id":event_id,"svix-timestamp":timestamp,"svix-signature":"v1,"+signature}
    mounted=shell.post("/api/webhooks/resend",content=body,headers=headers)
    assert mounted.status_code==200,mounted.text
    assert shell.post("/webhooks/resend",content=body,headers=headers).status_code==404
print("PASS: signed Resend webhook, malformed/empty secret and bad/stale signature rejection, duplicate idempotency, delivered/bounced/suppressed states, out-of-order event protection, early-webhook race reconciliation, and public /api mount path")
