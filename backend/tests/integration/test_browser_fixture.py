import json
from pathlib import Path

import pytest

from tests.browser_fixture import schema_of
from tests.browser_fixture import test_database_url as browser_database_url


@pytest.mark.parametrize(
    "url",
    [
        "",
        "postgresql+psycopg://test:unused@localhost/wattwise",
        "sqlite:///wattwise_test",
    ],
)
def test_browser_fixture_refuses_unconfigured_or_non_test_databases(
    monkeypatch: pytest.MonkeyPatch, url: str
) -> None:
    monkeypatch.setenv("WATTWISE_TEST_DATABASE_URL", url)
    with pytest.raises(ValueError):
        browser_database_url()


@pytest.mark.parametrize("schema", ["public", 'e2e_123456789abc"; DROP SCHEMA public', "e2e_123"])
def test_browser_cleanup_refuses_non_fixture_schemas(tmp_path: Path, schema: str) -> None:
    state = tmp_path / "state.json"
    state.write_text(json.dumps({"schema": schema}), encoding="utf-8")
    with pytest.raises(ValueError, match="Invalid browser-test schema"):
        schema_of(state)
