# The public, read-only synthetic demo as one container (T046, D064): the FastAPI API serves the
# built React app on the same origin. Built by Render from render.yaml; also builds locally:
#   docker build -f deploy/render/Dockerfile -t wattwise-public:local .
# The demo model is trained here, at build time, on the committed synthetic sample only.

FROM node:24-bookworm@sha256:6449e19d8184d84062525b6a7524def03146c2cb04a7f08b076680d0e8e4240a AS frontend
WORKDIR /app/frontend
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci --no-audit --no-fund
COPY frontend/ ./
ENV VITE_API_BASE_URL=""
RUN npm run build

FROM python:3.13-slim-bookworm@sha256:281d39ff02e3b389401586134ff9e6572954687822a58055ec07a60ded4e0b7f AS base
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 OMP_NUM_THREADS=1 OPENBLAS_NUM_THREADS=1
RUN apt-get update && apt-get install -y --no-install-recommends libgomp1 && rm -rf /var/lib/apt/lists/*

FROM base AS build
COPY --from=ghcr.io/astral-sh/uv:0.12.24@sha256:3af4716e991d6956a41e573eab705d0ee08500cd829ed30293eb8472f372c65a /uv /usr/local/bin/uv
ENV UV_LINK_MODE=copy UV_COMPILE_BYTECODE=1 UV_PYTHON_DOWNLOADS=never
WORKDIR /app/backend
COPY backend/pyproject.toml backend/uv.lock backend/README.md ./
COPY backend/src ./src
RUN uv sync --locked --no-dev --no-editable --python /usr/local/bin/python

FROM base AS runtime
RUN groupadd --gid 10001 wattwise && useradd --uid 10001 --gid wattwise --create-home wattwise && mkdir /state && chown wattwise:wattwise /state
WORKDIR /app/backend
COPY --from=build /app/backend/.venv /app/backend/.venv
COPY data/sample/synthetic /app/data/sample/synthetic
COPY data/reference /app/data/reference
COPY --from=frontend /app/frontend/dist /app/static
ENV PATH="/app/backend/.venv/bin:$PATH" \
    WATTWISE_ENVIRONMENT=production \
    WATTWISE_READ_ONLY=true \
    WATTWISE_MODEL_DATA_KIND=synthetic \
    WATTWISE_REGISTRY_ROOT=/state/models \
    WATTWISE_EVALUATION_ROOT=/state/evaluation \
    WATTWISE_STATIC_DIR=/app/static
USER 10001:10001
RUN python -m wattwise.demo --build-only --data /app/data/sample/synthetic --artifacts /state
EXPOSE 10000
CMD ["python", "-m", "wattwise.public_demo", "--artifacts", "/state", "--data", "/app/data/sample/synthetic"]
