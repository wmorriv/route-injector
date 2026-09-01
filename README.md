# Route-Tool

A BGP route injection and flapping tool built on [ExaBGP](https://github.com/Exa-Networks/exabgp). Generate thousands of BGP routes across multiple address families and optionally flap them on configurable patterns — useful for scale testing, RIB/FIB stress testing, and convergence benchmarking.

## Features

- **Multi-AFI support** — IPv4 unicast, IPv6 unicast, VPNv4 (MPLS L3VPN), VPNv6
- **Route flapping** — random, sequential, and burst patterns with configurable percentage, interval, and duration
- **Up to 1M routes per address family** — with batched announcement to avoid overwhelming peers
- **YAML configuration** with Pydantic validation
- **CLI with runtime overrides** — change peer address, route count, or flap behavior without editing config files
- **Containerlab integration** — included topology for lab testing with Arista cEOS (adaptable to any vendor)

## Requirements

- Python 3.10+
- Docker

## Quick Start

```bash
# Install locally (for the CLI)
pip install -e .

# Copy and edit the config
cp configs/example.yaml configs/config.yaml
# Edit configs/config.yaml — set peer_address, local_address, AS numbers, etc.

# Validate your config
route-tool validate -c configs/config.yaml

# Preview the routes that will be generated
route-tool preview -c configs/config.yaml

# Build and run
route-tool run -c configs/config.yaml
```

## Configuration

All settings live in a single YAML file. See [`configs/example.yaml`](configs/example.yaml) for a fully commented example.

### BGP Session

```yaml
bgp:
  local_as: 65001
  peer_address: 10.0.0.1       # Remote router IP
  peer_as: 65000
  router_id: 10.0.0.2
  local_address: 10.0.0.2      # Source IP for the BGP session
  hold_time: 90
```

### Routes

Each address family can be independently enabled and configured:

```yaml
routes:
  ipv4:
    enabled: true
    count: 1000
    base_prefix: "198.51.100.0/24"
    prefix_length: 32
    next_hop: "10.0.0.2"
    communities: ["65001:100"]
    med: 100
    # as_path: [65001, 65002]   # Optional AS path prepend

  ipv6:
    enabled: true
    count: 500
    base_prefix: "2001:db8::/32"
    prefix_length: 48
    next_hop: "2001:db8::2"

  vpnv4:
    enabled: true
    count: 1000
    base_prefix: "10.0.0.0/8"
    prefix_length: 24
    next_hop: "10.0.0.2"
    rd: "65001:1"
    route_targets: ["65001:100"]

  vpnv6:
    enabled: false
```

### Route Flapping

```yaml
flapping:
  enabled: true
  percentage: 10              # % of routes to flap each cycle
  interval_sec: 30            # Seconds between flap cycles
  pattern: random             # random | sequential | burst
  address_families: [ipv4, vpnv4]
  duration_sec: 0             # 0 = flap indefinitely
  burst_size: 50              # Routes per burst (burst pattern only)
  initial_delay_sec: 60       # Wait before flapping starts
```

**Patterns:**
- `random` — randomly selects a percentage of routes each cycle
- `sequential` — walks through routes in order, advancing the window each cycle
- `burst` — randomly selects a fixed number of routes (`burst_size`) each cycle

## CLI Reference

```
route-tool [OPTIONS] COMMAND [ARGS]...
```

| Command    | Description                                      |
|------------|--------------------------------------------------|
| `run`      | Build image and start the ExaBGP container       |
| `stop`     | Stop and remove the container                    |
| `status`   | Show container, BGP neighbor, and route status   |
| `validate` | Validate a config file without starting anything |
| `preview`  | Dry-run: show sample routes that would be generated |
| `logs`     | View container logs (follows by default)         |

### `run` Options

| Flag                  | Description                          |
|-----------------------|--------------------------------------|
| `-c, --config PATH`  | Config file (required)               |
| `--peer-address IP`  | Override BGP peer address            |
| `--local-as ASN`     | Override local AS number             |
| `--count N`          | Override route count for all enabled AFIs |
| `--flap-interval N`  | Override flap interval (seconds)     |
| `--flap-percentage N`| Override flap percentage             |
| `--no-flap`          | Disable route flapping               |
| `--no-build`         | Skip Docker image build              |
| `--no-detach`        | Run in foreground                    |

## Docker

### Standalone

```bash
docker build -t route-tool:latest .
docker run --network host \
  -v ./configs/config.yaml:/config/config.yaml:ro \
  route-tool:latest
```

### Docker Compose

```bash
# Edit configs/config.yaml, then:
docker compose up -d
docker logs -f route-tool
```

The compose file uses `network_mode: host` so the container shares the host's network stack — the `local_address` in your config must be a real IP on the host.

### Environment Variable Overrides

When running the container directly, you can override config values via environment variables:

| Variable                   | Description                    |
|----------------------------|--------------------------------|
| `OVERRIDE_PEER_ADDRESS`   | BGP peer address               |
| `OVERRIDE_LOCAL_AS`       | Local AS number                |
| `OVERRIDE_COUNT`          | Route count for all enabled AFIs |
| `OVERRIDE_NO_FLAP`        | Set to any value to disable flapping |
| `OVERRIDE_FLAP_INTERVAL`  | Flap interval in seconds       |
| `OVERRIDE_FLAP_PERCENTAGE`| Flap percentage                |
| `CONFIG_PATH`             | Config file path inside the container (default: `/config/config.yaml`) |
| `STARTUP_DELAY`           | Seconds to wait before starting ExaBGP (default: `0`) |

## Containerlab

An example topology is included for lab testing with Arista cEOS:

```bash
docker build -t route-tool:latest .
sudo clab deploy -t configs/clab-example.clab.yml
```

This creates a two-node topology with a direct link between route-tool and a cEOS DUT, pre-configured for BGP peering. Adapt the topology file for other vendors (SR Linux, vMX, vSROS, etc.) by replacing the `dut` node definition and startup config.

Check BGP status after deploy:

```bash
docker exec -it clab-bgp-scale-test-route-injector \
  env exabgp.api.pipename=/run/exabgp/exabgp exabgpcli show neighbor summary
```

Tear down:

```bash
sudo clab destroy -t configs/clab-example.clab.yml
```

## Peering with an External Router

1. Ensure IP reachability between the host running route-tool and the router
2. Configure `configs/config.yaml` with the correct IPs and AS numbers
3. Configure the router to accept the BGP peer — for example on IOS-XR:

   ```
   router bgp 65000
    neighbor 192.168.1.100
     remote-as 65001
     address-family ipv4 unicast
   ```

4. Run `route-tool run -c configs/config.yaml`
5. Verify with `route-tool status`

## Development

```bash
# Install with dev dependencies
pip install -e ".[dev]"

# Run tests
pytest

# Run tests with coverage
pytest --cov=route_tool
```

## Project Structure

```
route_tool/
  cli.py             # Click CLI — run, stop, status, validate, preview, logs
  config.py          # Pydantic models and YAML loading
  controller.py      # ExaBGP process controller (runs inside the container)
  exabgp_config.py   # Generates exabgp.conf from YAML config
  flapper.py         # Route flapping engine
  generator.py       # Prefix generation for all address families
configs/
  example.yaml       # Annotated example config
  clab-example.clab.yml  # Containerlab topology
  clab-config.yaml   # Config tuned for the clab topology
scripts/
  entrypoint.sh      # Container entrypoint
```
