from alembic.autogenerate import compare_metadata
from alembic.runtime.migration import MigrationContext
from sqlalchemy import Engine, inspect

from wattwise.db.base import Base
from wattwise.db.migrate import current_revision, downgrade, head_revision, upgrade

TABLES = {
    "datasets",
    "buildings",
    "meters",
    "readings",
    "alerts",
    "alert_feedback",
    "analysis_runs",
}


def tables(engine: Engine) -> set[str]:
    return set(inspect(engine).get_table_names()) - {"alembic_version"}


def test_upgrade_creates_the_tables_and_records_the_head_revision(schema_engine: Engine) -> None:
    with schema_engine.begin() as connection:
        upgrade(connection)

    assert tables(schema_engine) == TABLES
    with schema_engine.connect() as connection:
        assert current_revision(connection) == head_revision()


def test_downgrade_removes_everything_it_created(schema_engine: Engine) -> None:
    with schema_engine.begin() as connection:
        upgrade(connection)
    with schema_engine.begin() as connection:
        downgrade(connection)

    assert tables(schema_engine) == set()
    with schema_engine.connect() as connection:
        assert current_revision(connection) is None


def test_the_migrations_upgrade_and_downgrade_cleanly_more_than_once(
    schema_engine: Engine,
) -> None:
    for _ in range(2):
        with schema_engine.begin() as connection:
            upgrade(connection)
        assert tables(schema_engine) == TABLES
        with schema_engine.begin() as connection:
            downgrade(connection)
        assert tables(schema_engine) == set()


def test_the_models_match_the_migrated_schema(schema_engine: Engine) -> None:
    """A model change without a migration (or the reverse) shows up as a difference here."""
    with schema_engine.begin() as connection:
        upgrade(connection)

    with schema_engine.connect() as connection:
        context = MigrationContext.configure(connection, opts={"compare_type": True})
        assert compare_metadata(context, Base.metadata) == []


def test_there_is_a_single_head_revision() -> None:
    assert head_revision() == "0004"


def test_each_revision_downgrades_to_the_one_before(schema_engine: Engine) -> None:
    with schema_engine.begin() as connection:
        upgrade(connection, "0001")
    assert tables(schema_engine) == {"buildings", "meters"}
    with schema_engine.begin() as connection:
        upgrade(connection)
    with schema_engine.begin() as connection:
        downgrade(connection, "0001")

    assert tables(schema_engine) == {"buildings", "meters"}
    with schema_engine.connect() as connection:
        assert current_revision(connection) == "0001"
