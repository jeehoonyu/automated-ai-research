from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import venv
from pathlib import Path


def main() -> None:
    repository = Path(__file__).resolve().parents[1]
    wheels = sorted((repository / "dist").glob("automated_ai_research-*.whl"))
    if len(wheels) != 1:
        raise SystemExit(f"Expected exactly one project wheel in dist, found {len(wheels)}")
    with tempfile.TemporaryDirectory(prefix="research-wheel-smoke-") as temporary:
        root = Path(temporary)
        environment = root / "venv"
        venv.EnvBuilder(with_pip=True).create(environment)
        python = environment / ("Scripts/python.exe" if sys.platform == "win32" else "bin/python")
        subprocess.run(
            [
                str(python),
                "-m",
                "pip",
                "--disable-pip-version-check",
                "install",
                str(wheels[0]),
            ],
            cwd=root,
            check=True,
        )
        help_result = subprocess.run(
            [str(python), "-m", "research", "--help"],
            cwd=root,
            check=True,
            capture_output=True,
            text=True,
        )
        if "Local-first evidence processing" not in help_result.stdout:
            raise SystemExit("Installed wheel did not expose the expected research CLI")
        workspace = root / "workspace"
        initialized = subprocess.run(
            [str(python), "-m", "research", "init", str(workspace), "--json"],
            cwd=root,
            check=True,
            capture_output=True,
            text=True,
        )
        envelope = json.loads(initialized.stdout)
        if envelope.get("status") != "success" or not (workspace / "schemas" / "v1").is_dir():
            raise SystemExit("Installed wheel could not initialize its packaged schema catalog")


if __name__ == "__main__":
    main()
