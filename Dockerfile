FROM ghcr.io/astral-sh/uv:0.11.28 AS uv

FROM python:3.14-slim

ARG DEBIAN_FRONTEND=noninteractive
ARG TERRAPANEL_VERSION=1.0.0

LABEL org.opencontainers.image.title="TerraPanel" \
    org.opencontainers.image.description="Web management panel for tModLoader dedicated servers" \
    org.opencontainers.image.version="${TERRAPANEL_VERSION}"

RUN dpkg --add-architecture i386 \
    && apt-get update \
    && apt-get install --no-install-recommends --yes \
        bash \
        ca-certificates \
        curl \
        libc6:i386 \
        libgcc-s1:i386 \
        libicu76 \
        libstdc++6:i386 \
        tar \
        tini \
        unzip \
    && rm -rf /var/lib/apt/lists/*

COPY --from=uv /uv /uvx /usr/local/bin/

WORKDIR /app
ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    TERRAPANEL_ENVIRONMENT=production \
    TERRAPANEL_HTTP__BIND_ADDRESS=0.0.0.0 \
    TERRAPANEL_STORAGE__ROOT_DIR=/data

COPY pyproject.toml uv.lock README.md .python-version ./
RUN uv sync --frozen --no-dev --no-install-project

COPY src ./src
RUN uv sync --frozen --no-dev \
    && mkdir -p /data/servers /data/backups

USER root
VOLUME ["/data"]
EXPOSE 8080 7777

HEALTHCHECK --interval=10s --timeout=3s --start-period=5s --retries=6 \
    CMD curl --fail --silent http://127.0.0.1:8080/api/v1/health || exit 1

ENTRYPOINT ["/usr/bin/tini", "--"]
CMD ["uv", "run", "--frozen", "--no-dev", "--no-sync", "terrapanel"]
