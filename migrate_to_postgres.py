"""
One-time migration: copy everything from the SQLite file (uganda_businesses.db)
into PostgreSQL.

Usage (after Postgres is running and env vars / DATABASE_URL are set):

    pip install psycopg2-binary
    python migrate_to_postgres.py

Safe to re-run: businesses are inserted through database_pg.insert_business(),
which skips duplicates; settings are upserted; logs/queue rows are de-duplicated
on natural keys.
"""

import os
import sqlite3

import config
import database_pg as pg

SQLITE_PATH = config.SQLITE_DB_PATH


def _sqlite():
    conn = sqlite3.connect(SQLITE_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def _table_exists(scur, name) -> bool:
    scur.execute("SELECT name FROM sqlite_master WHERE type='table' AND name=?", (name,))
    return scur.fetchone() is not None


def migrate_businesses(s, pcur):
    total_new = 0
    for platform in pg.PLATFORMS:
        table = f"{platform}_businesses"
        sc = s.cursor()
        if not _table_exists(sc, table):
            continue
        rows = sc.execute(f"SELECT * FROM {table}").fetchall()
        new = 0
        for r in rows:
            rec = dict(r)
            # insert_business applies the same de-dup rules as the live app
            if pg.insert_business(platform, rec):
                new += 1
        print(f"  {table:24}  {new:>5} inserted / {len(rows)} read")
        total_new += new
    return total_new


def migrate_settings(s, pcur):
    sc = s.cursor()
    if not _table_exists(sc, "settings"):
        return 0
    rows = sc.execute("SELECT key, value FROM settings").fetchall()
    for r in rows:
        pg.save_setting(r["key"], r["value"])
    print(f"  settings                 {len(rows):>5} upserted")
    return len(rows)


def migrate_logs(s, conn, pcur):
    sc = s.cursor()
    if not _table_exists(sc, "scrape_logs"):
        return 0
    rows = sc.execute("SELECT * FROM scrape_logs ORDER BY id").fetchall()
    for r in rows:
        d = dict(r)
        pcur.execute(
            """INSERT INTO scrape_logs
                 (platform, started_at, completed_at, status, count_new, count_skipped, error_message)
               VALUES (%s, %s, %s, %s, %s, %s, %s)""",
            (d.get("platform"), d.get("started_at"), d.get("completed_at"),
             d.get("status"), d.get("count_new") or 0, d.get("count_skipped") or 0,
             d.get("error_message")),
        )
    conn.commit()
    print(f"  scrape_logs              {len(rows):>5} copied")
    return len(rows)


def migrate_queue(s, conn, pcur, table, conflict_col):
    sc = s.cursor()
    if not _table_exists(sc, table):
        return 0
    rows = sc.execute(f"SELECT * FROM {table}").fetchall()
    cols = rows[0].keys() if rows else []
    n = 0
    for r in rows:
        d = dict(r)
        if table == "jiji_queue":
            pcur.execute(
                """INSERT INTO jiji_queue (listing_url, title, category, discovered_at, scraped)
                   VALUES (%s, %s, %s, %s, %s) ON CONFLICT (listing_url) DO NOTHING""",
                (d.get("listing_url"), d.get("title"), d.get("category"),
                 d.get("discovered_at"), d.get("scraped") or 0),
            )
        else:  # instagram_queue
            pcur.execute(
                """INSERT INTO instagram_queue (username, profile_url, discovered_at, scraped)
                   VALUES (%s, %s, %s, %s) ON CONFLICT (username) DO NOTHING""",
                (d.get("username"), d.get("profile_url"),
                 d.get("discovered_at"), d.get("scraped") or 0),
            )
        n += pcur.rowcount
    conn.commit()
    print(f"  {table:24}  {n:>5} copied")
    return n


def migrate_users(s, conn, pcur):
    sc = s.cursor()
    if not _table_exists(sc, "users"):
        return 0
    rows = sc.execute("SELECT username, password_hash, created_at FROM users").fetchall()
    for r in rows:
        d = dict(r)
        pcur.execute(
            """INSERT INTO users (username, password_hash, created_at)
               VALUES (%s, %s, %s) ON CONFLICT (username) DO NOTHING""",
            (d.get("username"), d.get("password_hash"), d.get("created_at")),
        )
    conn.commit()
    print(f"  users                    {len(rows):>5} copied")
    return len(rows)


def main():
    if not os.path.exists(SQLITE_PATH):
        print(f"SQLite file not found: {SQLITE_PATH}")
        return

    print("Creating PostgreSQL schema ...")
    pg.init_db()

    s    = _sqlite()
    conn = pg.get_connection()
    pcur = conn.cursor()

    print("Migrating data ...")
    migrate_businesses(s, pcur)
    migrate_settings(s, pcur)
    migrate_users(s, conn, pcur)
    migrate_logs(s, conn, pcur)
    migrate_queue(s, conn, pcur, "jiji_queue", "listing_url")
    migrate_queue(s, conn, pcur, "instagram_queue", "username")

    conn.close()
    s.close()
    print("\nMigration complete. Switch app.py to `import database_pg as db` to go live.")


if __name__ == "__main__":
    main()
