from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient

from wattwise.api.main import create_app
from wattwise.core.config import Settings


@pytest.fixture
def client() -> Iterator[TestClient]:
    """A test client for an app built with explicit test settings."""
    app = create_app(Settings(environment="test"))
    with TestClient(app) as test_client:
        yield test_client
