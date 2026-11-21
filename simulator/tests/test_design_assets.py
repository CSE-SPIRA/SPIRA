"""Check the committed simulator design outputs against their source."""

import subprocess
import sys
from pathlib import Path


def test_design_assets_are_current():
    root = Path(__file__).resolve().parents[2]
    subprocess.run(
        [sys.executable, str(root / "design/build.py"), "--check", "--part", "simulator"],
        check=True,
    )
