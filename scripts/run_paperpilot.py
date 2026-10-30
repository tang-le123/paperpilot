"""One-click local launcher for PaperPilot.

Builds the React bundle if missing, then starts FastAPI on 127.0.0.1:8001.
"""
from __future__ import annotations

import os
import subprocess
import sys
import webbrowser
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FRONTEND = ROOT / "frontend_react"
DIST = FRONTEND / "dist" / "index.html"
BACKEND = ROOT / "backend"


def main() -> None:
    if not DIST.exists():
        print("React build not found; running npm run build...")
        subprocess.run(["cmd", "/c", "npm", "run", "build"], cwd=FRONTEND, check=True)
    os.chdir(BACKEND)
    webbrowser.open("http://127.0.0.1:8001")
    subprocess.run(
        [
            sys.executable,
            "-m",
            "uvicorn",
            "app.main:app",
            "--host",
            "127.0.0.1",
            "--port",
            "8001",
        ],
        check=False,
    )


if __name__ == "__main__":
    main()
