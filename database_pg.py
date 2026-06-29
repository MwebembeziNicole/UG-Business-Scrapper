"""
Backwards-compatibility shim — PostgreSQL backend.

The PostgreSQL implementation now lives in `database/postgres.py`. This module is
kept (not deleted) so existing `import database_pg` statements keep working
unchanged; it simply re-exports the package implementation.
"""

from database.postgres import *  # noqa: F401,F403
