"""
PostgreSQL database layer — drop-in replacement for database.py.

Same public function names and return shapes as the SQLite version, so the rest
of the app (app.py, scrapers, exporter) does not change. To switch the app over,
change one import in app.py:

    import database as db          ->   import database_pg as db

Connection is read from the environment (so no secrets live in code):

    DATABASE_URL = postgresql://user:password@host:5432/uganda_businesses
        (or set PGHOST / PGPORT / PGDATABASE / PGUSER / PGPASSWORD individually)

Requires:  pip install psycopg2-binary
"""

import os
from datetime import datetime

import psycopg2
import psycopg2.extras
from werkzeug.security import generate_password_hash, check_password_hash

import config

PLATFORMS = config.PLATFORMS


# ── Connection ────────────────────────────────────────────────────────────────

def _conn_kwargs():
    if config.DATABASE_URL:
        return {"dsn": config.DATABASE_URL}
    return {
        "host":     config.DB_HOST,
        "port":     config.DB_PORT,
        "dbname":   config.DB_NAME,
        "user":     config.DB_USER,
        "password": config.DB_PASSWORD,
    }


def get_connection():
    """Plain connection (tuple cursors). Use dict_cursor() for dict rows."""
    return psycopg2.connect(**_conn_kwargs())


def dict_cursor(conn):
    return conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)


# ── Schema ────────────────────────────────────────────────────────────────────

def init_db():
    conn = get_connection()
    c = conn.cursor()

    for platform in PLATFORMS:
        c.execute(f"""
            CREATE TABLE IF NOT EXISTS {platform}_businesses (
                id            SERIAL PRIMARY KEY,
                business_name TEXT,
                username      TEXT,
                category      TEXT,
                phone         TEXT,
                email         TEXT,
                website       TEXT,
                facebook      TEXT,
                location      TEXT,
                source_url    TEXT,
                scraped_at    TEXT NOT NULL
            )
        """)
        # Forward-compatible column adds (no-op if already present)
        for col in ("email", "website", "facebook"):
            c.execute(f"ALTER TABLE {platform}_businesses ADD COLUMN IF NOT EXISTS {col} TEXT")

        # Partial unique indexes — Postgres supports these natively
        c.execute(f"""CREATE UNIQUE INDEX IF NOT EXISTS ux_{platform}_phone
                      ON {platform}_businesses(phone)
                      WHERE phone IS NOT NULL AND phone <> ''""")
        c.execute(f"""CREATE UNIQUE INDEX IF NOT EXISTS ux_{platform}_username
                      ON {platform}_businesses(username)
                      WHERE username IS NOT NULL AND username <> ''""")
        c.execute(f"""CREATE UNIQUE INDEX IF NOT EXISTS ux_{platform}_email
                      ON {platform}_businesses(email)
                      WHERE email IS NOT NULL AND email <> ''""")

    c.execute("""
        CREATE TABLE IF NOT EXISTS scrape_logs (
            id            SERIAL PRIMARY KEY,
            platform      TEXT    NOT NULL,
            started_at    TEXT    NOT NULL,
            completed_at  TEXT,
            status        TEXT    NOT NULL DEFAULT 'running',
            count_new     INTEGER DEFAULT 0,
            count_skipped INTEGER DEFAULT 0,
            error_message TEXT
        )
    """)

    c.execute("""
        CREATE TABLE IF NOT EXISTS settings (
            key   TEXT PRIMARY KEY,
            value TEXT
        )
    """)

    # App user accounts (login). Single login type — every account has full access.
    c.execute("""
        CREATE TABLE IF NOT EXISTS users (
            id            SERIAL PRIMARY KEY,
            username      TEXT NOT NULL UNIQUE,
            password_hash TEXT NOT NULL,
            created_at    TEXT NOT NULL
        )
    """)

    c.execute("""
        CREATE TABLE IF NOT EXISTS instagram_queue (
            id            SERIAL PRIMARY KEY,
            username      TEXT    NOT NULL UNIQUE,
            profile_url   TEXT    NOT NULL,
            discovered_at TEXT    NOT NULL,
            scraped       INTEGER NOT NULL DEFAULT 0
        )
    """)

    c.execute("""
        CREATE TABLE IF NOT EXISTS jiji_queue (
            id            SERIAL PRIMARY KEY,
            listing_url   TEXT    NOT NULL UNIQUE,
            title         TEXT,
            category      TEXT,
            discovered_at TEXT    NOT NULL,
            scraped       INTEGER NOT NULL DEFAULT 0
        )
    """)

    # Twitter/X and TikTok discovery queues (profile-based, like Instagram)
    for qtable in ("twitter_queue", "tiktok_queue"):
        c.execute(f"""
            CREATE TABLE IF NOT EXISTS {qtable} (
                id            SERIAL PRIMARY KEY,
                username      TEXT    NOT NULL UNIQUE,
                profile_url   TEXT    NOT NULL,
                discovered_at TEXT    NOT NULL,
                scraped       INTEGER NOT NULL DEFAULT 0
            )
        """)

    # Default settings (only inserted once). Values come from config.py; the
    # Firecrawl key is read from the environment, not hardcoded here.
    c.execute("INSERT INTO settings (key, value) VALUES (%s, %s) ON CONFLICT (key) DO NOTHING",
              ("firecrawl_api_key", config.FIRECRAWL_API_KEY))
    c.execute("INSERT INTO settings (key, value) VALUES (%s, %s) ON CONFLICT (key) DO NOTHING",
              ("daily_limit", str(config.DAILY_LIMIT_DEFAULT)))
    c.execute("INSERT INTO settings (key, value) VALUES (%s, %s) ON CONFLICT (key) DO NOTHING",
              ("schedule_hour", str(config.SCHEDULE_HOUR_DEFAULT)))
    c.execute("INSERT INTO settings (key, value) VALUES (%s, %s) ON CONFLICT (key) DO NOTHING",
              ("schedule_minute", str(config.SCHEDULE_MINUTE_DEFAULT)))

    conn.commit()
    conn.close()


# ── Businesses ────────────────────────────────────────────────────────────────

def insert_business(platform: str, business: dict) -> bool:
    if platform not in PLATFORMS:
        return False

    phone      = (business.get("phone") or "").strip()
    username   = (business.get("username") or "").strip()
    email      = (business.get("email") or "").strip()
    website    = (business.get("website") or "").strip()
    facebook   = (business.get("facebook") or "").strip()
    source_url = (business.get("source_url") or "").strip()

    # source_url is the stable identifier for directory listings (Yellow Pages
    # has no phone/username and often no email), so accept it too.
    if not (phone or username or email or source_url):
        return False

    conn = get_connection()
    c    = conn.cursor()
    try:
        if phone:
            c.execute(f"SELECT 1 FROM {platform}_businesses WHERE phone = %s", (phone,))
            if c.fetchone():
                return False
        if username:
            c.execute(f"SELECT 1 FROM {platform}_businesses WHERE username = %s", (username,))
            if c.fetchone():
                return False
        if email:
            c.execute(f"SELECT 1 FROM {platform}_businesses WHERE email = %s", (email,))
            if c.fetchone():
                return False
        if source_url:
            c.execute(f"SELECT 1 FROM {platform}_businesses WHERE source_url = %s", (source_url,))
            if c.fetchone():
                return False

        c.execute(f"""
            INSERT INTO {platform}_businesses
                (business_name, username, category, phone, email, website, facebook, location, source_url, scraped_at)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
        """, (
            (business.get("business_name") or "").strip(),
            username,
            (business.get("category") or "").strip(),
            phone, email, website, facebook,
            (business.get("location") or "").strip(),
            source_url,
            datetime.now().isoformat(),
        ))
        conn.commit()
        return True
    except psycopg2.IntegrityError:
        conn.rollback()
        return False
    finally:
        conn.close()


def get_businesses(platform: str = None, limit: int = 200, offset: int = 0, search: str = None) -> list:
    conn    = get_connection()
    results = []
    targets = [platform] if platform else PLATFORMS

    for p in targets:
        c = dict_cursor(conn)
        base   = f"SELECT *, '{p}' AS platform FROM {p}_businesses"
        params = []
        if search:
            base  += " WHERE business_name ILIKE %s OR phone ILIKE %s OR email ILIKE %s OR location ILIKE %s OR username ILIKE %s"
            params = [f"%{search}%"] * 5
        base  += " ORDER BY scraped_at DESC LIMIT %s OFFSET %s"
        params += [limit, offset]
        c.execute(base, params)
        results.extend([dict(r) for r in c.fetchall()])

    conn.close()
    return results


def delete_business(platform: str, record_id: int) -> bool:
    if platform not in PLATFORMS:
        return False
    conn = get_connection()
    conn.cursor().execute(f"DELETE FROM {platform}_businesses WHERE id = %s", (record_id,))
    conn.commit()
    conn.close()
    return True


def get_stats() -> dict:
    conn  = get_connection()
    c     = conn.cursor()
    today = datetime.now().date().isoformat()
    stats = {}
    for p in PLATFORMS:
        c.execute(f"SELECT COUNT(*) FROM {p}_businesses")
        total = c.fetchone()[0]
        c.execute(f"SELECT COUNT(*) FROM {p}_businesses WHERE scraped_at LIKE %s", (f"{today}%",))
        today_count = c.fetchone()[0]
        stats[p] = {"total": total, "today": today_count}
    conn.close()
    return stats


# ── Logs ──────────────────────────────────────────────────────────────────────

def start_log(platform: str) -> int:
    conn = get_connection()
    c    = conn.cursor()
    c.execute(
        "INSERT INTO scrape_logs (platform, started_at, status) VALUES (%s, %s, 'running') RETURNING id",
        (platform, datetime.now().isoformat()),
    )
    log_id = c.fetchone()[0]
    conn.commit()
    conn.close()
    return log_id


def finish_log(log_id: int, count_new: int, count_skipped: int, error: str = None):
    conn   = get_connection()
    status = "error" if error else "success"
    conn.cursor().execute(
        """UPDATE scrape_logs
              SET status=%s, completed_at=%s, count_new=%s, count_skipped=%s, error_message=%s
            WHERE id=%s""",
        (status, datetime.now().isoformat(), count_new, count_skipped, error, log_id),
    )
    conn.commit()
    conn.close()


def mark_stale_running_failed() -> int:
    """Mark any log still 'running' as failed — called once at startup."""
    conn = get_connection()
    c    = conn.cursor()
    c.execute(
        """UPDATE scrape_logs
              SET status='error',
                  completed_at=%s,
                  error_message=COALESCE(NULLIF(error_message, ''),
                                         'Interrupted — marked failed on restart')
            WHERE status='running'""",
        (datetime.now().isoformat(),),
    )
    n = c.rowcount
    conn.commit()
    conn.close()
    return n


def get_logs(limit: int = 60) -> list:
    conn = get_connection()
    c    = dict_cursor(conn)
    c.execute("SELECT * FROM scrape_logs ORDER BY id DESC LIMIT %s", (limit,))
    rows = [dict(r) for r in c.fetchall()]
    conn.close()
    return rows


# ── Settings ──────────────────────────────────────────────────────────────────

def get_setting(key: str, default=None):
    conn = get_connection()
    c    = conn.cursor()
    c.execute("SELECT value FROM settings WHERE key=%s", (key,))
    row = c.fetchone()
    conn.close()
    return row[0] if row else default


def save_setting(key: str, value):
    conn = get_connection()
    conn.cursor().execute(
        "INSERT INTO settings (key, value) VALUES (%s, %s) ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value",
        (key, str(value)),
    )
    conn.commit()
    conn.close()


# ── Instagram queue ───────────────────────────────────────────────────────────

def queue_ig_profiles(profiles: list) -> int:
    conn  = get_connection()
    c     = conn.cursor()
    added = 0
    now   = datetime.now().isoformat()
    for p in profiles:
        c.execute(
            "INSERT INTO instagram_queue (username, profile_url, discovered_at) VALUES (%s, %s, %s) ON CONFLICT (username) DO NOTHING",
            (p.get("username", ""), p.get("profile_url", ""), now),
        )
        if c.rowcount:
            added += 1
    conn.commit()
    conn.close()
    return added


def get_ig_queue(only_unscraped: bool = True) -> list:
    conn = get_connection()
    c    = dict_cursor(conn)
    if only_unscraped:
        c.execute("SELECT * FROM instagram_queue WHERE scraped = 0 ORDER BY id")
    else:
        c.execute("SELECT * FROM instagram_queue ORDER BY id DESC")
    rows = [dict(r) for r in c.fetchall()]
    conn.close()
    return rows


def mark_ig_scraped(usernames: list):
    if not usernames:
        return
    conn = get_connection()
    c    = conn.cursor()
    c.executemany("UPDATE instagram_queue SET scraped = 1 WHERE username = %s", [(u,) for u in usernames])
    conn.commit()
    conn.close()


def get_ig_queue_stats() -> dict:
    conn = get_connection()
    c    = conn.cursor()
    c.execute("SELECT COUNT(*) FROM instagram_queue")
    total = c.fetchone()[0]
    c.execute("SELECT COUNT(*) FROM instagram_queue WHERE scraped = 0")
    pending = c.fetchone()[0]
    conn.close()
    return {"total": total, "pending": pending, "scraped": total - pending}


def clear_ig_queue():
    conn = get_connection()
    conn.cursor().execute("DELETE FROM instagram_queue")
    conn.commit()
    conn.close()


# ── Jiji queue ────────────────────────────────────────────────────────────────

def init_jiji_queue():
    init_db()  # tables already created in init_db


def queue_jiji_listings(listings: list) -> int:
    conn  = get_connection()
    c     = conn.cursor()
    added = 0
    now   = datetime.now().isoformat()
    for item in listings:
        c.execute(
            "INSERT INTO jiji_queue (listing_url, title, category, discovered_at) VALUES (%s, %s, %s, %s) ON CONFLICT (listing_url) DO NOTHING",
            (item.get("listing_url", ""), item.get("title", ""), item.get("category", ""), now),
        )
        if c.rowcount:
            added += 1
    conn.commit()
    conn.close()
    return added


def get_jiji_queue(only_unscraped: bool = True) -> list:
    conn = get_connection()
    c    = dict_cursor(conn)
    if only_unscraped:
        c.execute("SELECT * FROM jiji_queue WHERE scraped = 0 ORDER BY id")
    else:
        c.execute("SELECT * FROM jiji_queue ORDER BY id DESC")
    rows = [dict(r) for r in c.fetchall()]
    conn.close()
    return rows


def mark_jiji_scraped(urls: list):
    if not urls:
        return
    conn = get_connection()
    c    = conn.cursor()
    c.executemany("UPDATE jiji_queue SET scraped = 1 WHERE listing_url = %s", [(u,) for u in urls])
    conn.commit()
    conn.close()


def get_jiji_queue_stats() -> dict:
    conn = get_connection()
    c    = conn.cursor()
    c.execute("SELECT COUNT(*) FROM jiji_queue")
    total = c.fetchone()[0]
    c.execute("SELECT COUNT(*) FROM jiji_queue WHERE scraped = 0")
    pending = c.fetchone()[0]
    conn.close()
    return {"total": total, "pending": pending, "scraped": total - pending}


def clear_jiji_queue():
    conn = get_connection()
    conn.cursor().execute("DELETE FROM jiji_queue")
    conn.commit()
    conn.close()


# ── Twitter / TikTok profile-queue helpers (generic, like Instagram) ───────────

def _queue_profiles(table: str, profiles: list) -> int:
    conn  = get_connection()
    c     = conn.cursor()
    added = 0
    now   = datetime.now().isoformat()
    for p in profiles:
        c.execute(
            f"INSERT INTO {table} (username, profile_url, discovered_at) VALUES (%s, %s, %s) ON CONFLICT (username) DO NOTHING",
            (p.get("username", ""), p.get("profile_url", ""), now),
        )
        if c.rowcount:
            added += 1
    conn.commit()
    conn.close()
    return added


def _get_profile_queue(table: str, only_unscraped: bool = True) -> list:
    conn = get_connection()
    c    = dict_cursor(conn)
    if only_unscraped:
        c.execute(f"SELECT * FROM {table} WHERE scraped = 0 ORDER BY id")
    else:
        c.execute(f"SELECT * FROM {table} ORDER BY id DESC")
    rows = [dict(r) for r in c.fetchall()]
    conn.close()
    return rows


def _mark_profile_scraped(table: str, usernames: list):
    if not usernames:
        return
    conn = get_connection()
    c    = conn.cursor()
    c.executemany(f"UPDATE {table} SET scraped = 1 WHERE username = %s", [(u,) for u in usernames])
    conn.commit()
    conn.close()


def _profile_queue_stats(table: str) -> dict:
    conn = get_connection()
    c    = conn.cursor()
    c.execute(f"SELECT COUNT(*) FROM {table}")
    total = c.fetchone()[0]
    c.execute(f"SELECT COUNT(*) FROM {table} WHERE scraped = 0")
    pending = c.fetchone()[0]
    conn.close()
    return {"total": total, "pending": pending, "scraped": total - pending}


def _clear_profile_queue(table: str):
    conn = get_connection()
    conn.cursor().execute(f"DELETE FROM {table}")
    conn.commit()
    conn.close()


# Twitter/X
def queue_twitter_profiles(profiles: list) -> int: return _queue_profiles("twitter_queue", profiles)
def get_twitter_queue(only_unscraped: bool = True) -> list: return _get_profile_queue("twitter_queue", only_unscraped)
def mark_twitter_scraped(usernames: list): _mark_profile_scraped("twitter_queue", usernames)
def get_twitter_queue_stats() -> dict: return _profile_queue_stats("twitter_queue")
def clear_twitter_queue(): _clear_profile_queue("twitter_queue")

# TikTok
def queue_tiktok_profiles(profiles: list) -> int: return _queue_profiles("tiktok_queue", profiles)
def get_tiktok_queue(only_unscraped: bool = True) -> list: return _get_profile_queue("tiktok_queue", only_unscraped)
def mark_tiktok_scraped(usernames: list): _mark_profile_scraped("tiktok_queue", usernames)
def get_tiktok_queue_stats() -> dict: return _profile_queue_stats("tiktok_queue")
def clear_tiktok_queue(): _clear_profile_queue("tiktok_queue")


# ── User accounts / authentication ─────────────────────────────────────────────

def create_user(username: str, password: str) -> bool:
    username = (username or "").strip()
    if not username or not password:
        return False
    conn = get_connection()
    c    = conn.cursor()
    try:
        c.execute(
            "INSERT INTO users (username, password_hash, created_at) VALUES (%s, %s, %s) ON CONFLICT (username) DO NOTHING",
            (username, generate_password_hash(password), datetime.now().isoformat()),
        )
        created = c.rowcount > 0
        conn.commit()
        return created
    finally:
        conn.close()


def get_user_by_username(username: str):
    conn = get_connection()
    c    = dict_cursor(conn)
    c.execute("SELECT * FROM users WHERE username = %s", ((username or "").strip(),))
    row = c.fetchone()
    conn.close()
    return dict(row) if row else None


def get_user_by_id(user_id):
    conn = get_connection()
    c    = dict_cursor(conn)
    c.execute("SELECT * FROM users WHERE id = %s", (user_id,))
    row = c.fetchone()
    conn.close()
    return dict(row) if row else None


def verify_user(username: str, password: str):
    u = get_user_by_username(username)
    if u and check_password_hash(u["password_hash"], password or ""):
        return u
    return None


def user_count() -> int:
    conn = get_connection()
    c    = conn.cursor()
    c.execute("SELECT COUNT(*) FROM users")
    n = c.fetchone()[0]
    conn.close()
    return n
