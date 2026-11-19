import argparse

import uvicorn

from .api import LABEL, create_app
from .replay import EPISODES


def main():
    parser = argparse.ArgumentParser(description=LABEL)
    parser.add_argument("--episode", choices=EPISODES, default=EPISODES[0])
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8000)
    options = parser.parse_args()
    print(f"{LABEL} ({options.episode})", flush=True)
    uvicorn.run(
        create_app(options.episode),
        host=options.host,
        port=options.port,
        access_log=False,
    )


if __name__ == "__main__":
    main()
