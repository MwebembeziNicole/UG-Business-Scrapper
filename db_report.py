"""
Diagnostic: show which database is active and list the accounts in BOTH the
active database and the local SQLite file, so we can see exactly where each
login account lives.

    python db_report.py
"""

import os
import sqlite3

import config
from database.connection import DATABASE_ENGINE
from database import repository as db


def main():
    print("ACTIVE ENGINE :", DATABASE_ENGINE)
    print("DB_NAME       :", config.DB_NAME)
    print("DB_HOST/PORT  :", config.DB_HOST, config.DB_PORT)
    print("-" * 55)

    # Accounts in the active database (the one the app uses)
    try:
        conn = db.get_connection()
        cur = conn.cursor()
        cur.execute("SELECT id, username, email FROM users ORDER BY id")
        rows = cur.fetchall()
        conn.close()
        print(f"ACTIVE DB ({DATABASE_ENGINE}) users:")
        for r in rows:
            print("   ", tuple(r))
        if not rows:
            print("    (none)")
    except Exception as e:
        print("ACTIVE DB read error:", e)

    print("-" * 55)

    # Accounts in the local SQLite file, regardless of active engine
    path = config.SQLITE_DB_PATH
    print("SQLite file   :", path)
    if os.path.exists(path):
        try:
            sc = sqlite3.connect(path)
            sc.row_factory = sqlite3.Row
            rows = sc.execute("SELECT id, username, email FROM users ORDER BY id").fetchall()
            sc.close()
            print("SQLite file users:")
            for r in rows:
                print("   ", (r["id"], r["username"], r["email"]))
            if not rows:
                print("    (none)")
        except Exception as e:
            print("SQLite read error:", e)
    else:
        print("    SQLite file does not exist.")


if __name__ == "__main__":
    main()
