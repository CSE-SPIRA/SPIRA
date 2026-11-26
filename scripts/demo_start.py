"""Serve the demo's loopback start page and live guest-window status."""

import json
from contextlib import contextmanager
from datetime import datetime
from html import escape
from hmac import compare_digest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from math import ceil
from pathlib import Path
from string import Template
from threading import Thread


PAGE = Path(__file__).with_name("demo_start.html")
DESIGN = PAGE.parents[1] / "simulator/spira_simulator/ui/house"
ASSETS = {
    f"/{name}.css": (DESIGN / f"{name}.css", "text/css; charset=utf-8")
    for name in ("tokens", "fonts")
}
ASSETS["/fonts/LICENSE.txt"] = (DESIGN / "fonts/LICENSE.txt", "text/plain; charset=utf-8")
ASSETS.update({
    f"/fonts/{path.name}": (path, "font/woff2")
    for path in (DESIGN / "fonts").glob("*.woff2")
})


def guest_window(state):
    def bounds(row):
        trigger = row.get("trigger", {})
        if trigger.get("event") == "guest_arrived" and (window := trigger.get("window")):
            return tuple(datetime.fromisoformat(window[bound]) for bound in ("from", "to"))
        return None

    # Hub task stories retain the actual trigger even after its waiting row
    # disappears on arrival or after the party closes.
    windows = [bounds(row) for row in state["waiting"]]
    windows.extend(
        next((window for step in reversed(story["steps"]) if (window := bounds(step))), None)
        for story in state.get("task_stories", [])
    )
    return max(filter(None, windows), default=None)


def window_status(window, now):
    if window is None or now < window[0]:
        return {"status": "pending"}
    if now > window[1]:
        return {"status": "passed"}
    return {"status": "open", "minutes": max(1, ceil((window[1] - now).total_seconds() / 60))}


def render(urls):
    def link(url, name, description):
        label = f"<strong>{name}</strong><span>{description}</span>"
        if url:
            return f'<a href="{escape(url)}" target="_blank" rel="noopener">{label}</a>'
        return f'<div>{label}</div>'

    app_url = urls.get("app")
    app_description = ("휴대폰 화면에서 예시 주문을 공유하고 이야기를 봐요." if app_url
                       else "이번 실행에서는 앱 미리보기가 꺼져 있어요.")
    if app_url and "server" in urls:
        app_description = "주문 화면을 공유하고 서버가 보낸 준비를 봐요."
    shell_label = "시연 화면(제품 아님)" if "server" in urls else "예시 연출(제품 아님)"
    return Template(PAGE.read_text(encoding="utf-8")).substitute(
        app=link(app_url, "앱", app_description),
        viewer=link(urls["viewer"], "집 화면", "집과 기기의 변화를 3D로 봐요."),
        operator=link(urls["operator"], "집에서 일어나는 일", "택배를 들이고 손님을 맞이해요."),
        hub=link(urls["hub"], "Hub", "집이 받은 계획과 기기가 움직인 기록을 봐요."),
        shell=(f'<p class="shell"><a href="{escape(urls["shell"])}" target="_blank" rel="noopener">'
               f'{shell_label}</a></p>' if "shell" in urls else ""),
        reset=("<li>다시 시연할 때는 시연 화면의 <strong>진행자 조작 → 새로 시작</strong>을 눌러요.</li>"
               if "shell" in urls else ""),
    ).encode()


@contextmanager
def serve_start_page(port, urls, get_window, get_now, *, reset=None, reset_token=None):
    document = render(urls)

    class StartPage(BaseHTTPRequestHandler):
        def do_GET(self):
            if self.path == "/":
                body, content_type = document, "text/html; charset=utf-8"
            elif self.path == "/guest-window":
                try:
                    body = json.dumps(window_status(get_window(), get_now())).encode()
                except (OSError, ValueError, KeyError):
                    self.send_error(503)
                    return
                content_type = "application/json"
            elif self.path in ASSETS:
                asset, content_type = ASSETS[self.path]
                body = asset.read_bytes()
            else:
                self.send_error(404)
                return
            self.send_response(200)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(body)))
            if self.path in ("/", "/guest-window"):
                self.send_header("Cache-Control", "no-store")
            self.end_headers()
            if self.command != "HEAD":
                self.wfile.write(body)

        do_HEAD = do_GET

        def do_POST(self):
            if self.path != "/reset" or not reset_token:
                self.send_error(404)
                return
            if (self.client_address[0] != "127.0.0.1"
                    or self.headers.get("Host") != f"127.0.0.1:{self.server.server_port}"
                    or not compare_digest(self.headers.get("Authorization", "").encode(),
                                          f"Bearer {reset_token}".encode())):
                self.send_error(403)
                return
            self.send_response(reset())
            self.send_header("Content-Length", "0")
            self.end_headers()

        def log_message(self, *_):
            pass

    with ThreadingHTTPServer(("127.0.0.1", port), StartPage) as server:
        thread = Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            yield server.server_port
        finally:
            server.shutdown()
            thread.join()
