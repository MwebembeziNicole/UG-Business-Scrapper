"""
Delete a login account.

    python delete_user.py <username>

Username is case-sensitive. Uses the active backend (Postgres when configured,
else SQLite) via the repository layer, so it deletes from the same database the
app reads. It refuses to delete the last remaining account so you can't lock
yourself out.
"""

import sys

from database import repository as db
from database.connection import DATABASE_ENGINE


def main():
    if len(sys.argv) < 2:
        print("Usage: python delete_user.py <username>")
        return

    username = sys.argv[1]
    u = db.get_user_by_username(username)
    if not u:
        print(f"No account named '{username}' found (note: usernames are case-sensitive).")
        return

    if db.user_count() <= 1:
        print(f"'{username}' is the only account — refusing to delete it so you "
              f"aren't locked out. Create another account first (python create_user.py ...).")
        return

    placeholder = "%s" if DATABASE_ENGINE == "postgres" else "?"
    conn = db.get_connection()
    cur = conn.cursor()
    cur.execute(f"DELETE FROM users WHERE id = {placeholder}", (u["id"],))
    conn.commit()
    conn.close()
    print(f"Deleted account '{username}' (id={u['id']}). Remaining accounts: {db.user_count()}")


if __name__ == "__main__":
    main()
