# PostgreSQL — install, prepare & migrate (Windows)

This moves the app from the single-file SQLite database to PostgreSQL: concurrent
users, larger datasets, network access, and a proper place for the login accounts.

Nothing here breaks the current app. `database.py` (SQLite) stays in place;
`database_pg.py` is a drop-in replacement you switch to when ready. Your data —
**including the login accounts** — migrates across.

---

## 1. Install PostgreSQL on Windows

1. Download the installer: https://www.postgresql.org/download/windows/ (EDB installer).
2. Run it. Accept defaults, and when asked:
   - set a password for the **postgres** superuser — **write it down**;
   - keep port **5432**;
   - you can untick "Stack Builder" at the end.
3. This also installs **pgAdmin** (a graphical admin tool) and **psql** (command line).

## 2. Create the database

Open **pgAdmin** (or the "SQL Shell (psql)" from the Start menu) and run:

```sql
CREATE DATABASE uganda_businesses;
-- a dedicated app account (recommended instead of the postgres superuser):
CREATE USER bsa_app WITH PASSWORD 'choose-a-strong-password';
GRANT ALL PRIVILEGES ON DATABASE uganda_businesses TO bsa_app;
```

## 3. Install the Python packages

In the project folder:

```
pip install psycopg2-binary flask-login
```

(`flask-login` is also needed for the new sign-in; it's in `requirements.txt`.)

## 4. Tell the app how to connect (environment variables)

Set these so the password isn't in the code. On Windows you can set them in
**System → Advanced → Environment Variables**, or temporarily in the terminal
before running:

```
set DATABASE_URL=postgresql://bsa_app:choose-a-strong-password@localhost:5432/uganda_businesses
```

(Or set `PGHOST` / `PGPORT` / `PGDATABASE` / `PGUSER` / `PGPASSWORD` individually.)

## 5. Migrate your existing data

With PostgreSQL running and the variables set, from the project folder:

```
python migrate_to_postgres.py
```

This creates all tables in Postgres and copies every business, log, setting,
queue row **and login account** from `uganda_businesses.db`. Safe to re-run.

## 6. Switch the app to PostgreSQL

In `app.py`, change the one import line:

```python
# import database as db
import database_pg as db
```

Then start the app normally (`python run.py`). Everything else — routes, scrapers,
exports, the dashboard, and login — works unchanged, because `database_pg.py`
exposes the same functions.

## 7. Revert to SQLite (if ever needed)

Change the import back to `import database as db`. The SQLite file is untouched.

---

## Notes for the organisation rollout

- **Login accounts:** the `users` table migrates too, so existing sign-ins keep
  working after the switch. Add more accounts any time with
  `python create_user.py <username> <password>`.
- **Session secret:** set a fixed `FLASK_SECRET_KEY` environment variable on the
  server so logins survive restarts (otherwise one is generated and stored in the
  DB automatically).
- **Backups:** schedule `pg_dump uganda_businesses > backup.sql` (e.g. daily).
- **Access:** use one PostgreSQL account per purpose; don't share the superuser.
- **Scheduler:** if you later run under gunicorn with multiple workers, run the
  APScheduler job in only one worker so the daily collection doesn't fire twice.
- **SSO later:** login is self-managed for now but isolated in `app.py`'s `login`
  route + the `users` table, so Org Active Directory / SSO can replace it later
  without touching the rest of the app.
