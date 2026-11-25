"""OIDC ID-token signature/claim validation tests using generated local RSA keys."""
import importlib.util
import os
import tempfile
import time
from pathlib import Path

TMP = Path(tempfile.mkdtemp(prefix="broute192-oidc-"))
os.environ.update({
    "APP_ENV": "development",
    "DATA_DIR": str(TMP / "data"),
    "DATABASE_PATH": str(TMP / "data" / "oidc.sqlite3"),
    "SESSION_SECRET": "oidc-test-session-secret-" + "x" * 32,
})
ROOT = Path(__file__).resolve().parents[2]
API_PATH = ROOT / "cloud-functions" / "api" / "index.py"
spec = importlib.util.spec_from_file_location("broute192_oidc_api", API_PATH)
api = importlib.util.module_from_spec(spec)
import sys
sys.modules[spec.name] = api
spec.loader.exec_module(api)
api.init_db()

import jwt
from cryptography.hazmat.primitives.asymmetric import rsa
from fastapi import HTTPException

private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
public_jwk = jwt.algorithms.RSAAlgorithm.to_jwk(private_key.public_key(), as_dict=True)
public_jwk.update({"kid": "local-test-key", "use": "sig", "alg": "RS256"})
jwks = {"keys": [public_jwk]}
now = int(time.time())
claims = {
    "iss": "https://issuer.example.test",
    "aud": "broute-client-id",
    "sub": "provider-subject-123",
    "iat": now,
    "exp": now + 300,
    "nonce": "expected-nonce",
}


def token(overrides=None, algorithm="RS256"):
    body = dict(claims)
    body.update(overrides or {})
    if algorithm == "HS256":
        return jwt.encode(body, "not-an-rsa-key-that-is-long-enough-for-hmac-sha256", algorithm=algorithm, headers={"kid": "local-test-key"})
    return jwt.encode(body, private_key, algorithm=algorithm, headers={"kid": "local-test-key"})

verified = api._verify_oidc_id_token(token(), jwks, "broute-client-id", "https://issuer.example.test", "expected-nonce")
assert verified["sub"] == "provider-subject-123"

for bad_token in (
    token({"nonce": "wrong-nonce"}),
    token({"aud": "other-client"}),
    token({"iss": "https://attacker.example.test"}),
    token({"exp": now - 120}),
):
    try:
        api._verify_oidc_id_token(bad_token, jwks, "broute-client-id", "https://issuer.example.test", "expected-nonce")
        raise AssertionError("Invalid OIDC token was accepted")
    except HTTPException as exc:
        assert exc.status_code == 401

# Reject unsupported algorithms even when the token header identifies a known kid.
try:
    api._verify_oidc_id_token(token(algorithm="HS256"), jwks, "broute-client-id", "https://issuer.example.test", "expected-nonce")
    raise AssertionError("HS256 token was accepted")
except HTTPException as exc:
    assert exc.status_code == 401

# Callback destinations must remain same-origin relative paths.
from starlette.requests import Request
scope = {"type": "http", "method": "GET", "path": "/", "headers": [(b"host", b"testserver" )], "scheme": "https", "query_string": b""}
request = Request(scope)
api.APP_ORIGIN = "https://broute.example.test"
assert api._oauth_success_url(request, "/projects") == "https://broute.example.test/projects?auth=success"
assert api._oauth_success_url(request, "//evil.example/path").startswith("https://broute.example.test/?auth=success")
assert api._oauth_success_url(request, "/?lang=ko#invite=one-time-token") == "https://broute.example.test/?lang=ko&auth=success#invite=one-time-token"

print("PASS: RS256 signature, issuer, audience, expiry, nonce, algorithm and safe OAuth return URL")
