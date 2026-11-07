# syntax=docker/dockerfile:1.7
# One image for the API, the worker and migrations (backbone LLD §9.4). Build from the repo root:
#   docker build -f apps/api/Dockerfile --build-arg SIGNORA_COMMIT=$(git rev-parse --short HEAD) .

FROM python:3.12.15-slim-bookworm AS build
COPY --from=ghcr.io/astral-sh/uv:0.9.17 /uv /usr/local/bin/uv
ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PYTHON_DOWNLOADS=never \
    UV_PROJECT_ENVIRONMENT=/app/apps/api/.venv
WORKDIR /app/apps/api
# Dependencies first so they are cached independently of source changes.
COPY apps/api/pyproject.toml apps/api/uv.lock apps/api/.python-version ./
RUN uv sync --frozen --no-dev --no-install-project
COPY apps/api/src ./src
RUN uv sync --frozen --no-dev

FROM python:3.12.15-slim-bookworm AS runtime
ARG SIGNORA_COMMIT=dev
ENV PATH=/app/apps/api/.venv/bin:$PATH \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    SIGNORA_ROOT=/app \
    SIGNORA_COMMIT=${SIGNORA_COMMIT}
RUN groupadd --system --gid 10001 signora \
 && useradd --system --uid 10001 --gid signora --home-dir /app --shell /usr/sbin/nologin signora
WORKDIR /app
COPY --from=build /app/apps/api /app/apps/api
# Marker that identifies the repository root for configuration (LLD §6.2).
COPY .env.example /app/.env.example
RUN mkdir -p /app/data/blobs && chown -R signora:signora /app/data
USER signora
EXPOSE 8000
HEALTHCHECK --interval=15s --timeout=3s --start-period=20s --retries=3 \
  CMD ["python", "-c", "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8000/api/v1/health/live', timeout=2).status == 200 else 1)"]
CMD ["signora", "api", "--host", "0.0.0.0", "--port", "8000"]
