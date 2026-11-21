"""Connect Flutter's local Chrome dev server to the loopback demo stack."""

import argparse
from http.client import HTTPConnection, HTTPException
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import re


def loopback_port(value):
    match = re.fullmatch(r"http://127\.0\.0\.1:(\d{1,5})(/.*)?", value)
    if match and 0 < (port := int(match[1])) <= 65535:
        return port
    raise argparse.ArgumentTypeError("Use a demo-up URL on http://127.0.0.1:<port>")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for peer in ("fixture", "hub"):
        parser.add_argument(f"--{peer}", type=loopback_port, required=True)
    parser.add_argument("--port", type=int, default=8731)
    parser.add_argument("--web-port", type=int, default=8732)
    args = parser.parse_args()
    web_origin = f"http://127.0.0.1:{args.web_port}"

    class Proxy(BaseHTTPRequestHandler):
        def end_headers(self):
            if self.headers.get("Origin") == web_origin:
                self.send_header("Access-Control-Allow-Origin", web_origin)
                self.send_header("Vary", "Origin")
            self.send_header("Cache-Control", "no-store")
            super().end_headers()

        def do_OPTIONS(self):
            if self.headers.get("Origin") != web_origin:
                self.send_error(403)
                return
            self.send_response(204)
            self.send_header("Access-Control-Allow-Methods", "GET, POST, PUT, DELETE")
            self.send_header("Access-Control-Allow-Headers", "Authorization, Content-Type, X-API-Key")
            self.end_headers()

        def forward(self):
            if self.headers.get("Origin") != web_origin:
                self.send_error(403)
                return
            path = self.path.split("?", 1)[0]
            if self.command == "GET" and path == "/home/onboarding/devices":
                port, auth = args.hub, "X-API-Key"
            elif self.command == "POST" and path == "/v1/orders":
                port, auth = args.fixture, "Authorization"
            elif re.fullmatch(r"/v1/(households|episodes|cards)(/[A-Za-z0-9_-]+)*", path):
                port, auth = args.fixture, "Authorization"
            elif self.command == "GET" and path == "/health":
                port, auth = args.fixture, None
            else:
                self.send_error(404)
                return

            length = self.headers.get("Content-Length", "0")
            if not re.fullmatch(r"[0-9]{1,8}", length):
                self.send_error(400)
                return
            size = int(length)
            if size > 16 * 1024 * 1024:
                self.send_error(413)
                return
            headers = {"Accept": "application/json"}
            for name in ("Content-Type", auth):
                if name and name in self.headers:
                    headers[name] = self.headers[name]

            connection = HTTPConnection("127.0.0.1", port, timeout=35)
            try:
                connection.request(self.command, self.path, self.rfile.read(size), headers)
                upstream = connection.getresponse()
                body = upstream.read()
            except (OSError, HTTPException):
                self.send_error(502, "Demo service unavailable")
                return
            finally:
                connection.close()

            self.send_response(upstream.status)
            self.send_header("Content-Type", upstream.getheader("Content-Type", "application/json"))
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        do_GET = do_POST = do_PUT = do_DELETE = forward

    with ThreadingHTTPServer(("127.0.0.1", args.port), Proxy) as server:
        print(f"SPIRA_BASE_URL and SPIRA_HUB_URL: http://127.0.0.1:{args.port}", flush=True)
        try:
            server.serve_forever()
        except KeyboardInterrupt:
            pass


if __name__ == "__main__":
    main()
