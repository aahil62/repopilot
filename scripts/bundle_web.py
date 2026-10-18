"""Build the web UI and bundle it into the Python package, then build a wheel.

    backend/.venv/bin/python scripts/bundle_web.py      # -> dist/repopilot-<version>-py3-none-any.whl
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
WEB = ROOT / "web"
STATIC = ROOT / "backend" / "repopilot" / "static"


def run(*cmd: str, cwd: Path = ROOT, env: dict | None = None) -> None:
    print("$", " ".join(cmd))
    subprocess.run(cmd, cwd=cwd, check=True, env=env)


def main() -> None:
    env = {k: v for k, v in os.environ.items() if k != "NEXT_PUBLIC_DEMO_MODE"}
    if not (WEB / "node_modules").exists():
        run("npm", "ci", cwd=WEB)
    run("npm", "run", "build", cwd=WEB, env=env)
    shutil.rmtree(STATIC, ignore_errors=True)
    shutil.copytree(WEB / "out", STATIC)
    print(f"Bundled web UI into {STATIC.relative_to(ROOT)}")
    dist = ROOT / "dist"
    dist.mkdir(exist_ok=True)
    run(sys.executable, "-m", "pip", "wheel", "--no-deps", "-w", str(dist), str(ROOT / "backend"))


if __name__ == "__main__":
    main()
