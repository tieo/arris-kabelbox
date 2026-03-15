"""Port forwarding rule model."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Literal


@dataclass(frozen=True)
class PortRule:
    """A single port forwarding rule."""

    name: str
    protocol: Literal["TCP", "UDP", "TCP/UDP"]
    wan_port: int
    lan_port: int
    lan_ip: str
    wan_port_end: int | None = None
    lan_port_end: int | None = None
    enabled: bool = True

    def __post_init__(self):
        if not self.name:
            raise ValueError("name must not be empty")
        if self.protocol not in ("TCP", "UDP", "TCP/UDP"):
            raise ValueError(f"Invalid protocol: {self.protocol}")
        if not 1 <= self.wan_port <= 65535:
            raise ValueError(f"wan_port out of range: {self.wan_port}")
        if not 1 <= self.lan_port <= 65535:
            raise ValueError(f"lan_port out of range: {self.lan_port}")
        if not re.match(r"^\d+\.\d+\.\d+\.\d+$", self.lan_ip):
            raise ValueError(f"Invalid IP: {self.lan_ip}")

    @property
    def is_range(self) -> bool:
        return (
            self.wan_port_end is not None
            and self.wan_port_end != self.wan_port
        )

    @property
    def effective_wan_end(self) -> int:
        return self.wan_port_end if self.wan_port_end is not None else self.wan_port

    @property
    def effective_lan_end(self) -> int:
        return self.lan_port_end if self.lan_port_end is not None else self.lan_port

    @property
    def protocol_value(self) -> str:
        """Router form value for protocol select."""
        return {"TCP": "0", "UDP": "1", "TCP/UDP": "2"}[self.protocol]

    def matches(self, other: PortRule) -> bool:
        """Check if two rules represent the same forwarding (ignoring name)."""
        return (
            self.protocol == other.protocol
            and self.wan_port == other.wan_port
            and self.lan_port == other.lan_port
            and self.lan_ip == other.lan_ip
        )
