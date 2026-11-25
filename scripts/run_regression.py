#!/usr/bin/env python3
"""Deterministic B-ROUTE regression runner. Each scenario runs in a fresh process."""
from __future__ import annotations

import ast
import os
import re
import subprocess
import sys
import tempfile
from html.parser import HTMLParser
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
PYTHON = sys.executable


def run(command: list[str], *, env=None, input_text: str | None = None) -> None:
    label = " ".join(command[:4])
    print(f"\n[CHECK] {label}", flush=True)
    subprocess.run(command, cwd=ROOT, env=env, input=input_text, text=True, check=True)


def check_python_syntax() -> None:
    run([PYTHON, "-m", "compileall", "-q", "cloud-functions/api", "server.py", "workers", "tests", "scripts"])
    # GitHub Actions targets Python 3.11; the local runner may use a newer
    # interpreter, so also parse every shipped Python file with 3.11 grammar.
    for base in (ROOT / "cloud-functions" / "api", ROOT / "workers", ROOT / "tests", ROOT / "scripts"):
        for source in sorted(base.rglob("*.py")):
            ast.parse(source.read_text(encoding="utf-8"), filename=str(source), feature_version=(3, 11))
    for source in (ROOT / "server.py",):
        ast.parse(source.read_text(encoding="utf-8"), filename=str(source), feature_version=(3, 11))
    print("[PASS] Python syntax is compatible with the CI target (3.11)")


def check_frontend_syntax() -> None:
    node = subprocess.run(["node", "--version"], cwd=ROOT, capture_output=True, text=True)
    print(f"[INFO] Node {node.stdout.strip()}")
    with tempfile.TemporaryDirectory(prefix="broute-js-check-") as tmp:
        tmp_path = Path(tmp)
        for html_name in ("index.html", "admin.html"):
            source = (ROOT / html_name).read_text(encoding="utf-8")
            blocks = re.findall(r"<script(?:\s[^>]*)?>(.*?)</script>", source, flags=re.I | re.S)
            if not blocks:
                raise AssertionError(f"No inline script block found in {html_name}")
            for index, block in enumerate(blocks):
                if not block.strip():
                    continue
                script_file = tmp_path / f"{Path(html_name).stem}-{index}.js"
                script_file.write_text(block, encoding="utf-8")
                run(["node", "--check", str(script_file)])
        run(["node", "--check", str(ROOT / "sw.js")])


class IdCollector(HTMLParser):
    def __init__(self):
        super().__init__()
        self.ids: set[str] = set()
        self.duplicates: set[str] = set()

    def handle_starttag(self, tag, attrs):
        for key, value in attrs:
            if key == "id" and value:
                if value in self.ids:
                    self.duplicates.add(value)
                self.ids.add(value)


def check_html_ids() -> None:
    for name in ("index.html", "admin.html"):
        parser = IdCollector()
        parser.feed((ROOT / name).read_text(encoding="utf-8"))
        if parser.duplicates:
            raise AssertionError(f"Duplicate HTML IDs in {name}: {sorted(parser.duplicates)}")
        source = (ROOT / name).read_text(encoding="utf-8")
        literal_refs = set(re.findall(r"\$\(['\"]([A-Za-z][A-Za-z0-9_-]*)['\"]\)", source))
        # A few controls are injected with innerHTML only after an API response
        # (for example, the invite-accept and route-result buttons). Count a
        # literal id declaration in a template as a valid dynamic element.
        dynamic_ids = {ref for ref in literal_refs
                       if re.search(rf"\bid\s*=\s*['\"]{re.escape(ref)}['\"]", source)}
        missing_refs = sorted(literal_refs - parser.ids - dynamic_ids)
        if missing_refs:
            raise AssertionError(f"Missing DOM IDs referenced by JavaScript in {name}: {missing_refs}")
        print(f"[PASS] {name}: {len(parser.ids)} unique IDs, {len(literal_refs)} literal DOM references resolved")


def check_workflow_yaml() -> None:
    workflow_files = sorted((ROOT / ".github" / "workflows").glob("*.yml")) + sorted((ROOT / ".github" / "workflows").glob("*.yaml"))
    if not workflow_files:
        raise AssertionError("No GitHub Actions workflow files found")
    for workflow in workflow_files:
        doc = yaml.safe_load(workflow.read_text(encoding="utf-8"))
        if not isinstance(doc, dict) or not isinstance(doc.get("jobs"), dict):
            raise AssertionError(f"Invalid workflow structure: {workflow}")
        # PyYAML's YAML 1.1 parser reads the GitHub key `on` as boolean True.
        if "on" not in doc and True not in doc:
            raise AssertionError(f"Missing workflow triggers: {workflow}")
        for job_name, job in doc["jobs"].items():
            for index, step in enumerate(job.get("steps", [])):
                script = step.get("run")
                if script:
                    subprocess.run(["bash", "-n"], input=script, text=True, cwd=ROOT, check=True)
        print(f"[PASS] workflow YAML + embedded shell: {workflow.relative_to(ROOT)}")


def check_release_metadata() -> None:
    expected = "2.0.0-beta.1"
    if (ROOT / "VERSION").read_text(encoding="utf-8").strip() != expected:
        raise AssertionError("VERSION file does not match the candidate release")
    checks = {
        "cloud-functions/api/index.py": 'version=APP_VERSION',
        "server.py": 'version=api_module.APP_VERSION',
        "index.html": "B-ROUTE 2.0.0-beta.1",
        "admin.html": "B-ROUTE 2.0.0-beta.1",
        "manifest.json": expected,
        "sw.js": "broute-shell-2-0-beta-1",
    }
    for relative, token in checks.items():
        data = (ROOT / relative).read_text(encoding="utf-8")
        if token not in data:
            raise AssertionError(f"Release version marker mismatch: {relative} missing {token!r}")
    frontend = (ROOT / "index.html").read_text(encoding="utf-8")
    backend = (ROOT / "cloud-functions" / "api" / "index.py").read_text(encoding="utf-8")
    if "hashParams.get('invite')||queryParams.get('invite')" not in frontend:
        raise AssertionError("Email invitation fragment parser is missing")
    if "api('/project-invites/preview'" not in frontend or "api('/project-invites/accept'" not in frontend:
        raise AssertionError("New invite preview/accept endpoints must send tokens in POST bodies")
    if "api(`/project-invites/${encodeURIComponent(token)}" in frontend:
        raise AssertionError("Frontend must not place raw invitation tokens in API URL paths")
    if frontend.count("location.pathname+location.search+location.hash") < 2:
        raise AssertionError("Naver/Microsoft OAuth return must preserve the invitation fragment")
    if '"/#invite=" + raw_token' not in backend:
        raise AssertionError("New invitation tokens must be placed in the browser fragment")
    if "path_query + separator + \"auth=success\"" not in backend:
        raise AssertionError("OAuth success URL must keep auth query before invite fragment")
    if "@app.post(\"/webhooks/resend\")" not in backend or "_verify_resend_webhook" not in backend:
        raise AssertionError("Signed Resend delivery webhook is missing")
    env_example = (ROOT / ".env.example").read_text(encoding="utf-8")
    if "RESEND_WEBHOOK_SECRET" not in env_example:
        raise AssertionError("Webhook secret configuration is missing")
    if "/api/webhooks/resend" not in env_example:
        raise AssertionError("The externally mounted webhook URL must include /api")
    email_doc = (ROOT / "README-1.95-Email-Delivery-Webhooks.md").read_text(encoding="utf-8")
    if "https://서비스도메인/api/webhooks/resend" not in email_doc:
        raise AssertionError("The Resend setup guide has the wrong public webhook URL")
    deploy = (ROOT / ".github/workflows/deploy-cloud-run.yml").read_text(encoding="utf-8")
    for secret_name, env_name in (("OPTIONAL_RESEND_API_KEY_NAME", "RESEND_API_KEY"),
                                  ("OPTIONAL_RESEND_WEBHOOK_SECRET_NAME", "RESEND_WEBHOOK_SECRET"),
                                  ("OPTIONAL_INVITE_FROM_EMAIL_SECRET_NAME", "INVITE_FROM_EMAIL")):
        if secret_name not in deploy or f'"{env_name}"' not in deploy:
            raise AssertionError(f"Cloud Run deploy is missing optional Secret Manager mapping: {env_name}")
    for env_name in ("INVITE_REPLY_TO_EMAIL", "INVITE_FROM_NAME", "INVITE_EMAIL_DAILY_LIMIT"):
        if env_name not in deploy:
            raise AssertionError(f"Cloud Run deploy does not pass invitation setting: {env_name}")
    if "if: vars.GTFS_WORKER_IMAGE_BUILD_ENABLED == 'true'" not in deploy:
        raise AssertionError("GTFS worker image build must require explicit opt-in")
    if "APP_VERSION=2.0.0-beta.1" not in env_example:
        raise AssertionError("The beta runtime version must be explicit in .env.example")
    if "BETA_RELEASE_APPROVED=false" not in env_example:
        raise AssertionError("The beta release gate must remain disabled by default")
    if "vars.GCP_DEPLOY_ENABLED == 'true'" not in deploy or "vars.BETA_DEPLOY_APPROVED == 'true'" not in deploy:
        raise AssertionError("Cloud Run beta deployment must remain explicitly gated")
    if "BETA_PUBLIC_ACCESS_APPROVED: ${{ vars.BETA_PUBLIC_ACCESS_APPROVED || 'false' }}" not in deploy:
        raise AssertionError("Cloud Run beta must default to non-public access")
    if 'ACCESS_ARGS=(--no-allow-unauthenticated)' not in deploy:
        raise AssertionError("Closed-beta deployment must disable anonymous Cloud Run access by default")
    worker = (ROOT / "workers" / "gtfs_import_worker.py").read_text(encoding="utf-8")
    if 'api.APP_VERSION' not in worker or '"1.94.0"' in worker:
        raise AssertionError("GTFS worker heartbeat version must match the API runtime version")
    version_source = (ROOT / "cloud-functions" / "api" / "index.py").read_text(encoding="utf-8")
    if 'APP_VERSION = os.getenv("APP_VERSION", "2.0.0-beta.1")' not in version_source:
        raise AssertionError("The API runtime version source is missing")
    app_dockerfile = (ROOT / "Dockerfile").read_text(encoding="utf-8")
    worker_dockerfile = (ROOT / "workers" / "Dockerfile").read_text(encoding="utf-8")
    if "FROM python:3.11-slim" not in app_dockerfile or "FROM python:3.11-slim" not in worker_dockerfile:
        raise AssertionError("App and GTFS worker Docker images must use the Python 3.11 CI target")
    if (ROOT / ".env").exists():
        raise AssertionError("A real .env file must not be included in the project")
    if not (ROOT / ".env.example").is_file():
        raise AssertionError(".env.example is required")
    print("[PASS] release metadata and secret-file hygiene")


def run_scenarios() -> None:
    scenarios = sorted((ROOT / "tests" / "scenarios").glob("scenario_*.py"))
    if not scenarios:
        raise AssertionError("No regression scenarios found")
    env = os.environ.copy()
    env["PYTHONPATH"] = str(ROOT / "cloud-functions") + os.pathsep + env.get("PYTHONPATH", "")
    for scenario in scenarios:
        run([PYTHON, str(scenario)], env=env)
    print(f"\n[PASS] {len(scenarios)} isolated regression scenarios")


def main() -> int:
    os.chdir(ROOT)
    check_python_syntax()
    check_frontend_syntax()
    check_html_ids()
    check_workflow_yaml()
    check_release_metadata()
    run_scenarios()
    print("\nB-ROUTE 2.0.0-beta.1 LOCAL CI: ALL CHECKS PASSED")
    print("Container image builds are executed by GitHub Actions; run locally only when Docker is installed.")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except subprocess.CalledProcessError as exc:
        print(f"\n[FAIL] Command exited with status {exc.returncode}: {exc.cmd}", file=sys.stderr)
        raise SystemExit(exc.returncode or 1)
    except Exception as exc:
        print(f"\n[FAIL] {type(exc).__name__}: {exc}", file=sys.stderr)
        raise SystemExit(1)
