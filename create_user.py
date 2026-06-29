"""
Add a login account from the command line.

    python create_user.py <username> <password>

The first account can also be created on the login page the first time you open
the app. Use this script to add more accounts later.
"""

import os
import sys

# Use the same backend the app uses (Postgres when configured, else SQLite).
if os.environ.get("DATABASE_URL") or os.environ.get("PGDATABASE") or os.environ.get("PGHOST"):
    import database_pg as db
else:
    import database as db


def main():
    if len(sys.argv) < 3:
        print("Usage: python create_user.py <username> <password>")
        return
    username, password = sys.argv[1], sys.argv[2]
    db.init_db()
    if db.create_user(username, password):
        print(f"Created login account '{username}'.")
    else:
        print(f"Could not create '{username}' — it may already exist, or the password was empty.")


if __name__ == "__main__":
    main()
