# Running the Business Scraping Agent on a Mac

This sets the app up on a MacBook using **SQLite** — no database server to
install. The same project also runs on the Windows/PostgreSQL machine unchanged;
it picks the database automatically (SQLite here, Postgres only if PG env vars
are set).

Estimated time: ~15 minutes.

---

## 1. Install the two prerequisites (on the Mac)

**Google Chrome** — the scrapers drive a real Chrome window.
Download from https://www.google.com/chrome and install it.

**Python 3** — check if it's already there. Open **Terminal**
(press ⌘+Space, type "Terminal", Enter) and run:

```
python3 --version
```

If it prints `Python 3.10` or higher, you're set. If "command not found",
install Python from https://www.python.org/downloads/macos/ (the latest 3.x),
then re-open Terminal and check again.

## 2. Copy the project onto the Mac

Put the whole `uganda_scraper` folder on the Mac (USB drive, AirDrop, or cloud).

**Before copying (or delete these on the Mac after):** don't carry over these —
they're machine-specific and will be recreated:

- `browser_profiles/`  (login sessions — the Mac makes its own; you'll sign in again)
- `__pycache__/`  folders
- any `venv/` folder

Keep `uganda_businesses.db` **if you want the existing collected businesses to come
along**. Delete it for a fresh, empty start (the app recreates it).

## 3. Install the Python packages

In Terminal, go into the folder (drag the folder onto the Terminal window to get
its path, or type `cd ` then paste the path), then:

```
cd /path/to/uganda_scraper
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

The `venv` lines create an isolated environment so nothing clashes with the Mac's
system Python. You'll see `(venv)` at the start of the prompt when it's active.

## 4. Run the app

```
python3 run.py
```

It starts on **http://127.0.0.1:5050** and opens the browser automatically.
(Next time, just `cd` into the folder, run `source venv/bin/activate`, then
`python3 run.py`.)

## 5. Create the login account

The first screen is **"Create the first account"** — choose a username and
password. That becomes the sign-in for the app. (Add more accounts later with
`python3 create_user.py <username> <password>`.)

## 6. Sign in to the platforms (for phone numbers)

On the dashboard, the yellow bar has **Sign in to Jiji / Instagram / Twitter / X /
TikTok**. Click each one once — a Chrome window opens, log in, click "I've logged
in". The session is saved on this Mac for future collections. (These are separate
from the app login in step 5.)

Then **Run Collection** (or per-platform **Run**) and **Export Excel** work as on
Windows.

---

## Good to know

- **Database:** this Mac uses the local SQLite file automatically — no Postgres
  needed. (Postgres is only for the central server later.)
- **Apple Silicon (M1/M2/M3):** works — just make sure Google Chrome is installed.
  The driver auto-installs the right version on first run.
- **Daily auto-collection:** runs only while the app is open. For a laptop that
  isn't always on, use the **Run** buttons when needed, or turn off "Automatic
  daily collection" in Settings.
- **First run may take a minute** as Chrome/driver initialise — that's normal.
