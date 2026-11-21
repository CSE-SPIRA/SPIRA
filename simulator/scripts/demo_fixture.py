"""Run the Hub's loopback demo fixture with a local rehearsal snapshot."""

import argparse
import pickle
from contextlib import asynccontextmanager
from pathlib import Path

import uvicorn
from hub.tests.fixture_server.api import create_app

# The fixture owns this in-memory state. Its route handlers share the cells
# below, including the active replay object that changes after an order share.
STATE = {
    "post_order": ("replay", "snapshots", "scene_counts", "pending_order", "active_order", "orders"),
    "get_plans": ("historical_package_replays",),
    "post_events": ("event_ids",),
    "post_execution": ("result_ids",),
}


def create_demo_fixture(episode, path):
    app = create_app(episode, scene_controls=True, demo_mode=True)
    endpoints = {route.name: route.endpoint for route in app.routes}
    cells = {}
    for name, keys in STATE.items():
        endpoint = endpoints[name]
        closure = dict(zip(endpoint.__code__.co_freevars, endpoint.__closure__, strict=True))
        cells.update({key: closure[key] for key in keys})

    original_lifespan = app.router.lifespan_context

    @asynccontextmanager
    async def lifespan(app):
        # The launcher supplies this path inside its private run directory.
        if path.exists():
            with path.open("rb") as source:
                saved = pickle.load(source)
            if saved.keys() != cells.keys():
                raise ValueError("The saved fixture state does not match this checkout")
            for key, cell in cells.items():
                cell.cell_contents = saved[key]

        async with original_lifespan(app):
            yield

        pending = path.with_suffix(".tmp")
        with pending.open("wb") as target:
            pickle.dump({key: cell.cell_contents for key, cell in cells.items()}, target)
        pending.replace(path)

    app.router.lifespan_context = lifespan
    return app


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--episode", required=True)
    parser.add_argument("--port", type=int, required=True)
    parser.add_argument("--state", type=Path, required=True)
    args = parser.parse_args()
    uvicorn.run(create_demo_fixture(args.episode, args.state), host="127.0.0.1",
                port=args.port, access_log=False)


if __name__ == "__main__":
    main()
