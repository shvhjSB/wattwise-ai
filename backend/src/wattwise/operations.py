"""One-shot migration and release checks for the private deployment recipe."""

import argparse
import json
import sys
from collections.abc import Sequence

from sqlalchemy import Engine, text

from wattwise.api.routes.models import model_evaluation
from wattwise.core.config import Settings, get_settings
from wattwise.db.engine import DatabaseStatus, check_database, create_db_engine
from wattwise.db.migrate import current_revision, head_revision, upgrade
from wattwise.ml.registry import current, verify

MIGRATION_LOCK = 742_038_001


class DeploymentError(RuntimeError):
    """A deployment failed a named, non-sensitive check."""


def migrate_database(engine: Engine) -> str:
    """Serialize migrations; never seed data, downgrade or select a model."""
    with engine.begin() as connection:
        connection.execute(text("SELECT pg_advisory_xact_lock(:key)"), {"key": MIGRATION_LOCK})
        upgrade(connection)
        revision = current_revision(connection)
        if revision != head_revision():
            raise DeploymentError("schema_outdated")
    return revision


def check_release(settings: Settings, engine: Engine, model_version: str) -> dict[str, str]:
    """Require a migrated database and the pinned, verified model/report bundle."""
    status = check_database(engine)
    if status is not DatabaseStatus.OK:
        raise DeploymentError(f"database_{status.value}")
    if current(settings.registry_root) != model_version:
        raise DeploymentError("model_version_mismatch")
    verify(model_version, settings.registry_root)
    report = model_evaluation(settings, limit=1)
    if not report.available or report.version != model_version:
        raise DeploymentError("evaluation_unavailable_or_mismatched")
    return {
        "revision": head_revision(),
        "model_version": model_version,
        "data_kind": settings.model_data_kind,
    }


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("migrate")
    check = commands.add_parser("check")
    check.add_argument("--model-version", required=True)
    args = parser.parse_args(argv)
    engine = None
    try:
        settings = get_settings()
        if settings.database_url is None:
            raise DeploymentError("database_not_configured")
        engine = create_db_engine(settings.database_url.get_secret_value())
        if args.command == "migrate":
            result = {"event": "migration_complete", "revision": migrate_database(engine)}
        else:
            result = {
                "event": "release_checked",
                **check_release(settings, engine, args.model_version),
            }
        print(json.dumps(result))
        return 0
    except Exception as exc:
        print(
            json.dumps(
                {
                    "event": "deployment_failed",
                    "error_type": type(exc).__name__,
                    "reason": str(exc) if isinstance(exc, DeploymentError) else "operation_failed",
                }
            ),
            file=sys.stderr,
        )
        return 1
    finally:
        if engine is not None:
            engine.dispose()


if __name__ == "__main__":
    raise SystemExit(main())
