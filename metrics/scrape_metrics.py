from __future__ import annotations

from prometheus_client import Counter, Gauge


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
