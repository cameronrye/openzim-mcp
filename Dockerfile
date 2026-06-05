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

# Create the non-root runtime user. No extra apt packages are needed —
# the image defaults to stdio transport (see ENTRYPOINT note below), so
# there is no HTTP server to health-probe and thus no need for curl.
RUN groupadd --gid 10001 appuser \
 && useradd --uid 10001 --gid appuser --shell /bin/bash --create-home appuser

WORKDIR /app

# Copy the virtualenv and source from builder as read-only (--chmod=555:
# r-x for owner/group/other, no write bits). uv pre-compiles .pyc during
# install, so the runtime never needs to write into /app; making the tree
# read-only at rest keeps the runtime user from mutating its own code.
COPY --from=builder --chown=appuser:appuser --chmod=555 /app/.venv /app/.venv
COPY --from=builder --chown=appuser:appuser --chmod=555 /app/openzim_mcp /app/openzim_mcp

ENV PATH="/app/.venv/bin:$PATH"

# Default mount point for ZIM files
VOLUME ["/data"]

# Document the HTTP port for the opt-in deployment path below. EXPOSE is
# metadata only; it publishes nothing unless `docker run -p` maps it.
EXPOSE 8000

# Drop privileges
USER appuser

# Default to stdio transport (inherited from the code defaults — we set no
# OPENZIM_MCP_TRANSPORT here), so `docker run -i --rm -v <zim>:/data <image>`
# runs as a local MCP server over stdin/stdout. That is how Claude Desktop
# and the Glama registry launch a containerized MCP server.
#
# To run the long-lived HTTP service instead, opt in at runtime:
#   docker run --rm -p 8000:8000 \
#     -e OPENZIM_MCP_TRANSPORT=http -e OPENZIM_MCP_HOST=0.0.0.0 \
#     -e OPENZIM_MCP_AUTH_TOKEN=$(openssl rand -hex 32) \
#     -v <zim>:/data <image>
# (binding a non-loopback host without a token is refused by design.)
ENTRYPOINT ["python", "-m", "openzim_mcp", "/data"]
