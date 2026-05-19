from __future__ import annotations

import logging
from typing import Any


def label_value(value: Any) -> str:
    if value is None:
        return ""
    return str(value)


def to_float(value: Any) -> float:
    if value is None or value == "":
        return 0.0
    return float(value)


def first_present(mapping: dict[str, Any], *keys: str) -> Any:
    for key in keys:
        if key in mapping:
            return mapping[key]
    return None


def remove_series(metric: Any, *labels: str) -> None:
    try:
        metric.remove(*labels)
    except KeyError:
        pass


def update_counter_from_total(
    metric: Any,
    last_values: dict[tuple[str, ...], float],
    labels: tuple[str, ...],
    current_total: float,
    metric_description: str,
) -> None:
    if current_total < 0:
        logging.warning(
            "Skipping negative %s for labels %s",
            metric_description,
            labels,
        )
        return

    previous_total = last_values.get(labels)
    counter = metric.labels(*labels)

    if previous_total is None:
        if current_total > 0:
            counter.inc(current_total)
    elif current_total > previous_total:
        counter.inc(current_total - previous_total)
    elif current_total < previous_total:
        logging.warning(
            "%s decreased for labels %s: %s -> %s; resetting counter series",
            metric_description,
            labels,
            previous_total,
            current_total,
        )
        remove_series(metric, *labels)
        if current_total > 0:
            metric.labels(*labels).inc(current_total)

    last_values[labels] = current_total
