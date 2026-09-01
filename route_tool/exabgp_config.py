"""Generate ExaBGP configuration from RouteToolConfig."""

from __future__ import annotations

from route_tool.config import RouteToolConfig


def generate_exabgp_conf(cfg: RouteToolConfig, config_path: str = "/config/config.yaml") -> str:
    """Generate exabgp.conf content from the tool's YAML config."""
    families = _build_family_block(cfg)
    return f"""\
process route-controller {{
    run /usr/local/bin/python3 /app/route_tool/controller.py {config_path};
    encoder text;
}}

neighbor {cfg.bgp.peer_address} {{
    router-id {cfg.bgp.router_id};
    local-address {cfg.bgp.local_address};
    local-as {cfg.bgp.local_as};
    peer-as {cfg.bgp.peer_as};
    hold-time {cfg.bgp.hold_time};

    family {{
{families}
    }}

    api {{
        processes [route-controller];
    }}
}}
"""


def _build_family_block(cfg: RouteToolConfig) -> str:
    lines = []
    if cfg.routes.ipv4.enabled:
        lines.append("        ipv4 unicast;")
    if cfg.routes.ipv6.enabled:
        lines.append("        ipv6 unicast;")
    if cfg.routes.vpnv4.enabled:
        lines.append("        ipv4 mpls-vpn;")
    if cfg.routes.vpnv6.enabled:
        lines.append("        ipv6 mpls-vpn;")
    if not lines:
        lines.append("        ipv4 unicast;")
    return "\n".join(lines)
