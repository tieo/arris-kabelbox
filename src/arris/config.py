"""Declarative YAML configuration loading and validation."""

from __future__ import annotations

from pathlib import Path

import yaml
from pydantic import BaseModel, field_validator

from .models.dhcp_lease import DHCPLease
from .models.port_rule import PortRule


class PortRuleConfig(BaseModel):
    name: str
    protocol: str = "TCP"
    wan_port: int
    lan_port: int | None = None
    lan_ip: str

    @field_validator("protocol")
    @classmethod
    def validate_protocol(cls, v: str) -> str:
        v = v.upper()
        if v not in ("TCP", "UDP", "TCP/UDP"):
            raise ValueError(f"Invalid protocol: {v}")
        return v

    def to_model(self) -> PortRule:
        return PortRule(
            name=self.name,
            protocol=self.protocol,
            wan_port=self.wan_port,
            lan_port=self.lan_port or self.wan_port,
            lan_ip=self.lan_ip,
        )


class DHCPLeaseConfig(BaseModel):
    name: str
    mac: str
    ip: str

    def to_model(self) -> DHCPLease:
        return DHCPLease(name=self.name, mac=self.mac, ip=self.ip)


class RouterConfig(BaseModel):
    host: str = "192.168.0.1"
    port_forwarding: list[PortRuleConfig] = []
    dhcp_reservations: list[DHCPLeaseConfig] = []

    @field_validator("dhcp_reservations")
    @classmethod
    def check_unique_macs(cls, v: list[DHCPLeaseConfig]) -> list[DHCPLeaseConfig]:
        macs = [lease.mac.upper() for lease in v]
        dupes = [m for m in macs if macs.count(m) > 1]
        if dupes:
            raise ValueError(f"Duplicate MAC addresses: {set(dupes)}")
        return v

    @field_validator("dhcp_reservations")
    @classmethod
    def check_unique_ips(cls, v: list[DHCPLeaseConfig]) -> list[DHCPLeaseConfig]:
        ips = [lease.ip for lease in v]
        dupes = [ip for ip in ips if ips.count(ip) > 1]
        if dupes:
            raise ValueError(f"Duplicate IP addresses: {set(dupes)}")
        return v

    @field_validator("port_forwarding")
    @classmethod
    def check_unique_ports(cls, v: list[PortRuleConfig]) -> list[PortRuleConfig]:
        ports = [(r.protocol.upper(), r.wan_port) for r in v]
        dupes = [p for p in ports if ports.count(p) > 1]
        if dupes:
            raise ValueError(f"Duplicate port mappings: {set(dupes)}")
        return v


def load_config(path: str | Path) -> RouterConfig:
    """Load and validate a YAML configuration file."""
    path = Path(path)
    with path.open() as f:
        raw = yaml.safe_load(f)
    if raw is None:
        return RouterConfig()
    return RouterConfig(**raw)
