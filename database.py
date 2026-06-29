"""
Backwards-compatibility shim — SQLite backend.

The SQLite implementation now lives in `database/sqlite.py`. This module is kept
(not deleted) so any existing `import database` / path-based tooling keeps
resolving, and simply re-exports the same public API.

NOTE: when the `database/` package is present, Python resolves `import database`
to the package (`database/__init__.py`), which re-exports this very same SQLite
API. Both paths therefore expose identical behaviour.
"""

from database.sqlite import *  # noqa: F401,F403
