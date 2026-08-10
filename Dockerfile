# No `# syntax=` directive on purpose. This file uses no BuildKit-only
# features, so pinning a frontend buys nothing — it only makes every
# BuildKit-based builder resolve and pull docker/dockerfile:1.6 before the
# first step runs. Registry builders that mirror or firewall Docker Hub fail
# there, before any of our layers are even attempted. Keep this file
# classic-builder clean (verify with `DOCKER_BUILDKIT=0 docker build .`) and
# do not re-add the directive without adding a feature that needs it.

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

# Strip write bits here rather than via `COPY --chmod` in the final stage.
# --chmod is a BuildKit-only flag, and registry builders that use the classic
# builder (or Kaniko) fail the build outright on it. Doing it in the builder
# means the plain COPY below carries these modes through, which every builder
# supports. `a-w` also beats a flat 555: it clears write without granting
# execute to files that never had it.
RUN chmod -R a-w /app/.venv /app/openzim_mcp

# ---- final stage ----
FROM python:3.13-slim

# Create the non-root runtime user. No extra apt packages are needed —
# the image defaults to stdio transport (see ENTRYPOINT note below), so
# there is no HTTP server to health-probe and thus no need for curl.
RUN groupadd --gid 10001 appuser \
 && useradd --uid 10001 --gid appuser --shell /bin/bash --create-home appuser

WORKDIR /app

# Copy the virtualenv and source from builder. The write bits were already
# stripped in the builder stage and COPY preserves source modes, so the tree
# lands read-only. uv pre-compiles .pyc during install, so the runtime never
# needs to write into /app; read-only at rest keeps the runtime user from
# mutating its own code.
COPY --from=builder --chown=appuser:appuser /app/.venv /app/.venv
COPY --from=builder --chown=appuser:appuser /app/openzim_mcp /app/openzim_mcp

# COPY re-creates the destination directory itself at the default 0755 owned
# by appuser, so the builder-stage chmod covers the contents but not these two
# inodes — without this the runtime user could still add new files alongside
# the code. Non-recursive on purpose: two inodes, so the layer stays tiny
# instead of duplicating the whole virtualenv.
RUN chmod 555 /app/.venv /app/openzim_mcp

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
