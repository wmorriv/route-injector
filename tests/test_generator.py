"""Tests for route generation."""

import pytest

from route_tool.config import (
    IPv4RouteConfig,
    IPv6RouteConfig,
    RoutesConfig,
    VPNv4RouteConfig,
    VPNv6RouteConfig,
)
from route_tool.generator import (
    Route,
    generate_all_routes,
    generate_ipv4_routes,
    generate_ipv6_routes,
    generate_vpnv4_routes,
    generate_vpnv6_routes,
)


def test_ipv4_route_count():
    cfg = IPv4RouteConfig(enabled=True, count=10, base_prefix="198.51.100.0/24", prefix_length=32)
    routes = generate_ipv4_routes(cfg)
    assert len(routes) == 10


def test_ipv4_prefixes_sequential():
    cfg = IPv4RouteConfig(enabled=True, count=3, base_prefix="198.51.100.0/24", prefix_length=32)
    routes = generate_ipv4_routes(cfg)
    assert routes[0].prefix == "198.51.100.0"
    assert routes[1].prefix == "198.51.100.1"
    assert routes[2].prefix == "198.51.100.2"


def test_ipv4_prefix_length_24():
    cfg = IPv4RouteConfig(enabled=True, count=3, base_prefix="10.0.0.0/8", prefix_length=24)
    routes = generate_ipv4_routes(cfg)
    assert routes[0].prefix == "10.0.0.0"
    assert routes[0].prefix_length == 24
    assert routes[1].prefix == "10.0.1.0"
    assert routes[2].prefix == "10.0.2.0"


def test_ipv4_announce_format():
    cfg = IPv4RouteConfig(
        enabled=True, count=1,
        base_prefix="198.51.100.0/24", prefix_length=32,
        next_hop="10.0.0.2",
        communities=["65001:100"],
        med=100,
    )
    route = generate_ipv4_routes(cfg)[0]
    announce = route.to_announce()
    assert "announce route 198.51.100.0/32" in announce
    assert "next-hop 10.0.0.2" in announce
    assert "community [65001:100]" in announce
    assert "med 100" in announce


def test_ipv4_withdraw_format():
    cfg = IPv4RouteConfig(enabled=True, count=1, base_prefix="198.51.100.0/24", prefix_length=32)
    route = generate_ipv4_routes(cfg)[0]
    withdraw = route.to_withdraw()
    assert "withdraw route 198.51.100.0/32" in withdraw


def test_ipv6_route_count():
    cfg = IPv6RouteConfig(enabled=True, count=5, base_prefix="2001:db8::/32", prefix_length=48)
    routes = generate_ipv6_routes(cfg)
    assert len(routes) == 5


def test_ipv6_prefixes_sequential():
    cfg = IPv6RouteConfig(enabled=True, count=3, base_prefix="2001:db8::/32", prefix_length=48)
    routes = generate_ipv6_routes(cfg)
    assert routes[0].prefix == "2001:db8::"
    assert routes[1].prefix == "2001:db8:1::"
    assert routes[2].prefix == "2001:db8:2::"


def test_vpnv4_route_count():
    cfg = VPNv4RouteConfig(
        enabled=True, count=10,
        base_prefix="10.0.0.0/8", prefix_length=24,
        rd="65001:1", route_targets=["65001:100"],
    )
    routes = generate_vpnv4_routes(cfg)
    assert len(routes) == 10
    assert all(r.rd == "65001:1" for r in routes)
    assert all(r.afi == "vpnv4" for r in routes)


def test_vpnv4_announce_format():
    cfg = VPNv4RouteConfig(
        enabled=True, count=1,
        base_prefix="10.0.0.0/8", prefix_length=24,
        next_hop="10.0.0.2",
        rd="65001:1", route_targets=["65001:100"],
    )
    route = generate_vpnv4_routes(cfg)[0]
    announce = route.to_announce()
    assert "announce route 10.0.0.0/24" in announce
    assert "rd 65001:1" in announce
    assert "target:65001:100" in announce


def test_vpnv6_route_count():
    cfg = VPNv6RouteConfig(
        enabled=True, count=5,
        base_prefix="fd00::/16", prefix_length=48,
        rd="65001:2", route_targets=["65001:200"],
    )
    routes = generate_vpnv6_routes(cfg)
    assert len(routes) == 5
    assert all(r.rd == "65001:2" for r in routes)
    assert all(r.afi == "vpnv6" for r in routes)


def test_generate_all_routes_only_enabled():
    routes_cfg = RoutesConfig(
        ipv4=IPv4RouteConfig(enabled=True, count=10),
        ipv6=IPv6RouteConfig(enabled=False),
        vpnv4=VPNv4RouteConfig(enabled=True, count=5),
        vpnv6=VPNv6RouteConfig(enabled=False),
    )
    result = generate_all_routes(routes_cfg)
    assert "ipv4" in result
    assert "vpnv4" in result
    assert "ipv6" not in result
    assert "vpnv6" not in result
    assert len(result["ipv4"]) == 10
    assert len(result["vpnv4"]) == 5


def test_as_path_in_announce():
    cfg = IPv4RouteConfig(
        enabled=True, count=1,
        base_prefix="198.51.100.0/24", prefix_length=32,
        as_path=[65001, 65002],
    )
    route = generate_ipv4_routes(cfg)[0]
    assert "as-path [65001 65002]" in route.to_announce()


def test_large_count():
    cfg = IPv4RouteConfig(enabled=True, count=10000, base_prefix="10.0.0.0/8", prefix_length=24)
    routes = generate_ipv4_routes(cfg)
    assert len(routes) == 10000
    prefixes = {r.prefix for r in routes}
    assert len(prefixes) == 10000
