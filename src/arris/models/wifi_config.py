"""WiFi configuration model."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal


@dataclass(frozen=True)
class WifiConfig:
    """WiFi network configuration (read-only snapshot)."""

    ssid: str
    band: Literal["2.4GHz", "5GHz"]
    channel: int | str
    security: str
    enabled: bool = True
