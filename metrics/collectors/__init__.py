from __future__ import annotations

from .servers import ServerStatsCollector
from .users import UserCollector


DEFAULT_COLLECTORS = (
    UserCollector(),
    ServerStatsCollector(),
)
