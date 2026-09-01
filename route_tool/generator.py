"""Route prefix generation for IPv4, IPv6, VPNv4, and VPNv6."""

from __future__ import annotations

import ipaddress
import logging
import sys
from dataclasses import dataclass, field
from typing import Iterator

from route_tool.config import (
    IPv4RouteConfig,
    IPv6RouteConfig,
    RoutesConfig,
    VPNv4RouteConfig,
    VPNv6RouteConfig,
)

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class Route:
    prefix: str
    prefix_length: int
    next_hop: str
    afi: str
    communities: list[str] = field(default_factory=list)
    as_path: list[int] = field(default_factory=list)
    med: int | None = None
    rd: str | None = None
    route_targets: list[str] = field(default_factory=list)

    def to_announce(self) -> str:
        """Format as an ExaBGP announce command."""
        if self.afi in ("vpnv4", "vpnv6"):
            return self._vpn_announce()
        return self._unicast_announce()

    def to_withdraw(self) -> str:
        """Format as an ExaBGP withdraw command."""
        if self.afi in ("vpnv4", "vpnv6"):
            return self._vpn_withdraw()
        return self._unicast_withdraw()

    def _unicast_announce(self) -> str:
        parts = [f"announce route {self.prefix}/{self.prefix_length} next-hop {self.next_hop}"]
        if self.as_path:
            parts.append(f"as-path [{' '.join(str(a) for a in self.as_path)}]")
        if self.med is not None:
            parts.append(f"med {self.med}")
        if self.communities:
            parts.append(f"community [{' '.join(self.communities)}]")
        return " ".join(parts)

    def _unicast_withdraw(self) -> str:
        return f"withdraw route {self.prefix}/{self.prefix_length} next-hop {self.next_hop}"

    def _vpn_announce(self) -> str:
        parts = [
            f"announce route {self.prefix}/{self.prefix_length}",
            f"rd {self.rd}",
            f"next-hop {self.next_hop}",
        ]
        if self.as_path:
            parts.append(f"as-path [{' '.join(str(a) for a in self.as_path)}]")
        if self.med is not None:
            parts.append(f"med {self.med}")
        if self.communities:
            parts.append(f"community [{' '.join(self.communities)}]")
        ext_communities = [f"target:{rt}" for rt in self.route_targets]
        if ext_communities:
            parts.append(f"extended-community [{' '.join(ext_communities)}]")
        return " ".join(parts)

    def _vpn_withdraw(self) -> str:
        return (
            f"withdraw route {self.prefix}/{self.prefix_length} "
            f"rd {self.rd} next-hop {self.next_hop}"
        )


def _generate_prefixes_v4(
    base: str, prefix_length: int, count: int
) -> Iterator[ipaddress.IPv4Address]:
    """Generate sequential IPv4 host addresses from a base network."""
    network = ipaddress.IPv4Network(base, strict=False)
    step = 2 ** (32 - prefix_length)
    start_int = int(network.network_address)
    max_addr = 2**32

    for i in range(count):
        addr_int = start_int + (i * step)
        if addr_int >= max_addr:
            log.warning(
                "Wrapped around IPv4 address space at route %d/%d", i, count
            )
            addr_int = addr_int % max_addr
        yield ipaddress.IPv4Address(addr_int)


def _generate_prefixes_v6(
    base: str, prefix_length: int, count: int
) -> Iterator[ipaddress.IPv6Address]:
    """Generate sequential IPv6 addresses from a base network."""
    network = ipaddress.IPv6Network(base, strict=False)
    step = 2 ** (128 - prefix_length)
    start_int = int(network.network_address)
    max_addr = 2**128

    for i in range(count):
        addr_int = start_int + (i * step)
        if addr_int >= max_addr:
            log.warning(
                "Wrapped around IPv6 address space at route %d/%d", i, count
            )
            addr_int = addr_int % max_addr
        yield ipaddress.IPv6Address(addr_int)


def generate_ipv4_routes(cfg: IPv4RouteConfig) -> list[Route]:
    """Generate IPv4 unicast routes from config."""
    routes = []
    for addr in _generate_prefixes_v4(cfg.base_prefix, cfg.prefix_length, cfg.count):
        routes.append(
            Route(
                prefix=str(addr),
                prefix_length=cfg.prefix_length,
                next_hop=cfg.next_hop,
                afi="ipv4",
                communities=list(cfg.communities),
                as_path=list(cfg.as_path),
                med=cfg.med,
            )
        )
    log.info("Generated %d IPv4 unicast routes", len(routes))
    return routes


def generate_ipv6_routes(cfg: IPv6RouteConfig) -> list[Route]:
    """Generate IPv6 unicast routes from config."""
    routes = []
    for addr in _generate_prefixes_v6(cfg.base_prefix, cfg.prefix_length, cfg.count):
        routes.append(
            Route(
                prefix=str(addr),
                prefix_length=cfg.prefix_length,
                next_hop=cfg.next_hop,
                afi="ipv6",
                communities=list(cfg.communities),
                as_path=list(cfg.as_path),
                med=cfg.med,
            )
        )
    log.info("Generated %d IPv6 unicast routes", len(routes))
    return routes


def generate_vpnv4_routes(cfg: VPNv4RouteConfig) -> list[Route]:
    """Generate VPNv4 routes from config."""
    routes = []
    for addr in _generate_prefixes_v4(cfg.base_prefix, cfg.prefix_length, cfg.count):
        routes.append(
            Route(
                prefix=str(addr),
                prefix_length=cfg.prefix_length,
                next_hop=cfg.next_hop,
                afi="vpnv4",
                communities=list(cfg.communities),
                as_path=list(cfg.as_path),
                med=cfg.med,
                rd=cfg.rd,
                route_targets=list(cfg.route_targets),
            )
        )
    log.info("Generated %d VPNv4 routes", len(routes))
    return routes


def generate_vpnv6_routes(cfg: VPNv6RouteConfig) -> list[Route]:
    """Generate VPNv6 routes from config."""
    routes = []
    for addr in _generate_prefixes_v6(cfg.base_prefix, cfg.prefix_length, cfg.count):
        routes.append(
            Route(
                prefix=str(addr),
                prefix_length=cfg.prefix_length,
                next_hop=cfg.next_hop,
                afi="vpnv6",
                communities=list(cfg.communities),
                as_path=list(cfg.as_path),
                med=cfg.med,
                rd=cfg.rd,
                route_targets=list(cfg.route_targets),
            )
        )
    log.info("Generated %d VPNv6 routes", len(routes))
    return routes


_GENERATORS = {
    "ipv4": lambda cfg: generate_ipv4_routes(cfg.ipv4),
    "ipv6": lambda cfg: generate_ipv6_routes(cfg.ipv6),
    "vpnv4": lambda cfg: generate_vpnv4_routes(cfg.vpnv4),
    "vpnv6": lambda cfg: generate_vpnv6_routes(cfg.vpnv6),
}


def generate_all_routes(routes_cfg: RoutesConfig) -> dict[str, list[Route]]:
    """Generate routes for all enabled address families."""
    result: dict[str, list[Route]] = {}
    for afi in ("ipv4", "ipv6", "vpnv4", "vpnv6"):
        afi_cfg = getattr(routes_cfg, afi)
        if afi_cfg.enabled:
            result[afi] = _GENERATORS[afi](routes_cfg)
    total = sum(len(r) for r in result.values())
    log.info("Generated %d total routes across %d address families", total, len(result))
    return result
