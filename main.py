"""
Remnawave per-user traffic Prometheus exporter.

The exporter fetches all Remnawave users from GET /api/users and exposes
the all-time traffic counter for each user as Prometheus metrics.
"""

from __future__ import annotations

import base64
import hmac
import logging
import os
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any

import requests
from load_dotenv import load_dotenv
from prometheus_client import CONTENT_TYPE_LATEST, Counter, Gauge, generate_latest

load_dotenv()

BASE_URL = os.getenv("BASE_URL", "").strip()
API_TOKEN = os.getenv("API_TOKEN", "")
INTERVAL_SECONDS = int(os.getenv("INTERVAL_SECONDS", "10"))
PROMETHEUS_PORT = int(os.getenv("PROMETHEUS_PORT", "9100"))
PROMETHEUS_BIND = os.getenv("PROMETHEUS_BIND", "0.0.0.0")
PROMETHEUS_USERNAME = os.getenv("PROMETHEUS_USERNAME", "")
PROMETHEUS_PASSWORD = os.getenv("PROMETHEUS_PASSWORD", "")
PAGE_SIZE = int(os.getenv("PAGE_SIZE", "100"))
REQUEST_TIMEOUT = float(os.getenv("REQUEST_TIMEOUT", "15"))

USER_LABELS = ("username", "status")

USER_LIFETIME_TRAFFIC_BYTES = Gauge(
    "remnawave_user_lifetime_traffic_bytes",
    "All-time user traffic reported by Remnawave, in bytes.",
    USER_LABELS,
)
REMNAWAVE_USERS_TOTAL = Gauge(
    "remnawave_users_total",
    "Number of users returned by the last successful Remnawave scrape.",
)
REMNAWAVE_EXPORTER_UP = Gauge(
    "remnawave_exporter_up",
    "1 if the last Remnawave scrape succeeded, 0 otherwise.",
)
REMNAWAVE_LAST_SCRAPE_TIMESTAMP = Gauge(
    "remnawave_last_scrape_timestamp_seconds",
    "Unix timestamp of the last successful Remnawave scrape.",
)
REMNAWAVE_LAST_SCRAPE_DURATION = Gauge(
    "remnawave_last_scrape_duration_seconds",
    "Duration of the last Remnawave scrape in seconds.",
)
REMNAWAVE_SCRAPE_ERRORS_TOTAL = Counter(
    "remnawave_scrape_errors_total",
    "Total number of failed Remnawave scrapes.",
)

_known_user_label_values: set[tuple[str, str]] = set()


def api_base_url() -> str:
    base_url = BASE_URL.rstrip("/")
    if not base_url.endswith("/api"):
        base_url = f"{base_url}/api"
    return base_url


def auth_headers() -> dict[str, str]:
    token = API_TOKEN.strip()
    if token and not token.startswith("Bearer "):
        token = f"Bearer {token}"

    return {
        "Accept": "application/json",
        "Authorization": token,
    }


def unwrap_response(payload: Any) -> dict[str, Any]:
    if not isinstance(payload, dict):
        raise ValueError("Remnawave response is not a JSON object")

    for wrapper_key in ("response", "data"):
        wrapped = payload.get(wrapper_key)
        if isinstance(wrapped, dict) and "users" in wrapped:
            return wrapped

    return payload


def fetch_users_page(
    session: requests.Session,
    start: int,
    size: int,
) -> tuple[list[dict[str, Any]], int | None]:
    response = session.get(
        f"{api_base_url()}/users",
        params={"start": start, "size": size},
        timeout=REQUEST_TIMEOUT,
    )

    if not response.ok:
        body = response.text[:300].replace("\n", " ")
        raise RuntimeError(
            f"Remnawave API returned HTTP {response.status_code}: {body}"
        )

    data = unwrap_response(response.json())
    users = data.get("users")
    total = data.get("total")

    if not isinstance(users, list):
        raise ValueError("Remnawave response does not contain a users list")

    if total is not None:
        total = int(total)

    return users, total


def fetch_all_users(session: requests.Session) -> list[dict[str, Any]]:
    users: list[dict[str, Any]] = []
    start = 0
    total: int | None = None

    while True:
        page, total = fetch_users_page(session, start=start, size=PAGE_SIZE)
        users.extend(page)

        if not page:
            break
        if total is not None and len(users) >= total:
            break
        if len(page) < PAGE_SIZE and total is None:
            break

        start += len(page)

    return users


def label_value(value: Any) -> str:
    if value is None:
        return ""
    return str(value)


def user_label_values(user: dict[str, Any]) -> tuple[str, str]:
    return (
        label_value(user.get("username")),
        label_value(user.get("status")),
    )


def to_float(value: Any) -> float:
    if value is None or value == "":
        return 0.0
    return float(value)


def lifetime_traffic_bytes(user: dict[str, Any]) -> float:
    user_traffic = user.get("userTraffic") or user.get("user_traffic")
    if isinstance(user_traffic, dict):
        value = user_traffic.get("lifetimeUsedTrafficBytes")
        if value is None:
            value = user_traffic.get("lifetime_used_traffic_bytes")
        if value is not None:
            return to_float(value)

    for key in (
        "lifetimeUsedTrafficBytes",
        "lifetime_used_traffic_bytes",
        "lifetimeTrafficUsedBytes",
    ):
        value = user.get(key)
        if value is not None:
            return to_float(value)

    return 0.0


def update_metrics(users: list[dict[str, Any]]) -> None:
    global _known_user_label_values

    current_label_values: set[tuple[str, str]] = set()

    for user in users:
        labels = user_label_values(user)
        if not labels[0]:
            logging.warning("Skipping user without username: %s", user)
            continue

        current_label_values.add(labels)
        USER_LIFETIME_TRAFFIC_BYTES.labels(
            *labels).set(lifetime_traffic_bytes(user))

    for stale_labels in _known_user_label_values - current_label_values:
        USER_LIFETIME_TRAFFIC_BYTES.remove(*stale_labels)

    _known_user_label_values = current_label_values
    REMNAWAVE_USERS_TOTAL.set(len(current_label_values))


def expected_basic_auth_header() -> str:
    credentials = f"{PROMETHEUS_USERNAME}:{PROMETHEUS_PASSWORD}".encode("utf-8")
    encoded_credentials = base64.b64encode(credentials).decode("ascii")
    return f"Basic {encoded_credentials}"


class AuthenticatedMetricsHandler(BaseHTTPRequestHandler):
    def do_GET(self) -> None:
        if self.path.split("?", 1)[0] != "/metrics":
            self.send_error(404)
            return

        authorization = self.headers.get("Authorization", "")
        if not hmac.compare_digest(authorization, expected_basic_auth_header()):
            self.send_response(401)
            self.send_header("WWW-Authenticate", 'Basic realm="remnawave metrics"')
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


def start_metrics_server() -> tuple[ThreadingHTTPServer, threading.Thread]:
    server = ThreadingHTTPServer(
        (PROMETHEUS_BIND, PROMETHEUS_PORT),
        AuthenticatedMetricsHandler,
    )
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return server, thread


def validate_config() -> None:
    if not BASE_URL:
        raise ValueError("Set BASE_URL before starting the exporter")
    if not API_TOKEN.strip():
        raise ValueError("Set API_TOKEN before starting the exporter")
    if not PROMETHEUS_USERNAME.strip():
        raise ValueError("Set PROMETHEUS_USERNAME before starting the exporter")
    if not PROMETHEUS_PASSWORD:
        raise ValueError("Set PROMETHEUS_PASSWORD before starting the exporter")
    if INTERVAL_SECONDS <= 0:
        raise ValueError("INTERVAL_SECONDS must be greater than 0")
    if PAGE_SIZE <= 0:
        raise ValueError("PAGE_SIZE must be greater than 0")


def run_exporter() -> None:
    validate_config()

    session = requests.Session()
    session.headers.update(auth_headers())

    start_metrics_server()
    logging.info(
        "Serving metrics on http://%s:%s/metrics",
        PROMETHEUS_BIND,
        PROMETHEUS_PORT,
    )

    while True:
        started_at = time.monotonic()

        try:
            users = fetch_all_users(session)
            update_metrics(users)

            REMNAWAVE_EXPORTER_UP.set(1)
            REMNAWAVE_LAST_SCRAPE_TIMESTAMP.set(time.time())
            logging.info("Exported traffic metrics for %s users", len(users))
        except Exception:
            REMNAWAVE_EXPORTER_UP.set(0)
            REMNAWAVE_SCRAPE_ERRORS_TOTAL.inc()
            logging.exception("Failed to scrape Remnawave users")
        finally:
            duration = time.monotonic() - started_at
            REMNAWAVE_LAST_SCRAPE_DURATION.set(duration)
            time.sleep(max(0.0, INTERVAL_SECONDS - duration))


def main() -> int:
    logging.basicConfig(
        level=os.getenv("LOG_LEVEL", "INFO"),
        format="%(asctime)s %(levelname)s %(message)s",
    )

    try:
        run_exporter()
    except KeyboardInterrupt:
        logging.info("Exporter stopped")
        return 0
    except Exception as exc:
        logging.error("Exporter configuration error: %s", exc)
        return 1

    return 0


if __name__ == "__main__":
    sys.exit(main())
