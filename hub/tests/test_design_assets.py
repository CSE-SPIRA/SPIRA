"""Check the committed hub design outputs against their source."""

import subprocess
import sys
from pathlib import Path


def test_design_assets_are_current():
    root = Path(__file__).resolve().parents[2]
    subprocess.run(
        [sys.executable, str(root / "demo-shell/design/build.py"), "--check", "--part", "hub"],
        check=True,
    )
