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


SERVER_LABELS = ("server_uuid", "server_name")
SERVER_LOAD_LABELS = (*SERVER_LABELS, "period")
SERVER_INTERFACE_LABELS = (*SERVER_LABELS, "interface")
LOAD_AVERAGE_PERIODS = ("1m", "5m", "15m")

REMNAWAVE_SERVERS_TOTAL = Gauge(
    "remnawave_servers_total",
    "Number of servers returned by the last successful Remnawave scrape.",
)
SERVER_MEMORY_FREE_BYTES = Gauge(
    "remnawave_server_memory_free_bytes",
    "Free memory reported by the Remnawave server stats section, in bytes.",
    SERVER_LABELS,
)
SERVER_MEMORY_USED_BYTES = Gauge(
    "remnawave_server_memory_used_bytes",
    "Used memory reported by the Remnawave server stats section, in bytes.",
    SERVER_LABELS,
)
SERVER_UPTIME_SECONDS = Gauge(
    "remnawave_server_uptime_seconds",
    "Server uptime reported by the Remnawave server stats section, in seconds.",
    SERVER_LABELS,
)
SERVER_LOAD_AVERAGE = Gauge(
    "remnawave_server_load_average",
    "Server load average reported by the Remnawave server stats section.",
    SERVER_LOAD_LABELS,
)
SERVER_NETWORK_RECEIVE_BYTES_PER_SECOND = Gauge(
    "remnawave_server_network_receive_bytes_per_second",
    "Network receive rate reported by the Remnawave server stats section.",
    SERVER_INTERFACE_LABELS,
)
SERVER_NETWORK_TRANSMIT_BYTES_PER_SECOND = Gauge(
    "remnawave_server_network_transmit_bytes_per_second",
    "Network transmit rate reported by the Remnawave server stats section.",
    SERVER_INTERFACE_LABELS,
)
SERVER_NETWORK_RECEIVE_BYTES = Counter(
    "remnawave_server_network_receive_bytes",
    "Total network bytes received by the server interface.",
    SERVER_INTERFACE_LABELS,
)
SERVER_NETWORK_TRANSMIT_BYTES = Counter(
    "remnawave_server_network_transmit_bytes",
    "Total network bytes transmitted by the server interface.",
    SERVER_INTERFACE_LABELS,
)

_known_stats_label_values: set[tuple[str, str]] = set()
_known_load_label_values: set[tuple[str, str, str]] = set()
_known_interface_label_values: set[tuple[str, str, str]] = set()
_last_rx_total_bytes: dict[tuple[str, ...], float] = {}
_last_tx_total_bytes: dict[tuple[str, ...], float] = {}


class ServerStatsCollector:
    name = "servers"

    def collect(self, client: RemnawaveClient) -> list[dict[str, Any]]:
        return client.fetch_servers()

    def update_metrics(self, servers: list[dict[str, Any]]) -> None:
        update_server_metrics(servers)


def server_label_values(server: dict[str, Any]) -> tuple[str, str]:
    return (
        label_value(first_present(server, "uuid", "serverUuid", "nodeUuid")),
        label_value(first_present(server, "name", "serverName", "nodeName")),
    )


def server_stats(server: dict[str, Any]) -> dict[str, Any] | None:
    system = server.get("system")
    if isinstance(system, dict) and isinstance(system.get("stats"), dict):
        return system["stats"]

    stats = server.get("stats")
    if isinstance(stats, dict):
        return stats

    return None


def load_average_period(index: int) -> str:
    if index < len(LOAD_AVERAGE_PERIODS):
        return LOAD_AVERAGE_PERIODS[index]
    return f"slot_{index}"


def update_server_metrics(servers: list[dict[str, Any]]) -> None:
    global _known_stats_label_values
    global _known_load_label_values
    global _known_interface_label_values

    valid_servers_count = 0
    current_stats_label_values: set[tuple[str, str]] = set()
    current_load_label_values: set[tuple[str, str, str]] = set()
    current_interface_label_values: set[tuple[str, str, str]] = set()

    for server in servers:
        labels = server_label_values(server)
        if not labels[0]:
            logging.warning("Skipping server without uuid: %s", server)
            continue

        valid_servers_count += 1
        stats = server_stats(server)
        if stats is None:
            logging.warning("Skipping server without stats section: %s", labels)
            continue

        current_stats_label_values.add(labels)
        SERVER_MEMORY_FREE_BYTES.labels(*labels).set(
            to_float(first_present(stats, "memoryFree", "memory_free"))
        )
        SERVER_MEMORY_USED_BYTES.labels(*labels).set(
            to_float(first_present(stats, "memoryUsed", "memory_used"))
        )
        SERVER_UPTIME_SECONDS.labels(*labels).set(
            to_float(first_present(stats, "uptime"))
        )

        load_avg = first_present(stats, "loadAvg", "load_avg")
        if isinstance(load_avg, list):
            for index, value in enumerate(load_avg):
                load_labels = (*labels, load_average_period(index))
                current_load_label_values.add(load_labels)
                SERVER_LOAD_AVERAGE.labels(*load_labels).set(to_float(value))

        interface_stats = stats.get("interface")
        if isinstance(interface_stats, dict):
            interface_name = label_value(
                first_present(interface_stats, "interface", "name")
            )
            if not interface_name:
                logging.warning("Skipping server interface without name: %s", labels)
                continue

            interface_labels = (*labels, interface_name)
            current_interface_label_values.add(interface_labels)
            SERVER_NETWORK_RECEIVE_BYTES_PER_SECOND.labels(*interface_labels).set(
                to_float(
                    first_present(
                        interface_stats,
                        "rxBytesPerSec",
                        "rx_bytes_per_sec",
                    )
                )
            )
            SERVER_NETWORK_TRANSMIT_BYTES_PER_SECOND.labels(*interface_labels).set(
                to_float(
                    first_present(
                        interface_stats,
                        "txBytesPerSec",
                        "tx_bytes_per_sec",
                    )
                )
            )
            update_counter_from_total(
                SERVER_NETWORK_RECEIVE_BYTES,
                _last_rx_total_bytes,
                interface_labels,
                to_float(first_present(interface_stats, "rxTotal", "rx_total")),
                "server network receive total",
            )
            update_counter_from_total(
                SERVER_NETWORK_TRANSMIT_BYTES,
                _last_tx_total_bytes,
                interface_labels,
                to_float(first_present(interface_stats, "txTotal", "tx_total")),
                "server network transmit total",
            )

    for stale_labels in _known_stats_label_values - current_stats_label_values:
        remove_series(SERVER_MEMORY_FREE_BYTES, *stale_labels)
        remove_series(SERVER_MEMORY_USED_BYTES, *stale_labels)
        remove_series(SERVER_UPTIME_SECONDS, *stale_labels)

    for stale_labels in _known_load_label_values - current_load_label_values:
        remove_series(SERVER_LOAD_AVERAGE, *stale_labels)

    for stale_labels in _known_interface_label_values - current_interface_label_values:
        remove_series(SERVER_NETWORK_RECEIVE_BYTES_PER_SECOND, *stale_labels)
        remove_series(SERVER_NETWORK_TRANSMIT_BYTES_PER_SECOND, *stale_labels)
        remove_series(SERVER_NETWORK_RECEIVE_BYTES, *stale_labels)
        remove_series(SERVER_NETWORK_TRANSMIT_BYTES, *stale_labels)
        _last_rx_total_bytes.pop(stale_labels, None)
        _last_tx_total_bytes.pop(stale_labels, None)

    _known_stats_label_values = current_stats_label_values
    _known_load_label_values = current_load_label_values
    _known_interface_label_values = current_interface_label_values
    REMNAWAVE_SERVERS_TOTAL.set(valid_servers_count)
