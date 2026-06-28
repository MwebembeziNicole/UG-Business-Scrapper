# PostgreSQL setup & migration

This moves the app from the single-file SQLite database to PostgreSQL, which
supports concurrent users, larger datasets, network access, and proper user
accounts — everything needed to run the tool across an organisation.

Nothing here breaks the current app: `database.py` (SQLite) stays in place, and
`database_pg.py` is a drop-in replacement you switch to when ready.

---

## 1. Install PostgreSQL

- **Windows / one office machine:** download the installer from
  https://www.postgresql.org/download/ and install. Note the password you set
  for the `postgres` user.
- **Linux server:** `sudo apt install postgresql`.

Create the database (one time):

```sql
CREATE DATABASE uganda_businesses;
-- optional: a dedicated app account instead of the postgres superuser
CREATE USER bsa_app WITH PASSWORD 'choose-a-strong-password';
GRANT ALL PRIVILEGES ON DATABASE uganda_businesses TO bsa_app;
```

## 2. Install the Python driver

```
pip install psycopg2-binary
```

Add `psycopg2-binary` to `requirements.txt` so it installs everywhere.

## 3. Tell the app how to connect (environment variables)

Set **one** of these before running. Using environment variables keeps the
password out of the code.

Either a single URL:

```
DATABASE_URL=postgresql://bsa_app:your-password@localhost:5432/uganda_businesses
```

…or the individual parts:

```
PGHOST=localhost
PGPORT=5432
PGDATABASE=uganda_businesses
PGUSER=bsa_app
PGPASSWORD=your-password
```

On Windows you can set these in System → Environment Variables; on Linux put
them in the service file or a `.env` loaded at startup.

## 4. Migrate existing data

With Postgres running and the variables set:

```
python migrate_to_postgres.py
```

This creates the tables and copies every business, log, setting, and queue row
from `uganda_businesses.db`. It's safe to run more than once (duplicates are
skipped).

## 5. Switch the app over

In `app.py`, change the one import line:

```python
# import database as db
import database_pg as db
```

Then start the app as usual (`python run.py`). Everything else — routes,
scrapers, exports, the dashboard — works unchanged, because `database_pg.py`
exposes the same functions.

## 6. Back to SQLite (if ever needed)

Revert the import to `import database as db`. The SQLite file is untouched.

---

## Notes for the organisation rollout

- **Backups:** schedule `pg_dump uganda_businesses > backup.sql` (e.g. daily).
- **Access:** create one PostgreSQL user per purpose; don't share the superuser.
- **Next step — investigator login:** a `users` table and a Flask-Login sign-in
  page sit naturally on top of this. That's the recommended follow-up before
  multiple investigators use it on a shared server.
- **Scheduler caution:** if you later run under gunicorn with multiple workers,
  run the APScheduler job in only one worker (or a separate process) so the
  daily collection doesn't fire multiple times.
