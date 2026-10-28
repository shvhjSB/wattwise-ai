"""Alembic environment: runs online, on a given connection or on `WATTWISE_DATABASE_URL`."""

from typing import Any

from alembic import context

from wattwise.core.config import get_settings
from wattwise.db import models  # noqa: F401  (registers the tables on the metadata)
from wattwise.db.base import Base
from wattwise.db.engine import create_db_engine

config = context.config


def _migrate(connection: Any) -> None:
    context.configure(connection=connection, target_metadata=Base.metadata, compare_type=True)
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    connection = config.attributes.get("connection")
    if connection is not None:
        _migrate(connection)
        return
    url = get_settings().database_url
    if url is None:
        raise RuntimeError("WATTWISE_DATABASE_URL is not set")
    engine = create_db_engine(url.get_secret_value())
    try:
        with engine.connect() as own:
            _migrate(own)
            own.commit()
    finally:
        engine.dispose()


if context.is_offline_mode():
    raise RuntimeError("offline (--sql) migrations are not supported; run against a database")
run_migrations_online()
