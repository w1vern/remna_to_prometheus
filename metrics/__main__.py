from __future__ import annotations

import logging
import os
import sys
import time
from typing import Any

from load_dotenv import load_dotenv

from metrics.api import RemnawaveClient
from metrics.collectors import DEFAULT_COLLECTORS
from metrics.config import Config
from metrics.prometheus_http import start_metrics_server
from metrics.scrape_metrics import (
    REMNAWAVE_EXPORTER_UP,
    REMNAWAVE_LAST_SCRAPE_DURATION,
    REMNAWAVE_LAST_SCRAPE_TIMESTAMP,
    REMNAWAVE_SCRAPE_ERRORS_TOTAL,
)

load_dotenv()


def payload_size(payload: Any) -> str:
    try:
        return str(len(payload))
    except TypeError:
        return "unknown"


def run_exporter() -> None:
    config = Config.from_env()
    config.validate()

    client = RemnawaveClient(config)

    start_metrics_server(config)
    logging.info(
        "Serving metrics on http://%s:%s/metrics",
        config.prometheus_bind,
        config.prometheus_port,
    )

    while True:
        started_at = time.monotonic()

        try:
            scrape_summary: list[str] = []
            for collector in DEFAULT_COLLECTORS:
                payload = collector.collect(client)
                collector.update_metrics(payload)
                scrape_summary.append(f"{collector.name}={payload_size(payload)}")

            REMNAWAVE_EXPORTER_UP.set(1)
            REMNAWAVE_LAST_SCRAPE_TIMESTAMP.set(time.time())
            logging.info("Exported Remnawave metrics: %s", ", ".join(scrape_summary))
        except Exception:
            REMNAWAVE_EXPORTER_UP.set(0)
            REMNAWAVE_SCRAPE_ERRORS_TOTAL.inc()
            logging.exception("Failed to scrape Remnawave")
        finally:
            duration = time.monotonic() - started_at
            REMNAWAVE_LAST_SCRAPE_DURATION.set(duration)
            time.sleep(max(0.0, config.interval_seconds - duration))


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
