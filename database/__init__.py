"""
Database package (Phase 2).

Backends live in dedicated modules so additional engines (e.g. sqlserver.py,
oracle.py) can be added later without touching the rest of the app:

    • database.sqlite     — SQLite implementation
    • database.postgres   — PostgreSQL implementation
    • database.connection — selects the active backend (see config.USE_POSTGRES)

Historically `import database` meant "the SQLite backend" — the application
selects PostgreSQL explicitly via `import database_pg`. To preserve that exact
behaviour, this package re-exports the full public API of the SQLite backend.
"""

# Re-export the SQLite public API → `import database` behaves exactly as before.
from .sqlite import *  # noqa: F401,F403

# Make submodules conveniently accessible as database.sqlite / database.connection.
from . import sqlite       # noqa: F401
from . import connection   # noqa: F401
