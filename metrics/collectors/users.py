from __future__ import annotations

import logging
from typing import Any

from prometheus_client import Counter, Gauge

from metrics.api import RemnawaveClient

from .common import (
    first_present,
    label_value,
    remove_series,
    to_float,
    update_counter_from_total,
)


USER_LABELS = ("username", "status")

USER_LIFETIME_TRAFFIC_BYTES = Counter(
    "remnawave_user_lifetime_traffic_bytes",
    "All-time user traffic reported by Remnawave, in bytes.",
    USER_LABELS,
)
REMNAWAVE_USERS_TOTAL = Gauge(
    "remnawave_users_total",
    "Number of users returned by the last successful Remnawave scrape.",
)

_known_user_label_values: set[tuple[str, str]] = set()
_last_lifetime_traffic_bytes: dict[tuple[str, ...], float] = {}


class UserCollector:
    name = "users"

    def collect(self, client: RemnawaveClient) -> list[dict[str, Any]]:
        return client.fetch_all_users()

    def update_metrics(self, users: list[dict[str, Any]]) -> None:
        update_user_metrics(users)


def user_label_values(user: dict[str, Any]) -> tuple[str, str]:
    return (
        label_value(user.get("username")),
        label_value(user.get("status")),
    )


def lifetime_traffic_bytes(user: dict[str, Any]) -> float:
    user_traffic = user.get("userTraffic") or user.get("user_traffic")
    if isinstance(user_traffic, dict):
        value = first_present(
            user_traffic,
            "lifetimeUsedTrafficBytes",
            "lifetime_used_traffic_bytes",
        )
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


def update_user_metrics(users: list[dict[str, Any]]) -> None:
    global _known_user_label_values

    current_label_values: set[tuple[str, str]] = set()

    for user in users:
        labels = user_label_values(user)
        if not labels[0]:
            logging.warning("Skipping user without username: %s", user)
            continue

        current_label_values.add(labels)
        update_counter_from_total(
            USER_LIFETIME_TRAFFIC_BYTES,
            _last_lifetime_traffic_bytes,
            labels,
            lifetime_traffic_bytes(user),
            "lifetime traffic",
        )

    for stale_labels in _known_user_label_values - current_label_values:
        remove_series(USER_LIFETIME_TRAFFIC_BYTES, *stale_labels)
        _last_lifetime_traffic_bytes.pop(stale_labels, None)

    _known_user_label_values = current_label_values
    REMNAWAVE_USERS_TOTAL.set(len(current_label_values))
