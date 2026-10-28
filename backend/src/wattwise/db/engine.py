"""The database engine and the readiness check."""

from __future__ import annotations

import logging
from enum import StrEnum

from sqlalchemy import Engine, create_engine
from sqlalchemy.exc import SQLAlchemyError

from wattwise.db.migrate import current_revision, head_revision

logger = logging.getLogger(__name__)

CONNECT_TIMEOUT_SECONDS = 3  # readiness must answer quickly when the database is down


class DatabaseStatus(StrEnum):
    OK = "ok"
    NOT_CONFIGURED = "not_configured"
    UNREACHABLE = "unreachable"
    SCHEMA_OUTDATED = "schema_outdated"


def create_db_engine(url: str) -> Engine:
    """An engine for `url` (postgresql+psycopg://...). It connects lazily, on first use."""
    return create_engine(
        url,
        pool_pre_ping=True,
        connect_args={"connect_timeout": CONNECT_TIMEOUT_SECONDS},
    )


def check_database(engine: Engine | None) -> DatabaseStatus:
    """Whether the database can serve: configured, reachable, and migrated to the head revision.

    Never raises, and never puts the connection error (which may carry the host or user) in
    the result; the exception type is logged."""
    if engine is None:
        return DatabaseStatus.NOT_CONFIGURED
    try:
        with engine.connect() as connection:
            current = current_revision(connection)
    except SQLAlchemyError as exc:
        logger.warning("database check failed: %s", type(exc).__name__)
        return DatabaseStatus.UNREACHABLE
    return DatabaseStatus.OK if current == head_revision() else DatabaseStatus.SCHEMA_OUTDATED
