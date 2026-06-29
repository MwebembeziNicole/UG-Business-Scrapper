"""
database.connection
───────────────────
Decides which database backend is active, based on the Phase-1 configuration
(config.USE_POSTGRES). This module contains no SQL and no business logic — its
single responsibility is backend selection, so it stays trivial to extend with
future engines (sqlserver.py, oracle.py, ...).
"""

import config

# Human-readable name of the configured engine: "sqlite" or "postgres".
DATABASE_ENGINE = "postgres" if config.USE_POSTGRES else "sqlite"


def get_backend():
    """Return the active backend module (`database.sqlite` or `database.postgres`).

    Backends are imported lazily so that optional dependencies (e.g. psycopg2 for
    PostgreSQL) are only required when that backend is actually selected — exactly
    as the application behaved before this refactor.
    """
    if config.USE_POSTGRES:
        from . import postgres
        return postgres
    from . import sqlite
    return sqlite
