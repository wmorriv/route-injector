#!/bin/bash
set -euo pipefail

CONFIG_PATH="${CONFIG_PATH:-/config/config.yaml}"
EXABGP_CONF="/etc/exabgp/exabgp.conf"
STARTUP_DELAY="${STARTUP_DELAY:-0}"

if [ ! -f "$CONFIG_PATH" ]; then
    echo "ERROR: Config file not found at $CONFIG_PATH" >&2
    exit 1
fi

if [ "$STARTUP_DELAY" -gt 0 ] 2>/dev/null; then
    echo "Waiting ${STARTUP_DELAY}s for interfaces to be ready..."
    sleep "$STARTUP_DELAY"
fi

echo "Generating ExaBGP configuration from $CONFIG_PATH..."
python3 -c "
from route_tool.config import load_config
from route_tool.exabgp_config import generate_exabgp_conf
from pathlib import Path
import os

overrides = {}
if os.environ.get('OVERRIDE_PEER_ADDRESS'):
    overrides['peer_address'] = os.environ['OVERRIDE_PEER_ADDRESS']
if os.environ.get('OVERRIDE_LOCAL_AS'):
    overrides['local_as'] = int(os.environ['OVERRIDE_LOCAL_AS'])
if os.environ.get('OVERRIDE_COUNT'):
    overrides['count'] = int(os.environ['OVERRIDE_COUNT'])
if os.environ.get('OVERRIDE_NO_FLAP'):
    overrides['no_flap'] = True
if os.environ.get('OVERRIDE_FLAP_INTERVAL'):
    overrides['flap_interval'] = int(os.environ['OVERRIDE_FLAP_INTERVAL'])
if os.environ.get('OVERRIDE_FLAP_PERCENTAGE'):
    overrides['flap_percentage'] = int(os.environ['OVERRIDE_FLAP_PERCENTAGE'])

cfg = load_config(Path('$CONFIG_PATH'), overrides if overrides else None)
conf = generate_exabgp_conf(cfg, '$CONFIG_PATH')
with open('$EXABGP_CONF', 'w') as f:
    f.write(conf)
print('ExaBGP config written to $EXABGP_CONF')
"

echo "Starting ExaBGP..."
exec env exabgp.daemon.daemonize=false \
         exabgp.log.all=true \
         exabgp.log.level=INFO \
         exabgp.api.pipename=/run/exabgp/exabgp \
    exabgp "$EXABGP_CONF"
