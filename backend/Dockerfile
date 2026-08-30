# syntax=docker/dockerfile:1

# The frontend is built first so the production API image can serve one bundle.
FROM oven/bun:1.3.14 AS frontend-build

WORKDIR /app

COPY package.json bun.lock ./
COPY frontend/package.json frontend/package.json

RUN bun install --frozen-lockfile

COPY frontend frontend

# Vite inlines these at build time, so they must be present now.
ARG VITE_SUPABASE_URL
ARG VITE_SUPABASE_PUBLISHABLE_KEY

RUN cd frontend && bun run build


FROM python:3.14-slim AS backend-base

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    PATH="/app/.venv/bin:$PATH"

WORKDIR /app

RUN --mount=from=ghcr.io/astral-sh/uv:0.11.6,source=/uv,target=/bin/uv \
    --mount=type=cache,target=/root/.cache/uv \
    --mount=type=bind,source=uv.lock,target=uv.lock \
    --mount=type=bind,source=pyproject.toml,target=pyproject.toml \
    --mount=type=bind,source=backend/pyproject.toml,target=backend/pyproject.toml \
    uv sync --locked --no-dev --no-install-workspace --package app

COPY backend/pyproject.toml backend/alembic.ini backend/
COPY backend/app backend/app

RUN --mount=from=ghcr.io/astral-sh/uv:0.11.6,source=/uv,target=/bin/uv \
    --mount=type=cache,target=/root/.cache/uv \
    --mount=type=bind,source=uv.lock,target=uv.lock \
    --mount=type=bind,source=pyproject.toml,target=pyproject.toml \
    uv sync --locked --no-dev --package app


FROM backend-base AS development

RUN --mount=from=ghcr.io/astral-sh/uv:0.11.6,source=/uv,target=/bin/uv \
    --mount=type=cache,target=/root/.cache/uv \
    --mount=type=bind,source=uv.lock,target=uv.lock \
    --mount=type=bind,source=pyproject.toml,target=pyproject.toml \
    uv sync --locked --package app

COPY backend/tests backend/tests

WORKDIR /app/backend

CMD ["fastapi", "dev", "--host", "0.0.0.0", "--port", "8000"]


FROM backend-base AS production

COPY --from=frontend-build /app/backend/app/frontend backend/app/frontend

# The application never needs to write to its own image.
RUN groupadd --gid 10001 appuser \
    && useradd --no-log-init --create-home --uid 10001 --gid 10001 appuser

USER appuser

WORKDIR /app/backend

EXPOSE 8000

CMD ["/bin/sh", "-c", "exec fastapi run --host 0.0.0.0 --port ${PORT:-8000}"]
