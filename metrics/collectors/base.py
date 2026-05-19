from __future__ import annotations

from typing import Any, Protocol

from metrics.api import RemnawaveClient


class Collector(Protocol):
    name: str

    def collect(self, client: RemnawaveClient) -> Any:
        raise NotImplementedError

    def update_metrics(self, payload: Any) -> None:
        raise NotImplementedError
