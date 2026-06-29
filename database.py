import sqlite3
import os
from datetime import datetime
from werkzeug.security import generate_password_hash, check_password_hash

DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "uganda_businesses.db")
PLATFORMS = ["jiji", "instagram", "yellowpages", "twitter", "tiktok"]


def get_connection():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    return conn


def init_db():
    conn = get_connection()
    c = conn.cursor()

    for platform in PLATFORMS:
        c.execute(f"""
            CREATE TABLE IF NOT EXISTS {platform}_businesses (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                business_name TEXT,
                username    TEXT,
                category    TEXT,
                phone       TEXT,
                email       TEXT,
                website     TEXT,
                facebook    TEXT,
                location    TEXT,
                source_url  TEXT,
                scraped_at  TEXT NOT NULL
            )
        """)
        # Migrate older tables that predate the email/website/facebook columns
        for col in ("email", "website", "facebook"):
            try:
                c.execute(f"ALTER TABLE {platform}_businesses ADD COLUMN {col} TEXT")
            except sqlite3.OperationalError:
                pass  # column already exists
        c.execute(f"""
            CREATE UNIQUE INDEX IF NOT EXISTS ux_{platform}_phone
            ON {platform}_businesses(phone)
            WHERE phone IS NOT NULL AND phone != ''
        """)
        c.execute(f"""
            CREATE UNIQUE INDEX IF NOT EXISTS ux_{platform}_username
            ON {platform}_businesses(username)
            WHERE username IS NOT NULL AND username != ''
        """)
        c.execute(f"""
            CREATE UNIQUE INDEX IF NOT EXISTS ux_{platform}_email
            ON {platform}_businesses(email)
            WHERE email IS NOT NULL AND email != ''
        """)

    c.execute("""
        CREATE TABLE IF NOT EXISTS scrape_logs (
            id            INTEGER PRIMARY KEY AUTOINCREMENT,
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
            id            INTEGER PRIMARY KEY AUTOINCREMENT,
            username      TEXT NOT NULL UNIQUE,
            password_hash TEXT NOT NULL,
            created_at    TEXT NOT NULL
        )
    """)

    # Instagram profile discovery queue
    c.execute("""
        CREATE TABLE IF NOT EXISTS instagram_queue (
            id            INTEGER PRIMARY KEY AUTOINCREMENT,
            username      TEXT    NOT NULL UNIQUE,
            profile_url   TEXT    NOT NULL,
            discovered_at TEXT    NOT NULL,
            scraped       INTEGER NOT NULL DEFAULT 0
        )
    """)

    # Jiji listing discovery queue
    c.execute("""
        CREATE TABLE IF NOT EXISTS jiji_queue (
            id            INTEGER PRIMARY KEY AUTOINCREMENT,
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
                id            INTEGER PRIMARY KEY AUTOINCREMENT,
                username      TEXT    NOT NULL UNIQUE,
                profile_url   TEXT    NOT NULL,
                discovered_at TEXT    NOT NULL,
                scraped       INTEGER NOT NULL DEFAULT 0
            )
        """)

    c.execute("INSERT OR IGNORE INTO settings (key, value) VALUES ('firecrawl_api_key', 'fc-7a5a845f96e545f5b7a10a0b3b09a7d3')")
    c.execute("INSERT OR IGNORE INTO settings (key, value) VALUES ('daily_limit', '40')")
    c.execute("INSERT OR IGNORE INTO settings (key, value) VALUES ('schedule_hour', '8')")
    c.execute("INSERT OR IGNORE INTO settings (key, value) VALUES ('schedule_minute', '0')")
    c.execute("INSERT OR IGNORE INTO settings (key, value) VALUES ('automation_enabled', '1')")
    c.execute("INSERT OR IGNORE INTO settings (key, value) VALUES ('disabled_platforms', '')")

    conn.commit()
    conn.close()


def insert_business(platform: str, business: dict) -> bool:
    if platform not in PLATFORMS:
        return False

    phone      = (business.get("phone") or "").strip()
    username   = (business.get("username") or "").strip()
    email      = (business.get("email") or "").strip()
    website    = (business.get("website") or "").strip()
    facebook   = (business.get("facebook") or "").strip()
    source_url = (business.get("source_url") or "").strip()

    # Need at least one identifying/contact field. For directory sites like
    # Yellow Pages (no phone/username, often no email) the listing's source_url
    # is the stable identifier, so accept it too.
    if not (phone or username or email or source_url):
        return False

    conn = get_connection()
    c    = conn.cursor()
    try:
        if phone:
            c.execute(f"SELECT 1 FROM {platform}_businesses WHERE phone = ?", (phone,))
            if c.fetchone():
                return False
        if username:
            c.execute(f"SELECT 1 FROM {platform}_businesses WHERE username = ?", (username,))
            if c.fetchone():
                return False
        if email:
            c.execute(f"SELECT 1 FROM {platform}_businesses WHERE email = ?", (email,))
            if c.fetchone():
                return False
        if source_url:
            c.execute(f"SELECT 1 FROM {platform}_businesses WHERE source_url = ?", (source_url,))
            if c.fetchone():
                return False

        c.execute(f"""
            INSERT INTO {platform}_businesses
                (business_name, username, category, phone, email, website, facebook, location, source_url, scraped_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            (business.get("business_name") or "").strip(),
            username,
            (business.get("category") or "").strip(),
            phone,
            email,
            website,
            facebook,
            (business.get("location") or "").strip(),
            source_url,
            datetime.now().isoformat(),
        ))
        conn.commit()
        return True

    except sqlite3.IntegrityError:
        return False
    finally:
        conn.close()


def get_businesses(platform: str = None, limit: int = 200, offset: int = 0, search: str = None) -> list:
    conn    = get_connection()
    c       = conn.cursor()
    results = []
    targets = [platform] if platform else PLATFORMS

    for p in targets:
        base   = f"SELECT *, '{p}' AS platform FROM {p}_businesses"
        params = []
        if search:
            base  += " WHERE business_name LIKE ? OR phone LIKE ? OR email LIKE ? OR location LIKE ? OR username LIKE ?"
            params = [f"%{search}%"] * 5
        base  += " ORDER BY scraped_at DESC LIMIT ? OFFSET ?"
        params += [limit, offset]
        c.execute(base, params)
        results.extend([dict(r) for r in c.fetchall()])

    conn.close()
    return results


def delete_business(platform: str, record_id: int) -> bool:
    if platform not in PLATFORMS:
        return False
    conn = get_connection()
    conn.execute(f"DELETE FROM {platform}_businesses WHERE id = ?", (record_id,))
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
        c.execute(f"SELECT COUNT(*) FROM {p}_businesses WHERE scraped_at LIKE ?", (f"{today}%",))
        today_count = c.fetchone()[0]
        stats[p] = {"total": total, "today": today_count}
    conn.close()
    return stats


def start_log(platform: str) -> int:
    conn = get_connection()
    c    = conn.cursor()
    c.execute(
        "INSERT INTO scrape_logs (platform, started_at, status) VALUES (?, ?, 'running')",
        (platform, datetime.now().isoformat()),
    )
    log_id = c.lastrowid
    conn.commit()
    conn.close()
    return log_id


def finish_log(log_id: int, count_new: int, count_skipped: int, error: str = None):
    conn   = get_connection()
    status = "error" if error else "success"
    conn.execute(
        """UPDATE scrape_logs
              SET status=?, completed_at=?, count_new=?, count_skipped=?, error_message=?
            WHERE id=?""",
        (status, datetime.now().isoformat(), count_new, count_skipped, error, log_id),
    )
    conn.commit()
    conn.close()


def mark_stale_running_failed() -> int:
    """Mark any log still in 'running' state as failed.

    Called once at startup: a fresh process is never mid-scrape, so any leftover
    'running' rows are interrupted runs (app closed/crashed mid-collection) and
    should be closed out as failed rather than lingering forever.
    """
    conn = get_connection()
    c    = conn.cursor()
    c.execute(
        """UPDATE scrape_logs
              SET status='error',
                  completed_at=?,
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
    c    = conn.cursor()
    c.execute("SELECT * FROM scrape_logs ORDER BY id DESC LIMIT ?", (limit,))
    rows = [dict(r) for r in c.fetchall()]
    conn.close()
    return rows


def get_setting(key: str, default=None):
    conn = get_connection()
    c    = conn.cursor()
    c.execute("SELECT value FROM settings WHERE key=?", (key,))
    row = c.fetchone()
    conn.close()
    return row[0] if row else default


def save_setting(key: str, value):
    conn = get_connection()
    conn.execute("INSERT OR REPLACE INTO settings (key, value) VALUES (?,?)", (key, str(value)))
    conn.commit()
    conn.close()


# ── Instagram queue helpers ────────────────────────────────────────────────────

def queue_ig_profiles(profiles: list) -> int:
    conn  = get_connection()
    c     = conn.cursor()
    added = 0
    now   = datetime.now().isoformat()
    for p in profiles:
        try:
            c.execute(
                "INSERT OR IGNORE INTO instagram_queue (username, profile_url, discovered_at) VALUES (?,?,?)",
                (p.get('username', ''), p.get('profile_url', ''), now),
            )
            if c.rowcount:
                added += 1
        except Exception:
            pass
    conn.commit()
    conn.close()
    return added


def get_ig_queue(only_unscraped: bool = True) -> list:
    conn = get_connection()
    c    = conn.cursor()
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
    conn.executemany(
        "UPDATE instagram_queue SET scraped = 1 WHERE username = ?",
        [(u,) for u in usernames],
    )
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
    return {'total': total, 'pending': pending, 'scraped': total - pending}


def clear_ig_queue():
    conn = get_connection()
    conn.execute("DELETE FROM instagram_queue")
    conn.commit()
    conn.close()


# ── Jiji queue helpers ─────────────────────────────────────────────────────────

def init_jiji_queue():
    conn = get_connection()
    conn.execute("""
        CREATE TABLE IF NOT EXISTS jiji_queue (
            id            INTEGER PRIMARY KEY AUTOINCREMENT,
            listing_url   TEXT    NOT NULL UNIQUE,
            title         TEXT,
            category      TEXT,
            discovered_at TEXT    NOT NULL,
            scraped       INTEGER NOT NULL DEFAULT 0
        )
    """)
    conn.commit()
    conn.close()


def queue_jiji_listings(listings: list) -> int:
    conn  = get_connection()
    c     = conn.cursor()
    added = 0
    now   = datetime.now().isoformat()
    for item in listings:
        try:
            c.execute(
                "INSERT OR IGNORE INTO jiji_queue (listing_url, title, category, discovered_at) VALUES (?,?,?,?)",
                (item.get('listing_url', ''), item.get('title', ''), item.get('category', ''), now),
            )
            if c.rowcount:
                added += 1
        except Exception:
            pass
    conn.commit()
    conn.close()
    return added


def get_jiji_queue(only_unscraped: bool = True) -> list:
    conn = get_connection()
    c    = conn.cursor()
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
    conn.executemany(
        "UPDATE jiji_queue SET scraped = 1 WHERE listing_url = ?",
        [(u,) for u in urls],
    )
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
    return {'total': total, 'pending': pending, 'scraped': total - pending}


def clear_jiji_queue():
    conn = get_connection()
    conn.execute("DELETE FROM jiji_queue")
    conn.commit()
    conn.close()


# ── Twitter / TikTok profile-queue helpers (generic, like Instagram) ───────────

def _queue_profiles(table: str, profiles: list) -> int:
    conn  = get_connection()
    c     = conn.cursor()
    added = 0
    now   = datetime.now().isoformat()
    for p in profiles:
        try:
            c.execute(
                f"INSERT OR IGNORE INTO {table} (username, profile_url, discovered_at) VALUES (?,?,?)",
                (p.get("username", ""), p.get("profile_url", ""), now),
            )
            if c.rowcount:
                added += 1
        except Exception:
            pass
    conn.commit()
    conn.close()
    return added


def _get_profile_queue(table: str, only_unscraped: bool = True) -> list:
    conn = get_connection()
    c    = conn.cursor()
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
    conn.executemany(f"UPDATE {table} SET scraped = 1 WHERE username = ?", [(u,) for u in usernames])
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
    conn.execute(f"DELETE FROM {table}")
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
    """Create a login account with a hashed password. False if username taken."""
    username = (username or "").strip()
    if not username or not password:
        return False
    conn = get_connection()
    try:
        conn.execute(
            "INSERT INTO users (username, password_hash, created_at) VALUES (?, ?, ?)",
            (username, generate_password_hash(password), datetime.now().isoformat()),
        )
        conn.commit()
        return True
    except sqlite3.IntegrityError:
        return False
    finally:
        conn.close()


def get_user_by_username(username: str):
    conn = get_connection()
    c    = conn.cursor()
    c.execute("SELECT * FROM users WHERE username = ?", ((username or "").strip(),))
    row = c.fetchone()
    conn.close()
    return dict(row) if row else None


def get_user_by_id(user_id):
    conn = get_connection()
    c    = conn.cursor()
    c.execute("SELECT * FROM users WHERE id = ?", (user_id,))
    row = c.fetchone()
    conn.close()
    return dict(row) if row else None


def verify_user(username: str, password: str):
    """Return the user dict if username + password are correct, else None."""
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
