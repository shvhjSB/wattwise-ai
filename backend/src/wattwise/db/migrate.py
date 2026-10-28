"""Alembic from Python: the configuration, the head revision and upgrade/downgrade.

The migrations live inside the package (`wattwise/db/migrations`) so a built image carries them.
The command line uses `backend/alembic.ini`:

    uv run --env-file .env alembic upgrade head
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from alembic import command
from alembic.config import Config
from alembic.runtime.migration import MigrationContext
from alembic.script import ScriptDirectory
from sqlalchemy import Connection

MIGRATIONS = Path(__file__).parent / "migrations"


def alembic_config(connection: Connection | None = None) -> Config:
    """The Alembic configuration; with `connection`, migrations run on it, not on the
    `WATTWISE_DATABASE_URL` database."""
    config = Config()
    config.set_main_option("script_location", str(MIGRATIONS))
    if connection is not None:
        config.attributes["connection"] = connection
    return config


@lru_cache
def head_revision() -> str:
    head = ScriptDirectory.from_config(alembic_config()).get_current_head()
    if head is None:
        raise RuntimeError("the migrations have no head revision")
    return head


def current_revision(connection: Connection) -> str | None:
    """The revision the database is at, or None if it was never migrated."""
    return MigrationContext.configure(connection).get_current_revision()


def upgrade(connection: Connection, revision: str = "head") -> None:
    command.upgrade(alembic_config(connection), revision)


def downgrade(connection: Connection, revision: str = "base") -> None:
    command.downgrade(alembic_config(connection), revision)
