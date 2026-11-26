"""Demo home: write the fake home (dev/home.yaml) into the server DB and give the demo stack its keys.

    cd server
    python scripts/demo_home.py --home dev/home.yaml
    source out/demo.env

Run before `scripts/demo-up --server` (repository root). The household is deleted and written again, with a new hub
key each time. The calendar is relative to now (`+2d 14:00`) and tagged by the server LLM, as in a dry run.
out/demo.env (mode 600, never committed) holds SPIRA_HOUSEHOLD_ID, SPIRA_HUB_KEY and SPIRA_APP_TOKEN; the keys are
not printed.
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

SERVER = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SERVER))


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--home", required=True, type=Path, help="fake home yaml (dev/home.example.yaml)")
    p.add_argument("--household", help="household id instead of the one in the yaml (h_ + lowercase/digits)")
    p.add_argument("--out", type=Path, default=SERVER / "out" / "demo.env")
    args = p.parse_args(argv)

    from alembic import command
    from alembic.config import Config

    from spira_server import clock
    from spira_server.api.auth import new_hub_key
    from spira_server.dev.seed import HomeError, load_home, seed
    from spira_server.settings import get_settings

    settings = get_settings()
    cfg = Config(str(SERVER / "alembic.ini"))
    cfg.set_main_option("script_location", str(SERVER / "migrations"))
    command.upgrade(cfg, "head")

    now = clock.now()
    try:
        home = load_home(args.home, now)
    except HomeError as e:
        print(f"home.yaml: {e}", file=sys.stderr)
        return 2
    if args.household:
        home.household_id = args.household
        home.devices["household_id"] = args.household
    key, digest = new_hub_key()
    written = seed(home, now, hub_key_hash=digest)
    if written["calendar"] and not written["calendar_tagged"]:
        print("calendar was stored but not tagged (LLM call failed): S3 will see no events", file=sys.stderr)

    args.out.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(args.out, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        f.write(f"export SPIRA_HOUSEHOLD_ID={home.household_id}\n")
        f.write(f"export SPIRA_HUB_KEY={key}\n")
        f.write(f"export SPIRA_APP_TOKEN={settings.app_demo_token}\n")
    print(f"demo home {home.household_id}: {written['devices']} devices, {written['calendar']} calendar events "
          f"(tagged: {written['calendar_tagged']}), {written['past_orders']} past orders, now={clock.iso(now)}")
    print(f"keys -> {args.out} (source it before scripts/demo-up)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
