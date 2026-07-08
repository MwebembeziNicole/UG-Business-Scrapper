# Deploying to Railway

The app already ships with a `Dockerfile` (Python + Google Chrome, for Selenium/
undetected-chromedriver) and a `railway.json`, so Railway can build and run it
without extra buildpack configuration. This doc covers the parts Railway needs
that aren't in the code: persistent storage, environment variables, and a couple
of platform-specific gotchas.

---

## 1. Create the service

1. New Project → Deploy from GitHub repo (push this repo first if you haven't).
2. Railway detects the `Dockerfile` and uses it as the build method automatically
   (confirmed by `railway.json`'s `"builder": "DOCKERFILE"`).
3. Once deployed, Settings → Networking → **Generate Domain** to get a public URL.

## 2. Attach a volume (required)

Without a volume, everything written inside the container — the SQLite file,
`exports/`, and the authenticated `browser_profiles/` Chrome profiles — is wiped
on every redeploy. Attach one:

1. Service → **Volumes** → New Volume.
2. Mount path: `/data`.
3. Set these environment variables (Service → Variables) so the app writes into
   the volume instead of the container's ephemeral disk:

```
SQLITE_DB_PATH=/data/uganda_businesses.db
EXPORT_DIR=/data/exports
DAILY_EXPORT_DIR=/data/exports/daily
BROWSER_PROFILE_DIR=/data/browser_profiles
```

This mirrors the `[[mounts]]` block already in `fly.toml` for the Fly deployment
— same idea, different platform.

If you'd rather move off SQLite entirely, add a Railway Postgres plugin (New →
Database → PostgreSQL) — it injects `DATABASE_URL` automatically, and
`config.py`'s `DB_ENGINE=auto` picks it up with no code change. You'd still want
the volume for `browser_profiles/` and `exports/`, since those aren't database
rows.

## 3. Environment variables to set

At minimum:

```
FLASK_SECRET_KEY=<generate a random 32+ char string>
FIRECRAWL_API_KEY=<your key, if using Firecrawl-backed scrapers>
APP_BASE_URL=https://<your-railway-domain>
```

`HOST`/`PORT` do not need to be set — Railway injects `PORT` at runtime and the
Dockerfile's `CMD` now binds to `$PORT` (falls back to 8080 locally).

SMTP variables (`SMTP_HOST`, `SMTP_USER`, `SMTP_PASSWORD`, etc.) are only needed
if the "Forgot password" email flow should work in production.

## 4. Resource sizing

Chrome under Selenium needs headroom — the existing Fly config uses 2GB RAM.
Set the Railway service's memory limit similarly (Settings → Resources); 512MB–1GB
will likely OOM during a Selenium-driven scrape.

## 5. Single instance only

`railway.json` sets `numReplicas: 1`. Do not scale this service horizontally:
APScheduler's daily job and the in-memory `scrape_status` dict are process-local,
so a second instance would duplicate scheduled runs and split state. This is the
same constraint noted in the Dockerfile for gunicorn's worker count (`--workers 1`).

## 6. Logging in to social platforms after deploy

Instagram/Jiji/Twitter/TikTok scraping relies on already-authenticated Chrome
profiles under `browser_profiles/`. Selenium in the container runs headless (no
visible window on a server), so the initial interactive login — solving 2FA/CAPTCHA
by hand — still needs to happen the way it does locally: either run the login
step from a machine with a display and copy the resulting profile folder into the
Railway volume, or use the app's own `/api/login/<platform>` flow if it supports
remote/headful login through the dashboard (check `login.py` for the current
mechanism before relying on this).

## 7. Health checks

`GET /healthz` returns `{"status": "ok"}` without requiring login, and is wired
up in `railway.json` as the deploy health check.
