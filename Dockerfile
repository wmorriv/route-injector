FROM python:3.12-slim

RUN apt-get update && apt-get install -y --no-install-recommends iproute2 iputils-ping && \
    rm -rf /var/lib/apt/lists/*

RUN pip install --no-cache-dir exabgp>=4.2

WORKDIR /app

COPY pyproject.toml .
COPY route_tool/ route_tool/

RUN pip install --no-cache-dir .

COPY scripts/entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh

RUN mkdir -p /etc/exabgp /config /run/exabgp && \
    mkfifo /run/exabgp/exabgp.in /run/exabgp/exabgp.out && \
    chmod 600 /run/exabgp/exabgp.in /run/exabgp/exabgp.out

ENTRYPOINT ["/entrypoint.sh"]
