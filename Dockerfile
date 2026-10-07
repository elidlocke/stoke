# The production image: the built frontend, served by the FastAPI backend from one origin.
# Run it locally with `docker compose --profile app up --build`; Render builds it from render.yaml.

# --- Frontend --------------------------------------------------------------------------------------
FROM node:22-slim AS frontend
WORKDIR /app/frontend
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci
COPY frontend/ ./
# Vite bakes these into the bundle at build time. Render passes environment variables as build args;
# compose passes them from .env.
ARG VITE_AUTH0_DOMAIN
ARG VITE_AUTH0_CLIENT_ID
ARG VITE_AUTH0_AUDIENCE
RUN test -n "$VITE_AUTH0_DOMAIN" -a -n "$VITE_AUTH0_CLIENT_ID" -a -n "$VITE_AUTH0_AUDIENCE" \
    || (echo "Set VITE_AUTH0_DOMAIN, VITE_AUTH0_CLIENT_ID and VITE_AUTH0_AUDIENCE" && exit 1)
RUN npm run build

# --- Backend ---------------------------------------------------------------------------------------
FROM python:3.13-slim
COPY --from=ghcr.io/astral-sh/uv:0.9 /uv /bin/uv
ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy UV_PYTHON_DOWNLOADS=never
WORKDIR /app/backend
COPY backend/pyproject.toml backend/uv.lock backend/.python-version ./
RUN uv sync --frozen --no-dev --no-install-project
COPY backend/ ./
COPY --from=frontend /app/frontend/dist /app/static

RUN useradd --system --no-create-home stoke
USER stoke
ENV PATH="/app/backend/.venv/bin:$PATH" STATIC_DIR=/app/static PORT=8000
EXPOSE 8000
# One worker: the Stripe cache is in memory, per process. --proxy-headers trusts the host's TLS proxy.
CMD ["sh", "-c", "exec uvicorn app.main:app --host 0.0.0.0 --port $PORT --proxy-headers --forwarded-allow-ips='*'"]
