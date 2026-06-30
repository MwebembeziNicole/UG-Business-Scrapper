"""
database.repository
────────────────────
Phase 3 — a single, stable entry point for every database operation.

The rest of the application should obtain its database functions from here:

    from database.repository import get_businesses, insert_business, init_db, ...

instead of reaching into a specific backend module:

    • database.py        (legacy SQLite shim)
    • database_pg.py     (legacy PostgreSQL shim)
    • database.sqlite    (SQLite implementation)
    • database.postgres  (PostgreSQL implementation)

WHY
---
This module is a *thin abstraction layer*. It contains no SQL and no business
logic of its own — it simply delegates every call to whichever backend
``database.connection`` selected (SQLite or PostgreSQL, decided once from
``config``). Centralising access here means later phases can evolve the storage
layer (add caching, services, new engines) by touching this one file rather than
every caller.

BACKWARDS COMPATIBILITY
-----------------------
Nothing about the existing behaviour changes:

    • ``import database``      still works (SQLite shim / package).
    • ``import database_pg``   still works (PostgreSQL shim).
    • ``database.sqlite`` / ``database.postgres`` still work directly.

The repository re-exports the *complete* public API of the active backend, so
any name that worked when imported from a backend continues to work when
imported from here — including constants such as ``PLATFORMS`` and the various
queue helpers — with identical behaviour.

ENGINE SELECTION
----------------
The backend is chosen by ``database.connection`` from ``config.USE_POSTGRES``:

    • DATABASE_ENGINE == "sqlite"   → SQLite  (database.sqlite)
    • DATABASE_ENGINE == "postgres" → PostgreSQL (database.postgres)

so this module automatically uses the right engine without any caller changes.
"""

from database.connection import DATABASE_ENGINE, get_backend

# The active backend module (``database.sqlite`` or ``database.postgres``),
# resolved once from config — exactly the module the application would have
# imported as ``database`` / ``database_pg`` before this phase.
_backend = get_backend()


# ── Canonical database operations ───────────────────────────────────────────────
# Explicit, self-documenting wrappers around the operations the application uses.
# Each one delegates verbatim to the active backend (same name, same arguments,
# same return value) so there is a single, discoverable surface for callers while
# the actual implementation stays in sqlite.py / postgres.py.

# Schema / lifecycle
def init_db(*args, **kwargs):
    """Create tables / run lightweight migrations on the active backend."""
    return _backend.init_db(*args, **kwargs)


def get_connection(*args, **kwargs):
    """Return a raw connection from the active backend (used by tooling)."""
    return _backend.get_connection(*args, **kwargs)


# Businesses
def insert_business(*args, **kwargs):
    """Insert a scraped business (with the backend's de-dup rules). Returns bool."""
    return _backend.insert_business(*args, **kwargs)


def get_businesses(*args, **kwargs):
    """Return business rows for one platform or all platforms."""
    return _backend.get_businesses(*args, **kwargs)


def delete_business(*args, **kwargs):
    """Delete a single business row by platform + id. Returns bool."""
    return _backend.delete_business(*args, **kwargs)


def get_stats(*args, **kwargs):
    """Per-platform total / today counts."""
    return _backend.get_stats(*args, **kwargs)


# Scrape logs
def start_log(*args, **kwargs):
    """Open a scrape-log row ('running') and return its id."""
    return _backend.start_log(*args, **kwargs)


def finish_log(*args, **kwargs):
    """Close out a scrape-log row with success/error + counts."""
    return _backend.finish_log(*args, **kwargs)


def mark_stale_running_failed(*args, **kwargs):
    """Mark leftover 'running' logs as failed (called once at startup)."""
    return _backend.mark_stale_running_failed(*args, **kwargs)


def get_logs(*args, **kwargs):
    """Return the most recent scrape-log rows."""
    return _backend.get_logs(*args, **kwargs)


# Settings
def get_setting(*args, **kwargs):
    """Read a single setting value (with optional default)."""
    return _backend.get_setting(*args, **kwargs)


def save_setting(*args, **kwargs):
    """Upsert a single setting value."""
    return _backend.save_setting(*args, **kwargs)


# Users / authentication
def create_user(*args, **kwargs):
    """Create a login account with a hashed password. Returns bool."""
    return _backend.create_user(*args, **kwargs)


def get_user_by_username(*args, **kwargs):
    """Return the user dict for a username, or None."""
    return _backend.get_user_by_username(*args, **kwargs)


def get_user_by_id(*args, **kwargs):
    """Return the user dict for an id, or None."""
    return _backend.get_user_by_id(*args, **kwargs)


def verify_user(*args, **kwargs):
    """Return the user dict if username + password are correct, else None."""
    return _backend.verify_user(*args, **kwargs)


def user_count(*args, **kwargs):
    """Number of login accounts."""
    return _backend.user_count(*args, **kwargs)


# ── Convenience aliases ─────────────────────────────────────────────────────────
# Friendlier names some callers may prefer, mapped to the existing backend
# functions. These are aliases only — they add no new behaviour and keep the
# original names fully available.
save_business = insert_business      # alias for insert_business
get_scrape_logs = get_logs           # alias for get_logs


# ── Complete re-export of the active backend's public API ───────────────────────
# Anything public the backend exposes that is not already wrapped above (queue
# helpers for Instagram/Jiji/Twitter/TikTok, the ``PLATFORMS`` constant, etc.) is
# mirrored here verbatim. This guarantees the repository is a full, drop-in
# replacement for ``import database as db`` — no caller can lose access to a name
# that previously lived on the backend — without duplicating any logic.
#
# Imported third-party/stdlib helpers pulled into the backend's namespace (config,
# datetime, sqlite3, the password-hash helpers, …) are skipped so the repository
# surface stays limited to the database API itself.
import types as _types

_SKIP = {
    "config", "datetime", "os", "sys", "sqlite3", "psycopg2",
    "generate_password_hash", "check_password_hash",
}

for _name in dir(_backend):
    if _name.startswith("_") or _name in _SKIP:
        continue
    if _name in globals():
        continue  # already provided by an explicit wrapper / alias above
    _attr = getattr(_backend, _name)
    if isinstance(_attr, _types.ModuleType):
        continue  # don't re-export imported modules
    globals()[_name] = _attr


# Public surface: the explicit wrappers/aliases plus every mirrored backend name.
__all__ = [
    _n for _n, _v in list(globals().items())
    if not _n.startswith("_") and _n not in {"get_backend", "DATABASE_ENGINE"}
    and not isinstance(_v, _types.ModuleType)
]
