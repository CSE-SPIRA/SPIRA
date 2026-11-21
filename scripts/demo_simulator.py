"""Run the Simulator with the same bind address for HTTP and operator policy."""

import argparse

import uvicorn
from spira_simulator.api import create_app


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--host", required=True)
    parser.add_argument("--port", required=True, type=int)
    args = parser.parse_args()
    uvicorn.run(create_app(bind_host=args.host), host=args.host, port=args.port, access_log=False)


if __name__ == "__main__":
    main()
