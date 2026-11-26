import argparse
import os

import uvicorn

from .api import LABEL, create_app
from .replay import EPISODES
from .scene_support import NextOrder


def main():
    parser = argparse.ArgumentParser(description=LABEL)
    parser.add_argument("--episode", choices=EPISODES, default=EPISODES[0])
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8000)
    parser.add_argument(
        "--scene-controls", action="store_true",
        help="Enable live scene controls for the selected episode's household; start unpublished",
    )
    parser.add_argument(
        "--default-scene", choices=EPISODES, default=os.getenv("SPIRA_FIXTURE_DEFAULT_SCENE"),
        help="Publish this live scene on each new order (env: SPIRA_FIXTURE_DEFAULT_SCENE)",
    )
    options = parser.parse_args()
    if (options.scene_controls or options.default_scene) and options.host != "127.0.0.1":
        parser.error("Live scene controls require loopback")
    try:
        default_scene = NextOrder(episode_id=options.default_scene) if options.default_scene else None
        app = create_app(
            options.episode,
            scene_controls=options.scene_controls,
            demo_mode=os.getenv("DEMO_MODE") == "1",
            default_scene=default_scene,
        )
    except ValueError as error:
        parser.error(str(error))
    print(f"{LABEL} ({options.episode})", flush=True)
    uvicorn.run(
        app,
        host=options.host,
        port=options.port,
        access_log=False,
    )


if __name__ == "__main__":
    main()
