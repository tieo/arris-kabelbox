"""Test fixtures."""

import pytest


@pytest.fixture
def sample_port_rules():
    from arris.models.port_rule import PortRule
    return [
        PortRule(name="Web-HTTP", protocol="TCP", wan_port=80, lan_port=80, lan_ip="192.168.1.100"),
        PortRule(name="Web-HTTPS", protocol="TCP", wan_port=443, lan_port=443, lan_ip="192.168.1.100"),
        PortRule(name="VPN-STUN", protocol="UDP", wan_port=3478, lan_port=3478, lan_ip="192.168.1.100"),
    ]


@pytest.fixture
def sample_dhcp_leases():
    from arris.models.dhcp_lease import DHCPLease
    return [
        DHCPLease(name="Desktop", mac="AA:BB:CC:DD:EE:01", ip="192.168.1.10"),
        DHCPLease(name="Laptop", mac="AA:BB:CC:DD:EE:02", ip="192.168.1.11"),
        DHCPLease(name="Server", mac="AA:BB:CC:DD:EE:03", ip="192.168.1.20"),
    ]
