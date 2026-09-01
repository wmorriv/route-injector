"""Configuration models and YAML loading for route-tool."""

from __future__ import annotations

import ipaddress
from enum import Enum
from pathlib import Path
from typing import Optional

import yaml
from pydantic import BaseModel, Field, field_validator, model_validator


class FlapPattern(str, Enum):
    RANDOM = "random"
    SEQUENTIAL = "sequential"
    BURST = "burst"


class BgpConfig(BaseModel):
    local_as: int = Field(ge=1, le=4294967295)
    peer_address: str
    peer_as: int = Field(ge=1, le=4294967295)
    router_id: str
    local_address: str
    hold_time: int = Field(default=90, ge=3, le=65535)

    @field_validator("peer_address", "router_id", "local_address")
    @classmethod
    def validate_ip(cls, v: str) -> str:
        ipaddress.ip_address(v)
        return v


class IPv4RouteConfig(BaseModel):
    enabled: bool = False
    count: int = Field(default=100, ge=1, le=1_000_000)
    base_prefix: str = "198.51.100.0/24"
    prefix_length: int = Field(default=32, ge=8, le=32)
    next_hop: str = "10.0.0.2"
    communities: list[str] = Field(default_factory=list)
    med: Optional[int] = Field(default=None, ge=0)
    as_path: list[int] = Field(default_factory=list)

    @field_validator("base_prefix")
    @classmethod
    def validate_v4_prefix(cls, v: str) -> str:
        ipaddress.IPv4Network(v, strict=False)
        return v

    @field_validator("next_hop")
    @classmethod
    def validate_v4_next_hop(cls, v: str) -> str:
        ipaddress.IPv4Address(v)
        return v


class IPv6RouteConfig(BaseModel):
    enabled: bool = False
    count: int = Field(default=100, ge=1, le=1_000_000)
    base_prefix: str = "2001:db8::/32"
    prefix_length: int = Field(default=48, ge=16, le=128)
    next_hop: str = "2001:db8::2"
    communities: list[str] = Field(default_factory=list)
    med: Optional[int] = Field(default=None, ge=0)
    as_path: list[int] = Field(default_factory=list)

    @field_validator("base_prefix")
    @classmethod
    def validate_v6_prefix(cls, v: str) -> str:
        ipaddress.IPv6Network(v, strict=False)
        return v

    @field_validator("next_hop")
    @classmethod
    def validate_v6_next_hop(cls, v: str) -> str:
        ipaddress.IPv6Address(v)
        return v


class VPNv4RouteConfig(BaseModel):
    enabled: bool = False
    count: int = Field(default=100, ge=1, le=1_000_000)
    base_prefix: str = "10.0.0.0/8"
    prefix_length: int = Field(default=24, ge=8, le=32)
    next_hop: str = "10.0.0.2"
    rd: str = "65001:1"
    route_targets: list[str] = Field(default_factory=lambda: ["65001:100"])
    communities: list[str] = Field(default_factory=list)
    med: Optional[int] = Field(default=None, ge=0)
    as_path: list[int] = Field(default_factory=list)

    @field_validator("base_prefix")
    @classmethod
    def validate_v4_prefix(cls, v: str) -> str:
        ipaddress.IPv4Network(v, strict=False)
        return v

    @field_validator("next_hop")
    @classmethod
    def validate_v4_next_hop(cls, v: str) -> str:
        ipaddress.IPv4Address(v)
        return v

    @field_validator("rd")
    @classmethod
    def validate_rd(cls, v: str) -> str:
        parts = v.split(":")
        if len(parts) != 2:
            raise ValueError("RD must be in format 'admin:assigned' (e.g. '65001:1')")
        return v


class VPNv6RouteConfig(BaseModel):
    enabled: bool = False
    count: int = Field(default=100, ge=1, le=1_000_000)
    base_prefix: str = "fd00::/16"
    prefix_length: int = Field(default=48, ge=16, le=128)
    next_hop: str = "::ffff:10.0.0.2"
    rd: str = "65001:2"
    route_targets: list[str] = Field(default_factory=lambda: ["65001:200"])
    communities: list[str] = Field(default_factory=list)
    med: Optional[int] = Field(default=None, ge=0)
    as_path: list[int] = Field(default_factory=list)

    @field_validator("base_prefix")
    @classmethod
    def validate_v6_prefix(cls, v: str) -> str:
        ipaddress.IPv6Network(v, strict=False)
        return v

    @field_validator("next_hop")
    @classmethod
    def validate_v6_next_hop(cls, v: str) -> str:
        ipaddress.IPv6Address(v)
        return v

    @field_validator("rd")
    @classmethod
    def validate_rd(cls, v: str) -> str:
        parts = v.split(":")
        if len(parts) != 2:
            raise ValueError("RD must be in format 'admin:assigned' (e.g. '65001:2')")
        return v


class RoutesConfig(BaseModel):
    ipv4: IPv4RouteConfig = Field(default_factory=IPv4RouteConfig)
    ipv6: IPv6RouteConfig = Field(default_factory=IPv6RouteConfig)
    vpnv4: VPNv4RouteConfig = Field(default_factory=VPNv4RouteConfig)
    vpnv6: VPNv6RouteConfig = Field(default_factory=VPNv6RouteConfig)


class FlappingConfig(BaseModel):
    enabled: bool = False
    percentage: int = Field(default=10, ge=1, le=100)
    interval_sec: int = Field(default=30, ge=1)
    pattern: FlapPattern = FlapPattern.RANDOM
    address_families: list[str] = Field(default_factory=lambda: ["ipv4"])
    duration_sec: int = Field(default=0, ge=0)
    burst_size: int = Field(default=50, ge=1)
    initial_delay_sec: int = Field(default=60, ge=0)

    @field_validator("address_families")
    @classmethod
    def validate_afis(cls, v: list[str]) -> list[str]:
        valid = {"ipv4", "ipv6", "vpnv4", "vpnv6"}
        for afi in v:
            if afi not in valid:
                raise ValueError(f"Invalid address family '{afi}'. Must be one of: {valid}")
        return v


class RouteToolConfig(BaseModel):
    bgp: BgpConfig
    routes: RoutesConfig = Field(default_factory=RoutesConfig)
    flapping: FlappingConfig = Field(default_factory=FlappingConfig)

    @model_validator(mode="after")
    def validate_flap_afis_enabled(self) -> RouteToolConfig:
        if not self.flapping.enabled:
            return self
        for afi in self.flapping.address_families:
            afi_config = getattr(self.routes, afi)
            if not afi_config.enabled:
                raise ValueError(
                    f"Flapping configured for '{afi}' but it is not enabled in routes"
                )
        return self


def load_config(path: Path, overrides: dict | None = None) -> RouteToolConfig:
    """Load config from YAML file, applying optional CLI overrides."""
    with open(path) as f:
        data = yaml.safe_load(f)

    if overrides:
        _apply_overrides(data, overrides)

    return RouteToolConfig(**data)


def _apply_overrides(data: dict, overrides: dict) -> None:
    """Merge CLI overrides into the raw YAML data."""
    if "peer_address" in overrides:
        data.setdefault("bgp", {})["peer_address"] = overrides["peer_address"]

    if "local_as" in overrides:
        data.setdefault("bgp", {})["local_as"] = overrides["local_as"]

    if "count" in overrides:
        for afi in ("ipv4", "ipv6", "vpnv4", "vpnv6"):
            afi_data = data.get("routes", {}).get(afi, {})
            if afi_data.get("enabled", False):
                afi_data["count"] = overrides["count"]

    if "no_flap" in overrides and overrides["no_flap"]:
        data.setdefault("flapping", {})["enabled"] = False

    if "flap_interval" in overrides:
        data.setdefault("flapping", {})["interval_sec"] = overrides["flap_interval"]

    if "flap_percentage" in overrides:
        data.setdefault("flapping", {})["percentage"] = overrides["flap_percentage"]
