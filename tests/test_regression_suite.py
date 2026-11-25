"""Pytest entrypoint for the full isolated B-ROUTE regression suite."""
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]


def test_complete_local_regression_suite():
    subprocess.run([sys.executable, str(ROOT / "scripts" / "run_regression.py")], cwd=ROOT, check=True)
