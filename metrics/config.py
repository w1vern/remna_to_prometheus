from __future__ import annotations

import os
from dataclasses import dataclass


@dataclass(frozen=True)
class Config:
    base_url: str
    api_token: str
    interval_seconds: int
    prometheus_port: int
    prometheus_bind: str
    prometheus_username: str
    prometheus_password: str
    page_size: int
    request_timeout: float

    @classmethod
    def from_env(cls) -> "Config":
        return cls(
            base_url=os.getenv("BASE_URL", "").strip(),
            api_token=os.getenv("API_TOKEN", ""),
            interval_seconds=int(os.getenv("INTERVAL_SECONDS", "10")),
            prometheus_port=int(os.getenv("PROMETHEUS_PORT", "9100")),
            prometheus_bind=os.getenv("PROMETHEUS_BIND", "0.0.0.0"),
            prometheus_username=os.getenv("PROMETHEUS_USERNAME", ""),
            prometheus_password=os.getenv("PROMETHEUS_PASSWORD", ""),
            page_size=int(os.getenv("PAGE_SIZE", "100")),
            request_timeout=float(os.getenv("REQUEST_TIMEOUT", "15")),
        )

    @property
    def api_base_url(self) -> str:
        base_url = self.base_url.rstrip("/")
        if not base_url.endswith("/api"):
            base_url = f"{base_url}/api"
        return base_url

    def validate(self) -> None:
        if not self.base_url:
            raise ValueError("Set BASE_URL before starting the exporter")
        if not self.api_token.strip():
            raise ValueError("Set API_TOKEN before starting the exporter")
        if not self.prometheus_username.strip():
            raise ValueError("Set PROMETHEUS_USERNAME before starting the exporter")
        if not self.prometheus_password:
            raise ValueError("Set PROMETHEUS_PASSWORD before starting the exporter")
        if self.interval_seconds <= 0:
            raise ValueError("INTERVAL_SECONDS must be greater than 0")
        if self.page_size <= 0:
            raise ValueError("PAGE_SIZE must be greater than 0")
