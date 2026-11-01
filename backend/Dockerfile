FROM python:3.13-slim-bookworm@sha256:281d39ff02e3b389401586134ff9e6572954687822a58055ec07a60ded4e0b7f AS base
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 OMP_NUM_THREADS=1 OPENBLAS_NUM_THREADS=1
RUN apt-get update && apt-get install -y --no-install-recommends libgomp1 && rm -rf /var/lib/apt/lists/*

FROM base AS build
COPY --from=ghcr.io/astral-sh/uv:0.12.24@sha256:3af4716e991d6956a41e573eab705d0ee08500cd829ed30293eb8472f372c65a /uv /usr/local/bin/uv
ENV UV_LINK_MODE=copy UV_COMPILE_BYTECODE=1 UV_PYTHON_DOWNLOADS=never
WORKDIR /app/backend
COPY backend/pyproject.toml backend/uv.lock backend/README.md ./
COPY backend/src ./src
RUN --mount=type=cache,target=/root/.cache/uv uv sync --locked --no-dev --no-editable --python /usr/local/bin/python

FROM base AS runtime
RUN groupadd --gid 10001 wattwise && useradd --uid 10001 --gid wattwise --create-home wattwise && mkdir /state && chown wattwise:wattwise /state
WORKDIR /app/backend
COPY --from=build /app/backend/.venv /app/backend/.venv
COPY data/sample/synthetic /app/data/sample/synthetic
COPY data/reference /app/data/reference
ENV PATH="/app/backend/.venv/bin:$PATH"
USER 10001:10001
EXPOSE 8000
HEALTHCHECK --interval=5s --timeout=5s --start-period=15s --retries=12 CMD ["python", "-c", "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/api/v1/ready', timeout=3).close()"]
CMD ["python", "-m", "uvicorn", "wattwise.api.main:create_app", "--factory", "--host", "0.0.0.0", "--port", "8000"]
