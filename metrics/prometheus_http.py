from __future__ import annotations

import base64
import hmac
import logging
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any

from prometheus_client import CONTENT_TYPE_LATEST, generate_latest

from .config import Config


def expected_basic_auth_header(username: str, password: str) -> str:
    credentials = f"{username}:{password}".encode("utf-8")
    encoded_credentials = base64.b64encode(credentials).decode("ascii")
    return f"Basic {encoded_credentials}"


def make_metrics_handler(username: str, password: str) -> type[BaseHTTPRequestHandler]:
    expected_authorization = expected_basic_auth_header(username, password)

    class AuthenticatedMetricsHandler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:
            if self.path.split("?", 1)[0] != "/metrics":
                self.send_error(404)
                return

            authorization = self.headers.get("Authorization", "")
            if not hmac.compare_digest(authorization, expected_authorization):
                self.send_response(401)
                self.send_header(
                    "WWW-Authenticate",
                    'Basic realm="remnawave metrics"',
                )
                self.end_headers()
                return

            output = generate_latest()
            self.send_response(200)
            self.send_header("Content-Type", CONTENT_TYPE_LATEST)
            self.send_header("Content-Length", str(len(output)))
            self.end_headers()
            self.wfile.write(output)

        def log_message(self, format: str, *args: Any) -> None:
            logging.debug("Metrics HTTP request: " + format, *args)

    return AuthenticatedMetricsHandler


def start_metrics_server(config: Config) -> tuple[ThreadingHTTPServer, threading.Thread]:
    server = ThreadingHTTPServer(
        (config.prometheus_bind, config.prometheus_port),
        make_metrics_handler(
            config.prometheus_username,
            config.prometheus_password,
        ),
    )
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return server, thread
