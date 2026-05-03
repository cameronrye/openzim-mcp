# syntax=docker/dockerfile:1.6

# ---- builder stage ----
FROM python:3.13-slim AS builder

# Install uv (fast Python package manager). Pin to a specific tag so the
# image is reproducible — using :latest changes the binary out from under us
# every time the upstream image is rebuilt.
COPY --from=ghcr.io/astral-sh/uv:0.11 /uv /usr/local/bin/uv

WORKDIR /app

# Copy dep files and install (cached separately from source)
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project

# Copy source and install the project itself
COPY openzim_mcp ./openzim_mcp
COPY README.md ./
RUN uv sync --frozen --no-dev

# ---- final stage ----
FROM python:3.13-slim

# Create non-root user
RUN groupadd --gid 10001 appuser \
 && useradd --uid 10001 --gid appuser --shell /bin/bash --create-home appuser

# Install curl for HEALTHCHECK
RUN apt-get update \
 && apt-get install -y --no-install-recommends curl \
 && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Copy the virtualenv from builder. --chmod=755 (non-writable for the
# owner's group/others, no group/world write) avoids shipping app code
# the runtime user can mutate at rest.
COPY --from=builder --chown=appuser:appuser --chmod=755 /app/.venv /app/.venv
COPY --from=builder --chown=appuser:appuser --chmod=755 /app/openzim_mcp /app/openzim_mcp

ENV PATH="/app/.venv/bin:$PATH"

# Default mount point for ZIM files
VOLUME ["/data"]

# HTTP transport defaults — exposed bind requires OPENZIM_MCP_AUTH_TOKEN at
# runtime; the safe-default startup check refuses to bind 0.0.0.0 without it.
ENV OPENZIM_MCP_TRANSPORT=http \
    OPENZIM_MCP_HOST=0.0.0.0 \
    OPENZIM_MCP_PORT=8000

EXPOSE 8000

# Drop privileges
USER appuser

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
  CMD curl -fsS http://localhost:8000/readyz || exit 1

ENTRYPOINT ["python", "-m", "openzim_mcp", "/data"]
