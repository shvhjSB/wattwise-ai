"""Start the public, read-only synthetic demo in one container (T046, D064).

Used as the container command on Render (`render.yaml`):
1. Takes the database URL from `WATTWISE_DATABASE_URL`, or from the platform's `DATABASE_URL`
   (`postgresql://...`), adding the psycopg driver WattWise requires. It is never printed.
2. Seeds the synthetic demo from the model trained into the image at build time
   (`python -m wattwise.demo --build-only`). A fresh database is seeded; a stored demo made with
   another model is replaced (`replace_stale`); otherwise nothing changes. Startup stops if
   seeding fails, so a broken demo is never served.
3. Serves the API and the built frontend on `0.0.0.0:$PORT` (Render's default 10000).

    python -m wattwise.public_demo --artifacts /state --data /app/data/sample/synthetic
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from collections.abc import Mapping, MutableMapping, Sequence
from pathlib import Path
from typing import Final

from sqlalchemy.exc import SQLAlchemyError

from wattwise.core.config import DATABASE_DRIVER_PREFIX
from wattwise.db.engine import create_db_engine
from wattwise.demo import initialize_demo
from wattwise.ml.registry import RegistryError

DEFAULT_PORT: Final = 10000
PLATFORM_URL_PREFIXES: Final = ("postgresql://", "postgres://")


def database_url(environ: Mapping[str, str]) -> str | None:
    """WattWise's database URL from the environment, converting a platform `DATABASE_URL`."""
    if environ.get("WATTWISE_DATABASE_URL"):
        return environ["WATTWISE_DATABASE_URL"]
    platform = environ.get("DATABASE_URL", "")
    for prefix in PLATFORM_URL_PREFIXES:
        if platform.startswith(prefix):
            return DATABASE_DRIVER_PREFIX + platform.removeprefix(prefix)
    return None


def configure(environ: MutableMapping[str, str]) -> str:
    """Set `WATTWISE_DATABASE_URL` and the public-demo defaults; return the URL."""
    url = database_url(environ)
    if url is None:
        raise ValueError("Set DATABASE_URL (postgresql://...) or WATTWISE_DATABASE_URL.")
    environ["WATTWISE_DATABASE_URL"] = url
    environ.setdefault("WATTWISE_READ_ONLY", "true")
    environ.setdefault("WATTWISE_MODEL_DATA_KIND", "synthetic")
    return url


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m wattwise.public_demo", description=__doc__)
    parser.add_argument("--artifacts", type=Path, default=Path("/state"))
    parser.add_argument("--data", type=Path, default=Path("/app/data/sample/synthetic"))
    args = parser.parse_args(argv)
    try:
        url = configure(os.environ)
    except ValueError as exc:
        print(f"Public demo cannot start: {exc}", file=sys.stderr)
        return 1
    engine = create_db_engine(url)
    try:
        result = initialize_demo(engine, args.data, args.artifacts, replace_stale=True)
    except SQLAlchemyError as exc:
        print(f"Demo database initialization failed ({type(exc).__name__}).", file=sys.stderr)
        return 1
    except (ValueError, OSError, RegistryError) as exc:
        print(f"Demo initialization failed: {exc}", file=sys.stderr)
        return 1
    finally:
        engine.dispose()
    print(json.dumps({"synthetic": True, **result.__dict__}), flush=True)

    import uvicorn  # after seeding, so a failed seed never binds the port

    uvicorn.run(
        "wattwise.api.main:create_app",
        factory=True,
        host="0.0.0.0",  # the container's only interface
        port=int(os.environ.get("PORT", DEFAULT_PORT)),
        access_log=False,
        proxy_headers=True,
        forwarded_allow_ips="*",
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
