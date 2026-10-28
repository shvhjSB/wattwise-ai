"""Persistence: the SQLAlchemy models, the engine, and the Alembic migrations (T023).

Nothing in `wattwise.ml` imports this package; the pipeline reads Parquet, and the API stores
what it serves here.
"""
