"""
Central configuration for the Uganda Business Scraper.

PHASE 1 REFACTOR — configuration only.
Every configurable value used across the app is defined here so the rest of the
codebase imports from one place instead of hardcoding literals. Behaviour is
unchanged: every default below matches the value that previously lived inline.

Sensitive values (database credentials, the Firecrawl API key, the Flask secret)
are read from environment variables, which are loaded from a local `.env` file
when present. See `.env.example` for the full list of supported variables.

Nothing in this module imports from the application, so importing `config` can
never create a circular import.
"""

import os

# ── Load .env (optional) ──────────────────────────────────────────────────────
# python-dotenv is listed in requirements.txt. If it is not installed yet we
# degrade gracefully and simply rely on real environment variables, so the app
# still starts.
_BASE_DIR = os.path.dirname(os.path.abspath(__file__))

try:
    from dotenv import load_dotenv
    load_dotenv(os.path.join(_BASE_DIR, ".env"))
except ImportError:  # python-dotenv not installed — use real env vars only
    pass


# ── Small env helpers ─────────────────────────────────────────────────────────

def _env(name, default=None):
    """Return env var `name`, or `default` if unset/empty."""
    val = os.environ.get(name)
    return val if val not in (None, "") else default


def _env_int(name, default):
    try:
        return int(_env(name, default))
    except (TypeError, ValueError):
        return default


def _env_float(name, default):
    try:
        return float(_env(name, default))
    except (TypeError, ValueError):
        return default


# ── Project paths ─────────────────────────────────────────────────────────────
BASE_DIR = _BASE_DIR

# Jinja templates folder (relative name passed to Flask).
TEMPLATE_FOLDER = _env("TEMPLATE_FOLDER", "templates")

# SQLite database file (used when running on the SQLite backend).
SQLITE_DB_FILENAME = _env("SQLITE_DB_FILENAME", "uganda_businesses.db")
SQLITE_DB_PATH = _env("SQLITE_DB_PATH", os.path.join(BASE_DIR, SQLITE_DB_FILENAME))

# Excel export folders.
EXPORTS_DIR = _env("EXPORT_DIR", os.path.join(BASE_DIR, "exports"))
DAILY_EXPORTS_DIR = _env("DAILY_EXPORT_DIR", os.path.join(EXPORTS_DIR, "daily"))

# Persistent Chrome profiles (one sub-folder per platform).
BROWSER_PROFILE_DIR = _env("BROWSER_PROFILE_DIR", os.path.join(BASE_DIR, "browser_profiles"))


# ── Database engine selection ─────────────────────────────────────────────────
# DB_ENGINE: "auto" (default), "postgres", or "sqlite".
#   • "auto" preserves the original behaviour: use PostgreSQL when DATABASE_URL,
#     PGDATABASE or PGHOST is set, otherwise fall back to the SQLite file.
DB_ENGINE = _env("DB_ENGINE", "auto").lower()

# PostgreSQL connection. DB_* names are preferred; the original PG* names are
# still honoured for backward compatibility.
DATABASE_URL = _env("DATABASE_URL")
DB_HOST = _env("DB_HOST", _env("PGHOST", "localhost"))
DB_PORT = _env("DB_PORT", _env("PGPORT", "5432"))
DB_NAME = _env("DB_NAME", _env("PGDATABASE", "uganda_businesses"))
DB_USER = _env("DB_USER", _env("PGUSER", "postgres"))
DB_PASSWORD = _env("DB_PASSWORD", _env("PGPASSWORD", ""))

# Resolve whether to use PostgreSQL. Auto-detection matches the original triggers
# (DATABASE_URL / PGDATABASE / PGHOST) so existing setups behave identically.
if DB_ENGINE == "postgres":
    USE_POSTGRES = True
elif DB_ENGINE == "sqlite":
    USE_POSTGRES = False
else:  # auto
    USE_POSTGRES = bool(
        os.environ.get("DATABASE_URL")
        or os.environ.get("PGDATABASE")
        or os.environ.get("PGHOST")
    )

# Platforms the app collects from. Shared by both database backends so the list
# is defined in exactly one place.
PLATFORMS = ["jiji", "instagram", "yellowpages", "twitter", "tiktok"]


# ── Firecrawl integration ─────────────────────────────────────────────────────
# The API key is a secret and must come from the environment (.env). It is no
# longer hardcoded in the database seed. Existing installs are unaffected because
# the key is already stored in their settings table.
FIRECRAWL_API_KEY = _env("FIRECRAWL_API_KEY", "")


# ── Scraping limits & timing ──────────────────────────────────────────────────
# Default number of businesses to collect per platform per run (overridable in
# the Settings UI, which stores its own value in the database).
DAILY_LIMIT_DEFAULT = _env_int("DAILY_LIMIT_DEFAULT", 40)

# Upper bound used when reading businesses back out of the database for exports.
BUSINESS_QUERY_LIMIT = _env_int("BUSINESS_QUERY_LIMIT", 5000)

# Yellow Pages (static HTTP scraper).
YP_BASE_URL = _env("YP_BASE_URL", "https://www.yellowpages-uganda.com")
YP_MAX_PAGES_PER_CATEGORY = _env_int("YP_MAX_PAGES_PER_CATEGORY", 60)
YP_REQUEST_TIMEOUT = _env_int("YP_REQUEST_TIMEOUT", 30)
YP_REQUEST_DELAY = _env_float("YP_REQUEST_DELAY", 1.0)

# Jiji (Selenium scraper).
JIJI_MAX_PAGES_PER_CATEGORY = _env_int("JIJI_MAX_PAGES_PER_CATEGORY", 10)

# Selenium browser factory.
BROWSER_PAGE_LOAD_TIMEOUT = _env_int("BROWSER_PAGE_LOAD_TIMEOUT", 45)
BROWSER_WINDOW_SIZE = _env("BROWSER_WINDOW_SIZE", "1320,920")


# ── Scheduler defaults ────────────────────────────────────────────────────────
SCHEDULER_TIMEZONE = _env("SCHEDULER_TIMEZONE", "Africa/Kampala")
SCHEDULE_HOUR_DEFAULT = _env_int("SCHEDULE_HOUR_DEFAULT", 8)
SCHEDULE_MINUTE_DEFAULT = _env_int("SCHEDULE_MINUTE_DEFAULT", 0)
AUTOMATION_ENABLED_DEFAULT = _env("AUTOMATION_ENABLED_DEFAULT", "1")
DISABLED_PLATFORMS_DEFAULT = os.environ.get("DISABLED_PLATFORMS_DEFAULT", "")


# ── Flask / web server ────────────────────────────────────────────────────────
# Session secret. When unset, app.py falls back to a value stored in the database
# (generated once), exactly as before.
FLASK_SECRET_KEY = _env("FLASK_SECRET_KEY")

HOST = _env("HOST", "0.0.0.0")
PORT = _env_int("PORT", 5050)

# ── Session cookie security ───────────────────────────────────────────────────
# SESSION_COOKIE_SECURE is off by default so local HTTP testing (Kali <-> Windows)
# still works. Set FLASK_ENV=production (e.g. in Railway's env vars) to enable it
# automatically once deployed over HTTPS.
SESSION_COOKIE_SECURE = _env("FLASK_ENV", "development") == "production"
SESSION_COOKIE_SAMESITE = _env("SESSION_COOKIE_SAMESITE", "Lax")


# ── Email / SMTP (password-reset links) ───────────────────────────────────────
# All secrets come from the environment (.env). For Gmail use an App Password
# (not your normal password) with SMTP_HOST=smtp.gmail.com and SMTP_PORT=587.
SMTP_HOST     = _env("SMTP_HOST", "")
SMTP_PORT     = _env_int("SMTP_PORT", 587)
SMTP_USER     = _env("SMTP_USER", "")
SMTP_PASSWORD = _env("SMTP_PASSWORD", "")
# Sender address shown on the email; defaults to the SMTP login.
SMTP_FROM     = _env("SMTP_FROM", SMTP_USER or "")
# Use implicit SSL (port 465) instead of STARTTLS (port 587). Default: STARTTLS.
SMTP_USE_SSL  = _env("SMTP_USE_SSL", "0") in ("1", "true", "True", "yes", "on")

# Base URL used to build links inside emails. Must be reachable by the person
# clicking the link. Defaults to the local dev address; set this to a LAN/host
# address (e.g. http://192.168.1.20:5050) if others open the app over a network.
APP_BASE_URL = _env("APP_BASE_URL", f"http://{HOST}:{PORT}")

# How long a password-reset link stays valid, in minutes.
RESET_TOKEN_TTL_MIN = _env_int("RESET_TOKEN_TTL_MIN", 60)
