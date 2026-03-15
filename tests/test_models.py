"""Tests for data models."""

import pytest

from arris.models.port_rule import PortRule
from arris.models.dhcp_lease import DHCPLease


class TestPortRule:
    def test_valid_rule(self):
        rule = PortRule(name="http", protocol="TCP", wan_port=80, lan_port=80, lan_ip="192.168.0.1")
        assert rule.protocol_value == "0"
        assert not rule.is_range

    def test_udp_protocol_value(self):
        rule = PortRule(name="stun", protocol="UDP", wan_port=3478, lan_port=3478, lan_ip="192.168.0.1")
        assert rule.protocol_value == "1"

    def test_tcp_udp_protocol_value(self):
        rule = PortRule(name="both", protocol="TCP/UDP", wan_port=53, lan_port=53, lan_ip="192.168.0.1")
        assert rule.protocol_value == "2"

    def test_invalid_protocol(self):
        with pytest.raises(ValueError, match="Invalid protocol"):
            PortRule(name="bad", protocol="SCTP", wan_port=80, lan_port=80, lan_ip="192.168.0.1")

    def test_invalid_port(self):
        with pytest.raises(ValueError, match="wan_port out of range"):
            PortRule(name="bad", protocol="TCP", wan_port=0, lan_port=80, lan_ip="192.168.0.1")

    def test_invalid_ip(self):
        with pytest.raises(ValueError, match="Invalid IP"):
            PortRule(name="bad", protocol="TCP", wan_port=80, lan_port=80, lan_ip="not-an-ip")

    def test_empty_name(self):
        with pytest.raises(ValueError, match="name must not be empty"):
            PortRule(name="", protocol="TCP", wan_port=80, lan_port=80, lan_ip="192.168.0.1")

    def test_range(self):
        rule = PortRule(name="range", protocol="TCP", wan_port=8000, wan_port_end=8010,
                       lan_port=8000, lan_port_end=8010, lan_ip="192.168.0.1")
        assert rule.is_range
        assert rule.effective_wan_end == 8010

    def test_matches(self):
        a = PortRule(name="http", protocol="TCP", wan_port=80, lan_port=80, lan_ip="192.168.0.1")
        b = PortRule(name="web", protocol="TCP", wan_port=80, lan_port=80, lan_ip="192.168.0.1")
        assert a.matches(b)

    def test_no_match_different_port(self):
        a = PortRule(name="http", protocol="TCP", wan_port=80, lan_port=80, lan_ip="192.168.0.1")
        b = PortRule(name="http", protocol="TCP", wan_port=8080, lan_port=8080, lan_ip="192.168.0.1")
        assert not a.matches(b)


class TestDHCPLease:
    def test_valid_lease(self):
        lease = DHCPLease(name="test", mac="AA:BB:CC:DD:EE:FF", ip="192.168.0.100")
        assert lease.mac == "AA:BB:CC:DD:EE:FF"
        assert lease.ip_last_octet == "100"
        assert lease.mac_parts == ["AA", "BB", "CC", "DD", "EE", "FF"]

    def test_mac_normalization(self):
        lease = DHCPLease(name="test", mac="aa:bb:cc:dd:ee:ff", ip="192.168.0.1")
        assert lease.mac == "AA:BB:CC:DD:EE:FF"

    def test_mac_with_dashes(self):
        lease = DHCPLease(name="test", mac="AA-BB-CC-DD-EE-FF", ip="192.168.0.1")
        assert lease.mac == "AA:BB:CC:DD:EE:FF"

    def test_invalid_mac(self):
        with pytest.raises(ValueError, match="Invalid MAC"):
            DHCPLease(name="test", mac="not-a-mac", ip="192.168.0.1")

    def test_invalid_ip(self):
        with pytest.raises(ValueError, match="IP octet out of range"):
            DHCPLease(name="test", mac="AA:BB:CC:DD:EE:FF", ip="999.999.999.999")

    def test_matches_mac(self):
        lease = DHCPLease(name="test", mac="AA:BB:CC:DD:EE:FF", ip="192.168.0.1")
        assert lease.matches_mac("aa:bb:cc:dd:ee:ff")
        assert lease.matches_mac("AA:BB:CC:DD:EE:FF")
        assert not lease.matches_mac("11:22:33:44:55:66")
