import argparse
import os

import uvicorn

from .api import LABEL, create_app
from .replay import EPISODES


def main():
    parser = argparse.ArgumentParser(description=LABEL)
    parser.add_argument("--episode", choices=EPISODES, default=EPISODES[0])
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8000)
    parser.add_argument(
        "--scene-controls", action="store_true",
        help="Enable live scene controls for the selected episode's household; start unpublished",
    )
    options = parser.parse_args()
    if options.scene_controls and options.host != "127.0.0.1":
        parser.error("--scene-controls requires loopback")
    print(f"{LABEL} ({options.episode})", flush=True)
    uvicorn.run(
        create_app(
            options.episode,
            scene_controls=options.scene_controls,
            demo_mode=os.getenv("DEMO_MODE") == "1",
        ),
        host=options.host,
        port=options.port,
        access_log=False,
    )


if __name__ == "__main__":
    main()
