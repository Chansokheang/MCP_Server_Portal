# Bizplay MCP stack: one image, four entry points (see docker-compose.yml).
#   legacy-bizplay-api      mock of the existing Bizplay REST API
#   bizplay-mcp             curated MCP gateway
#   bizplay-mcp-registry    registry gateway (every published provider)
#   bizplay-portal          onboarding portal

FROM python:3.13-slim AS base
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    UV_LINK_MODE=copy \
    UV_COMPILE_BYTECODE=1 \
    FASTMCP_SHOW_SERVER_BANNER=false

COPY --from=ghcr.io/astral-sh/uv:0.11 /uv /uvx /bin/

WORKDIR /app

# Install dependencies first so this layer is cached while source changes.
COPY pyproject.toml uv.lock README.md ./
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-dev --no-install-project

# Then the project itself.
COPY src ./src
COPY openapi ./openapi
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-dev

# Shared state written at runtime (mounted as a volume in compose).
RUN mkdir -p /app/data /app/logs \
    && useradd --create-home --uid 10001 app \
    && chown -R app:app /app
USER app

ENV PATH="/app/.venv/bin:$PATH" \
    BIZPLAY_PORTAL_STATE=/app/data/portal_state.json \
    BIZPLAY_AUDIT_LOG=/app/logs/audit.jsonl

# Default command; compose overrides per service.
CMD ["bizplay-portal", "--host", "0.0.0.0", "--port", "18090"]
