"""
Create the PostgreSQL database the app expects, if it doesn't already exist.

    python create_db.py

Reuses the same connection settings as the app (config.py / your PG* env vars),
so it talks to the same server with the same credentials. It connects to the
built-in 'postgres' maintenance database and issues CREATE DATABASE — which
cannot run inside a transaction, hence autocommit. Safe to re-run.
"""

import config
import psycopg2
from psycopg2 import sql

target = config.DB_NAME

conn = psycopg2.connect(
    host=config.DB_HOST,
    port=config.DB_PORT,
    user=config.DB_USER,
    password=config.DB_PASSWORD,
    dbname="postgres",          # maintenance DB — always present
)
conn.autocommit = True          # CREATE DATABASE can't run in a transaction
cur = conn.cursor()

cur.execute("SELECT 1 FROM pg_database WHERE datname = %s", (target,))
if cur.fetchone():
    print(f"Database '{target}' already exists — nothing to do.")
else:
    cur.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(target)))
    print(f"Created database '{target}'.")

cur.close()
conn.close()
