"""Static DHCP lease model."""

from __future__ import annotations

import re
from dataclasses import dataclass


_MAC_RE = re.compile(r"^([0-9A-Fa-f]{2}:){5}[0-9A-Fa-f]{2}$")
_IP_RE = re.compile(r"^(\d{1,3}\.){3}\d{1,3}$")


@dataclass(frozen=True)
class DHCPLease:
    """A static DHCP reservation."""

    name: str
    mac: str
    ip: str

    def __post_init__(self):
        # Normalize MAC to uppercase
        object.__setattr__(self, "mac", self.mac.upper().replace("-", ":"))
        if not _MAC_RE.match(self.mac):
            raise ValueError(f"Invalid MAC: {self.mac}")
        if not _IP_RE.match(self.ip):
            raise ValueError(f"Invalid IP: {self.ip}")
        octets = [int(o) for o in self.ip.split(".")]
        if any(o < 0 or o > 255 for o in octets):
            raise ValueError(f"IP octet out of range: {self.ip}")

    @property
    def ip_last_octet(self) -> str:
        return self.ip.split(".")[-1]

    @property
    def mac_parts(self) -> list[str]:
        return self.mac.split(":")

    def matches_mac(self, other_mac: str) -> bool:
        return self.mac == other_mac.upper().replace("-", ":")
