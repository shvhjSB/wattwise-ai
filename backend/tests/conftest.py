import os
import uuid
from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Engine, create_engine, text

from wattwise.api.main import create_app
from wattwise.core.config import Settings

#: A PostgreSQL database the tests may create and drop schemas in (never a database with data
#: that matters). Locally: see backend/README.md. CI provides a service container.
TEST_DATABASE_ENV = "WATTWISE_TEST_DATABASE_URL"


@pytest.fixture
def client() -> Iterator[TestClient]:
    """A test client for an app built with explicit test settings, and no database."""
    app = create_app(Settings(environment="test", database_url=None))
    with TestClient(app) as test_client:
        yield test_client


@pytest.fixture(scope="session")
def test_database_url() -> str:
    """The test database's URL, or a skip when it is not configured (a failure in CI, where
    a database is always provided, so the PostgreSQL tests cannot silently stop running)."""
    url = os.environ.get(TEST_DATABASE_ENV)
    if url:
        return url
    if os.environ.get("CI"):
        pytest.fail(f"{TEST_DATABASE_ENV} must be set in CI")
    pytest.skip(f"{TEST_DATABASE_ENV} is not set; see backend/README.md")


@pytest.fixture
def schema_engine(test_database_url: str) -> Iterator[Engine]:
    """An engine whose connections use a fresh, empty schema of the test database.

    Every test gets its own schema, so tests cannot affect each other, and the schema is
    dropped afterwards. Migrations run inside it (their tables and `alembic_version` land in
    the first schema of the search path)."""
    schema = f"t_{uuid.uuid4().hex[:12]}"
    admin = create_engine(test_database_url, isolation_level="AUTOCOMMIT")
    with admin.connect() as connection:
        connection.execute(text(f'CREATE SCHEMA "{schema}"'))
    engine = create_engine(test_database_url, connect_args={"options": f"-csearch_path={schema}"})
    try:
        yield engine
    finally:
        engine.dispose()
        with admin.connect() as connection:
            connection.execute(text(f'DROP SCHEMA "{schema}" CASCADE'))
        admin.dispose()
