"""
Set or update the email address on a login account.

    python set_email.py <username> <email>

An email is required for the "Forgot password?" reset flow to reach that account.
Usernames are case-sensitive. Uses the active backend (Postgres when configured,
else SQLite) via the repository layer.
"""

import sys

from database import repository as db


def main():
    if len(sys.argv) < 3:
        print("Usage: python set_email.py <username> <email>")
        return
    username, email = sys.argv[1], sys.argv[2]
    db.init_db()
    if db.set_user_email(username, email):
        print(f"Email for '{username}' set to {email}.")
    else:
        print(f"No account named '{username}' found (note: usernames are case-sensitive).")


if __name__ == "__main__":
    main()
