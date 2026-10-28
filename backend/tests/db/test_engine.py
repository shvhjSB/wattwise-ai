from sqlalchemy import text

from wattwise.db.engine import DatabaseStatus, check_database, create_db_engine


def test_engine_sessions_run_in_utc(test_database_url: str) -> None:
    """Timestamps must read back in UTC whatever the server's own time zone is."""
    engine = create_db_engine(test_database_url)
    try:
        with engine.connect() as connection:
            assert connection.execute(text("SHOW timezone")).scalar() == "UTC"
    finally:
        engine.dispose()


def test_no_engine_means_not_configured() -> None:
    assert check_database(None) is DatabaseStatus.NOT_CONFIGURED
