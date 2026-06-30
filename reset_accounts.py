"""
Delete ALL login accounts (and any pending password-reset tokens) from the
ACTIVE database, so you can start fresh and register a new account in the app.

    python reset_accounts.py          # shows what it will do, does nothing
    python reset_accounts.py --yes    # actually clears the accounts

The active database is whatever the app uses (Postgres when configured, else
SQLite) — confirm the engine printed below is the one you intend before using
--yes.
"""

import sys

from database import repository as db
from database.connection import DATABASE_ENGINE


def main():
    db.init_db()
    n = db.user_count()
    print(f"Active engine : {DATABASE_ENGINE}")
    print(f"Accounts now  : {n}")

    if "--yes" not in sys.argv:
        print("\nThis will DELETE ALL accounts in the database above.")
        print("If that's the right database, re-run to confirm:")
        print("    python reset_accounts.py --yes")
        return

    conn = db.get_connection()
    cur = conn.cursor()
    for table in ("password_reset_tokens", "users"):
        try:
            cur.execute(f"DELETE FROM {table}")
        except Exception as e:
            print(f"  (skipped {table}: {e})")
    conn.commit()
    conn.close()
    print(f"\nDone — all accounts cleared from the {DATABASE_ENGINE} database.")
    print("Restart the app (python run.py) and click Register to create your account.")


if __name__ == "__main__":
    main()
