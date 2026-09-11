"""One cross-platform verification command; the checks run in isolated Docker storage."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def run(*args: str, cwd: Path = ROOT) -> None:
    subprocess.run(args, cwd=cwd, check=True)


def main() -> None:
    if "--inside" not in sys.argv:
        run("docker", "info", "--format", "{{.ServerVersion}}")
        run("docker", "compose", "config", "--quiet")
        run("docker", "compose", "--profile", "verify", "build", "verify")
        run("docker", "compose", "--profile", "verify", "run", "--rm", "verify")
        return
    for args in (
        (
            "ruff",
            "check",
            "backend",
            "scripts/export-openapi.py",
            "scripts/verify.py",
            "scripts/browser_acceptance_app.py",
            "scripts/check-setup.py",
        ),
        (
            "ruff",
            "format",
            "--check",
            "backend",
            "scripts/export-openapi.py",
            "scripts/verify.py",
            "scripts/browser_acceptance_app.py",
            "scripts/check-setup.py",
        ),
        ("mypy", "backend/src"),
        ("pytest", "backend/tests", "-q"),
    ):
        run("uv", "run", "--project", "backend", *args)
    run("npm", "run", "verify", cwd=ROOT / "frontend")


if __name__ == "__main__":
    try:
        main()
    except subprocess.CalledProcessError as error:
        sys.exit(error.returncode)
