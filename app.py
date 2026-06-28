"""
Uganda Business Scraper — Flask API + APScheduler
Run with: python run.py
"""

import os
import time
import threading
from datetime import datetime
import secrets
from flask import Flask, jsonify, request, send_file, render_template, redirect, url_for
from flask_cors import CORS
from flask_login import LoginManager, UserMixin, login_user, logout_user, current_user
from apscheduler.schedulers.background import BackgroundScheduler

# Database backend chosen automatically:
#   • PostgreSQL when configured (DATABASE_URL or PG* env vars are set) — your Windows box
#   • plain SQLite file otherwise — e.g. a colleague's Mac, no DB server needed
# Same code runs on both with no edits.
if os.environ.get("DATABASE_URL") or os.environ.get("PGDATABASE") or os.environ.get("PGHOST"):
    import database_pg as db
else:
    import database as db
import exporter

# Import scrapers (live platforms: Jiji, Instagram, Yellow Pages)
from scrapers.jiji        import scrape_jiji, discover_jiji, scrape_jiji_listings
from scrapers.instagram   import scrape_instagram, discover_instagram, scrape_instagram_profiles
from scrapers.yellowpages import scrape_yellowpages
from scrapers.twitter     import scrape_twitter, discover_twitter, scrape_twitter_profiles
from scrapers.tiktok      import scrape_tiktok,  discover_tiktok,  scrape_tiktok_profiles

# ─── App setup ────────────────────────────────────────────────────────────────

app       = Flask(__name__, template_folder="templates")
CORS(app)
scheduler = BackgroundScheduler(timezone="Africa/Kampala")

# ─── Authentication (Flask-Login; single login type, SSO-ready later) ──────────

login_manager = LoginManager()
login_manager.init_app(app)
login_manager.login_view = "login"


class User(UserMixin):
    def __init__(self, id, username):
        self.id       = str(id)
        self.username = username


@login_manager.user_loader
def load_user(user_id):
    row = db.get_user_by_id(user_id)
    return User(row["id"], row["username"]) if row else None


def _get_secret_key():
    """Stable session secret: env var if set, else generated once and stored."""
    key = os.environ.get("FLASK_SECRET_KEY")
    if key:
        return key
    key = db.get_setting("flask_secret_key", "")
    if not key:
        key = secrets.token_hex(32)
        db.save_setting("flask_secret_key", key)
    return key


# Endpoints reachable without logging in
_OPEN_ENDPOINTS = {"login", "static"}


@app.before_request
def _require_login():
    if request.endpoint in _OPEN_ENDPOINTS:
        return
    if current_user.is_authenticated:
        return
    if request.path.startswith("/api/"):
        return jsonify({"error": "Authentication required"}), 401
    return redirect(url_for("login"))

# Scrape status tracker  {platform: {status, progress, total, log_id, error}}
scrape_status: dict = {
    p: {"status": "idle", "progress": 0, "total": 40, "log_id": None, "error": None}
    for p in db.PLATFORMS
}

# Discover status trackers
discover_status: dict        = {"status": "idle", "progress": 0, "total": 0, "found": 0, "error": None}
jiji_discover_status: dict   = {"status": "idle", "progress": 0, "total": 0, "found": 0, "error": None}
twitter_discover_status: dict = {"status": "idle", "progress": 0, "total": 0, "found": 0, "error": None}
tiktok_discover_status: dict  = {"status": "idle", "progress": 0, "total": 0, "found": 0, "error": None}

SCRAPER_MAP = {
    "jiji":        scrape_jiji,
    "instagram":   scrape_instagram,
    "yellowpages": scrape_yellowpages,
    "twitter":     scrape_twitter,
    "tiktok":      scrape_tiktok,
}

# ─── Browser login manager (persistent profiles) ──────────────────────────────
# Phone numbers are only visible to a logged-in browser. These helpers open a
# VISIBLE Chrome window bound to the platform's persistent profile so the user
# logs in once; the session then persists for all future scrapes.

LOGIN_PLATFORMS = ["instagram", "jiji", "twitter", "tiktok"]
LOGIN_URLS = {
    "instagram": "https://www.instagram.com/accounts/login/",
    "jiji":      "https://jiji.ug/login",
    "twitter":   "https://x.com/login",
    "tiktok":    "https://www.tiktok.com/login",
}
login_state: dict = {p: {"status": "idle", "error": None} for p in LOGIN_PLATFORMS}
_login_events: dict = {}


def _run_login(platform: str):
    """Open a visible Chrome login window; close (persisting the session) when the
    user clicks 'I've logged in', when login is auto-detected, or after timeout."""
    from scrapers.browser import build_driver

    url = LOGIN_URLS[platform]
    ev = threading.Event()
    _login_events[platform] = ev
    login_state[platform] = {"status": "opening", "error": None}

    driver = None
    try:
        driver = build_driver(platform, headless=False)  # MUST be visible to log in
        driver.get(url)
        login_state[platform]["status"] = "waiting"

        start = time.time()
        while not ev.is_set() and (time.time() - start) < 600:
            time.sleep(3)
            try:
                cur = (driver.current_url or "").lower()
            except Exception:
                cur = ""
            detected = False
            if platform == "instagram":
                detected = ("instagram.com" in cur
                            and "/accounts/login" not in cur
                            and "/challenge" not in cur)
            elif platform == "jiji":
                detected = ("jiji.ug" in cur
                            and "/login" not in cur and "/signin" not in cur)
            if detected:
                login_state[platform]["status"] = "detected"
                time.sleep(4)  # let cookies settle
                break

        time.sleep(1)
        login_state[platform]["status"] = "done"
    except Exception as e:
        login_state[platform] = {"status": "error", "error": str(e)}
        print(f"[Login/{platform}] Error: {e}")
    finally:
        if driver is not None:
            try:
                driver.quit()
            except Exception:
                pass
        _login_events.pop(platform, None)


# ─── Scraping logic ───────────────────────────────────────────────────────────

def _run_scrape(platform: str):
    """Execute a scrape job in a background thread."""
    api_key = db.get_setting("firecrawl_api_key", "")
    limit   = int(db.get_setting("daily_limit", 40))

    if not api_key:
        scrape_status[platform]["status"] = "error"
        scrape_status[platform]["error"]  = "Firecrawl API key not configured."
        return

    scrape_status[platform].update(
        status="running", progress=0, total=limit, error=None
    )
    log_id = db.start_log(platform)
    scrape_status[platform]["log_id"] = log_id

    def progress_cb(current, total):
        scrape_status[platform]["progress"] = current
        scrape_status[platform]["total"]    = total

    try:
        scraper   = SCRAPER_MAP[platform]
        records   = scraper(api_key=api_key, target_count=limit, progress_cb=progress_cb)
        new_count = 0
        skipped   = 0

        for record in records:
            if db.insert_business(platform, record):
                new_count += 1
            else:
                skipped += 1

        all_records = db.get_businesses(platform=platform, limit=5000)
        exporter.export_platform(platform, all_records)

        db.finish_log(log_id, new_count, skipped)
        scrape_status[platform].update(status="done", progress=new_count, total=limit)
        print(f"[{platform}] done: {new_count} new | {skipped} skipped")

    except Exception as e:
        db.finish_log(log_id, 0, 0, error=str(e))
        scrape_status[platform].update(status="error", error=str(e))
        print(f"[{platform}] Error: {e}")


def _enabled_platforms():
    """Platforms NOT switched off in Settings -> Enabled Platforms."""
    raw = db.get_setting("disabled_platforms", "") or ""
    disabled = {p.strip() for p in raw.split(",") if p.strip()}
    return [p for p in db.PLATFORMS if p not in disabled]


def _write_daily_snapshot():
    """Write today's dated Excel snapshot — TODAY's records only, so every sheet
    (New Today + each platform) is consistent and reflects only today's runs."""
    today = datetime.now().date().isoformat()
    today_by_platform: dict = {}
    for p in db.PLATFORMS:
        recs = db.get_businesses(platform=p, limit=5000)
        today_by_platform[p] = [r for r in recs if str(r.get("scraped_at", "")).startswith(today)]
    try:
        path = exporter.export_daily(today_by_platform, today_by_platform)
        print(f"[Daily] snapshot written: {path}")
    except Exception as e:
        print(f"[Daily] snapshot failed: {e}")


def _run_all_platforms():
    """Scheduled job: scrape ENABLED platforms (if automation on), then snapshot."""
    if str(db.get_setting("automation_enabled", "1")) != "1":
        print("[Scheduler] Automatic collection is OFF — skipping daily run.")
        return
    print("[Scheduler] Daily collection starting ...")
    for platform in _enabled_platforms():
        if scrape_status[platform]["status"] != "running":
            t = threading.Thread(target=_run_scrape, args=(platform,), daemon=True)
            t.start()
            t.join()
    _write_daily_snapshot()


# ─── Jiji two-phase ───────────────────────────────────────────────────────────

def _run_jiji_discover():
    """Phase 1 for Jiji: search for listing URLs, save to queue."""
    global jiji_discover_status
    api_key = db.get_setting("firecrawl_api_key", "")
    if not api_key:
        jiji_discover_status.update(status="error", error="Firecrawl API key not configured.")
        return

    jiji_discover_status.update(status="running", progress=0, total=120, found=0, error=None)

    def progress_cb(current, total):
        jiji_discover_status["progress"] = current
        jiji_discover_status["total"]    = total

    try:
        listings = discover_jiji(api_key=api_key, target_count=120, progress_cb=progress_cb)
        added    = db.queue_jiji_listings(listings)
        jiji_discover_status.update(status="done", found=added, progress=len(listings))
        print(f"[Jiji/Discover] Queued {added} new listings.")
    except Exception as e:
        jiji_discover_status.update(status="error", error=str(e))
        print(f"[Jiji/Discover] Error: {e}")


def _run_jiji_scrape_queued():
    """Phase 2 for Jiji: scrape queued listings for phone/details."""
    api_key = db.get_setting("firecrawl_api_key", "")
    limit   = int(db.get_setting("daily_limit", 40))
    queued  = db.get_jiji_queue(only_unscraped=True)

    if not queued:
        _run_scrape("jiji")
        return

    scrape_status["jiji"].update(
        status="running", progress=0, total=min(limit, len(queued)), error=None
    )
    log_id = db.start_log("jiji")
    scrape_status["jiji"]["log_id"] = log_id

    def progress_cb(current, total):
        scrape_status["jiji"]["progress"] = current
        scrape_status["jiji"]["total"]    = total

    try:
        records      = scrape_jiji_listings(api_key=api_key, queued=queued, target_count=limit, progress_cb=progress_cb)
        new_count    = 0
        skipped      = 0
        scraped_urls = []

        for record in records:
            if db.insert_business("jiji", record):
                new_count += 1
            else:
                skipped += 1
            scraped_urls.append(record.get("source_url", ""))

        db.mark_jiji_scraped(scraped_urls)

        all_records = db.get_businesses(platform="jiji", limit=5000)
        exporter.export_platform("jiji", all_records)

        db.finish_log(log_id, new_count, skipped)
        scrape_status["jiji"].update(status="done", progress=new_count, total=limit)
        print(f"[Jiji] Phase 2 done: {new_count} new | {skipped} skipped")

    except Exception as e:
        db.finish_log(log_id, 0, 0, error=str(e))
        scrape_status["jiji"].update(status="error", error=str(e))
        print(f"[Jiji] Scrape error: {e}")


# ─── Instagram two-phase ──────────────────────────────────────────────────────

def _run_ig_discover():
    """Phase 1 for Instagram: search for profiles, save to queue."""
    global discover_status
    api_key = db.get_setting("firecrawl_api_key", "")
    if not api_key:
        discover_status.update(status="error", error="Firecrawl API key not configured.")
        return

    discover_status.update(status="running", progress=0, total=100, found=0, error=None)

    def progress_cb(current, total):
        discover_status["progress"] = current
        discover_status["total"]    = total

    try:
        profiles = discover_instagram(api_key=api_key, target_count=100, progress_cb=progress_cb)
        added    = db.queue_ig_profiles(profiles)
        discover_status.update(status="done", found=added, progress=len(profiles))
        print(f"[Instagram/Discover] Queued {added} new profiles.")
    except Exception as e:
        discover_status.update(status="error", error=str(e))
        print(f"[Instagram/Discover] Error: {e}")


def _run_ig_scrape_queued():
    """Phase 2 for Instagram: scrape queued profiles via imginn/picuki."""
    api_key = db.get_setting("firecrawl_api_key", "")
    limit   = int(db.get_setting("daily_limit", 40))
    queued  = db.get_ig_queue(only_unscraped=True)

    if not queued:
        _run_scrape("instagram")
        return

    scrape_status["instagram"].update(
        status="running", progress=0, total=min(limit, len(queued)), error=None
    )
    log_id = db.start_log("instagram")
    scrape_status["instagram"]["log_id"] = log_id

    def progress_cb(current, total):
        scrape_status["instagram"]["progress"] = current
        scrape_status["instagram"]["total"]    = total

    try:
        records           = scrape_instagram_profiles(api_key=api_key, queued=queued, target_count=limit, progress_cb=progress_cb)
        new_count         = 0
        skipped           = 0
        scraped_usernames = []

        for record in records:
            if db.insert_business("instagram", record):
                new_count += 1
            else:
                skipped += 1
            scraped_usernames.append(record.get("username", ""))

        db.mark_ig_scraped(scraped_usernames)

        all_records = db.get_businesses(platform="instagram", limit=5000)
        exporter.export_platform("instagram", all_records)

        db.finish_log(log_id, new_count, skipped)
        scrape_status["instagram"].update(status="done", progress=new_count, total=limit)
        print(f"[Instagram] Phase 2 done: {new_count} new | {skipped} skipped")

    except Exception as e:
        db.finish_log(log_id, 0, 0, error=str(e))
        scrape_status["instagram"].update(status="error", error=str(e))
        print(f"[Instagram] Scrape error: {e}")


# ─── Twitter / TikTok two-phase (profile-based, mirrors Instagram) ────────────

def _run_profile_discover(platform, discover_fn, queue_fn, status_dict, target=120):
    api_key = db.get_setting("firecrawl_api_key", "")
    status_dict.update(status="running", progress=0, total=target, found=0, error=None)

    def progress_cb(current, total):
        status_dict["progress"] = current
        status_dict["total"]    = total

    try:
        listings = discover_fn(api_key=api_key, target_count=target, progress_cb=progress_cb)
        added    = queue_fn(listings)
        status_dict.update(status="done", found=added, progress=len(listings))
        print(f"[{platform}/Discover] Queued {added} new profiles.")
    except Exception as e:
        status_dict.update(status="error", error=str(e))
        print(f"[{platform}/Discover] Error: {e}")


def _run_profile_scrape_queued(platform, scrape_fn, get_queue_fn, mark_fn):
    api_key = db.get_setting("firecrawl_api_key", "")
    limit   = int(db.get_setting("daily_limit", 40))
    queued  = get_queue_fn(only_unscraped=True)

    if not queued:
        _run_scrape(platform)   # nothing queued -> fresh one-shot discover+scrape
        return

    scrape_status[platform].update(status="running", progress=0, total=min(limit, len(queued)), error=None)
    log_id = db.start_log(platform)
    scrape_status[platform]["log_id"] = log_id

    def progress_cb(current, total):
        scrape_status[platform]["progress"] = current
        scrape_status[platform]["total"]    = total

    try:
        records      = scrape_fn(api_key=api_key, queued=queued, target_count=limit, progress_cb=progress_cb)
        new_count    = 0
        skipped      = 0
        done_users   = []
        for record in records:
            if db.insert_business(platform, record):
                new_count += 1
            else:
                skipped += 1
            done_users.append(record.get("username", ""))

        mark_fn(done_users)
        exporter.export_platform(platform, db.get_businesses(platform=platform, limit=5000))
        db.finish_log(log_id, new_count, skipped)
        scrape_status[platform].update(status="done", progress=new_count, total=limit)
        print(f"[{platform}] Phase 2 done: {new_count} new | {skipped} skipped")
    except Exception as e:
        db.finish_log(log_id, 0, 0, error=str(e))
        scrape_status[platform].update(status="error", error=str(e))
        print(f"[{platform}] Scrape error: {e}")


def _run_twitter_discover():
    _run_profile_discover("twitter", discover_twitter, db.queue_twitter_profiles, twitter_discover_status)

def _run_twitter_scrape_queued():
    _run_profile_scrape_queued("twitter", scrape_twitter_profiles, db.get_twitter_queue, db.mark_twitter_scraped)

def _run_tiktok_discover():
    _run_profile_discover("tiktok", discover_tiktok, db.queue_tiktok_profiles, tiktok_discover_status)

def _run_tiktok_scrape_queued():
    _run_profile_scrape_queued("tiktok", scrape_tiktok_profiles, db.get_tiktok_queue, db.mark_tiktok_scraped)


def _setup_scheduler():
    hour   = int(db.get_setting("schedule_hour",   8))
    minute = int(db.get_setting("schedule_minute", 0))
    scheduler.add_job(
        _run_all_platforms,
        trigger="cron",
        hour=hour,
        minute=minute,
        id="daily_scrape",
        replace_existing=True,
    )
    if not scheduler.running:
        scheduler.start()


# ─── Routes ───────────────────────────────────────────────────────────────────

@app.route("/")
def dashboard():
    return render_template(
        "dashboard.html",
        username=current_user.username,
        initials=(current_user.username[:2].upper() or "NM"),
    )


@app.route("/login", methods=["GET", "POST"])
def login():
    needs_setup = db.user_count() == 0          # first run -> create the first account
    error = None
    if request.method == "POST":
        username = request.form.get("username", "").strip()
        password = request.form.get("password", "")
        if needs_setup:
            if db.create_user(username, password):
                u = db.get_user_by_username(username)
                login_user(User(u["id"], u["username"]))
                return redirect(url_for("dashboard"))
            error = "Could not create the account — choose a username and a password."
        else:
            u = db.verify_user(username, password)
            if u:
                login_user(User(u["id"], u["username"]))
                return redirect(url_for("dashboard"))
            error = "Invalid username or password."
    return render_template("login.html", needs_setup=needs_setup, error=error)


@app.route("/logout")
def logout():
    logout_user()
    return redirect(url_for("login"))


@app.route("/api/stats")
def api_stats():
    stats = db.get_stats()
    for p in db.PLATFORMS:
        stats[p]["scrape_status"] = scrape_status[p]["status"]
        stats[p]["progress"]      = scrape_status[p]["progress"]
        stats[p]["total"]         = scrape_status[p]["total"]
        stats[p]["error"]         = scrape_status[p]["error"]
    # Instagram queue info
    q = db.get_ig_queue_stats()
    stats["instagram"]["queue_total"]     = q["total"]
    stats["instagram"]["queue_pending"]   = q["pending"]
    stats["instagram"]["discover_status"] = discover_status["status"]
    stats["instagram"]["discover_found"]  = discover_status.get("found", 0)
    # Jiji queue info
    jq = db.get_jiji_queue_stats()
    stats["jiji"]["queue_total"]          = jq["total"]
    stats["jiji"]["queue_pending"]        = jq["pending"]
    stats["jiji"]["discover_status"]      = jiji_discover_status["status"]
    stats["jiji"]["discover_found"]       = jiji_discover_status.get("found", 0)
    # Twitter / TikTok queue info
    for plat, dstat in (("twitter", twitter_discover_status), ("tiktok", tiktok_discover_status)):
        qs = db.get_twitter_queue_stats() if plat == "twitter" else db.get_tiktok_queue_stats()
        stats[plat]["queue_total"]     = qs["total"]
        stats[plat]["queue_pending"]   = qs["pending"]
        stats[plat]["discover_status"] = dstat["status"]
        stats[plat]["discover_found"]  = dstat.get("found", 0)
    return jsonify(stats)


# ── Jiji routes ───────────────────────────────────────────────────────────────

@app.route("/api/discover/jiji", methods=["POST"])
def api_jiji_discover():
    if jiji_discover_status["status"] == "running":
        return jsonify({"error": "Discovery already running"}), 409
    t = threading.Thread(target=_run_jiji_discover, daemon=True)
    t.start()
    return jsonify({"message": "Jiji listing discovery started"})


@app.route("/api/scrape/jiji/queued", methods=["POST"])
def api_jiji_scrape_queued():
    if scrape_status["jiji"]["status"] == "running":
        return jsonify({"error": "Already running"}), 409
    t = threading.Thread(target=_run_jiji_scrape_queued, daemon=True)
    t.start()
    return jsonify({"message": "Jiji scrape started from queue"})


@app.route("/api/jiji/queue")
def api_jiji_queue():
    return jsonify({"queue": db.get_jiji_queue_stats(), "discover": jiji_discover_status})


@app.route("/api/jiji/queue/clear", methods=["POST"])
def api_jiji_queue_clear():
    db.clear_jiji_queue()
    return jsonify({"ok": True})


# ── Instagram routes ──────────────────────────────────────────────────────────

@app.route("/api/discover/instagram", methods=["POST"])
def api_ig_discover():
    if discover_status["status"] == "running":
        return jsonify({"error": "Discovery already running"}), 409
    t = threading.Thread(target=_run_ig_discover, daemon=True)
    t.start()
    return jsonify({"message": "Instagram profile discovery started"})


@app.route("/api/scrape/instagram/queued", methods=["POST"])
def api_ig_scrape_queued():
    if scrape_status["instagram"]["status"] == "running":
        return jsonify({"error": "Already running"}), 409
    t = threading.Thread(target=_run_ig_scrape_queued, daemon=True)
    t.start()
    return jsonify({"message": "Instagram scrape started from queue"})


@app.route("/api/instagram/queue")
def api_ig_queue():
    return jsonify({"queue": db.get_ig_queue_stats(), "discover": discover_status})


@app.route("/api/instagram/queue/clear", methods=["POST"])
def api_ig_queue_clear():
    db.clear_ig_queue()
    return jsonify({"ok": True})


# ── Twitter / TikTok routes ───────────────────────────────────────────────────

@app.route("/api/discover/twitter", methods=["POST"])
def api_twitter_discover():
    if twitter_discover_status["status"] == "running":
        return jsonify({"error": "Discovery already running"}), 409
    threading.Thread(target=_run_twitter_discover, daemon=True).start()
    return jsonify({"message": "Twitter discovery started"})


@app.route("/api/scrape/twitter/queued", methods=["POST"])
def api_twitter_scrape_queued():
    if scrape_status["twitter"]["status"] == "running":
        return jsonify({"error": "Already running"}), 409
    threading.Thread(target=_run_twitter_scrape_queued, daemon=True).start()
    return jsonify({"message": "Twitter scrape started from queue"})


@app.route("/api/twitter/queue")
def api_twitter_queue():
    return jsonify({"queue": db.get_twitter_queue_stats(), "discover": twitter_discover_status})


@app.route("/api/twitter/queue/clear", methods=["POST"])
def api_twitter_queue_clear():
    db.clear_twitter_queue()
    return jsonify({"ok": True})


@app.route("/api/discover/tiktok", methods=["POST"])
def api_tiktok_discover():
    if tiktok_discover_status["status"] == "running":
        return jsonify({"error": "Discovery already running"}), 409
    threading.Thread(target=_run_tiktok_discover, daemon=True).start()
    return jsonify({"message": "TikTok discovery started"})


@app.route("/api/scrape/tiktok/queued", methods=["POST"])
def api_tiktok_scrape_queued():
    if scrape_status["tiktok"]["status"] == "running":
        return jsonify({"error": "Already running"}), 409
    threading.Thread(target=_run_tiktok_scrape_queued, daemon=True).start()
    return jsonify({"message": "TikTok scrape started from queue"})


@app.route("/api/tiktok/queue")
def api_tiktok_queue():
    return jsonify({"queue": db.get_tiktok_queue_stats(), "discover": tiktok_discover_status})


@app.route("/api/tiktok/queue/clear", methods=["POST"])
def api_tiktok_queue_clear():
    db.clear_tiktok_queue()
    return jsonify({"ok": True})


# ── Browser login routes ──────────────────────────────────────────────────────

@app.route("/api/login/<platform>", methods=["POST"])
def api_login_open(platform):
    if platform not in LOGIN_PLATFORMS:
        return jsonify({"error": "Unknown platform"}), 400
    if login_state[platform]["status"] in ("opening", "waiting", "detected"):
        return jsonify({"error": "Login window already open"}), 409
    t = threading.Thread(target=_run_login, args=(platform,), daemon=True)
    t.start()
    return jsonify({"message": f"Opening {platform} login window"})


@app.route("/api/login/<platform>/finish", methods=["POST"])
def api_login_finish(platform):
    if platform not in LOGIN_PLATFORMS:
        return jsonify({"error": "Unknown platform"}), 400
    ev = _login_events.get(platform)
    if ev:
        ev.set()
    return jsonify({"ok": True})


@app.route("/api/login/status")
def api_login_status():
    return jsonify(login_state)


# ── General routes ────────────────────────────────────────────────────────────

@app.route("/api/scrape/<platform>", methods=["POST"])
def api_scrape(platform):
    if platform not in db.PLATFORMS:
        return jsonify({"error": "Unknown platform"}), 400
    if scrape_status[platform]["status"] == "running":
        return jsonify({"error": "Already running"}), 409
    t = threading.Thread(target=_run_scrape, args=(platform,), daemon=True)
    t.start()
    return jsonify({"message": f"Scrape started for {platform}"})


def _run_all_sequential():
    """Run every ENABLED platform ONE AT A TIME (one browser open at a time = far
    more stable than 5 concurrent Chrome windows), then write the daily snapshot."""
    for platform in _enabled_platforms():
        if scrape_status[platform]["status"] != "running":
            try:
                _run_scrape(platform)
            except Exception as e:
                print(f"[RunCollection] {platform} crashed: {e}")
    _write_daily_snapshot()


@app.route("/api/scrape/all", methods=["POST"])
def api_scrape_all():
    if any(scrape_status[p]["status"] == "running" for p in db.PLATFORMS):
        return jsonify({"error": "A collection is already running"}), 409
    threading.Thread(target=_run_all_sequential, daemon=True).start()
    return jsonify({"started": _enabled_platforms()})


@app.route("/api/download/<platform>")
def api_download(platform):
    if platform not in db.PLATFORMS:
        return jsonify({"error": "Unknown platform"}), 400
    latest = exporter.get_latest_export(platform)
    if not latest:
        records = db.get_businesses(platform=platform, limit=5000)
        latest  = exporter.export_platform(platform, records)
    return send_file(
        latest,
        as_attachment=True,
        download_name=os.path.basename(latest),
        mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )


@app.route("/api/download/today")
def api_download_today():
    """Always regenerate today's snapshot from the DB so it reflects current data."""
    today = datetime.now().date().isoformat()
    today_by_platform = {
        p: [r for r in db.get_businesses(platform=p, limit=5000)
            if str(r.get("scraped_at", "")).startswith(today)]
        for p in db.PLATFORMS
    }
    filepath = exporter.export_daily(today_by_platform, today_by_platform)
    return send_file(
        filepath,
        as_attachment=True,
        download_name=os.path.basename(filepath),
        mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )


@app.route("/api/download/all/combined")
def api_download_all():
    records_by_platform = {p: db.get_businesses(platform=p, limit=5000) for p in db.PLATFORMS}
    filepath = exporter.export_all(records_by_platform)
    return send_file(
        filepath,
        as_attachment=True,
        download_name=os.path.basename(filepath),
        mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )


@app.route("/api/businesses")
def api_businesses():
    platform = request.args.get("platform")
    search   = request.args.get("search")
    limit    = int(request.args.get("limit", 100))
    offset   = int(request.args.get("offset", 0))
    records  = db.get_businesses(platform=platform, limit=limit, offset=offset, search=search)
    return jsonify(records)


@app.route("/api/businesses/<platform>/<int:record_id>", methods=["DELETE"])
def api_delete(platform, record_id):
    ok = db.delete_business(platform, record_id)
    return jsonify({"ok": ok})


@app.route("/api/logs")
def api_logs():
    return jsonify(db.get_logs(60))


@app.route("/api/settings", methods=["GET", "POST"])
def api_settings():
    if request.method == "GET":
        return jsonify({
            "firecrawl_api_key":  db.get_setting("firecrawl_api_key", ""),
            "daily_limit":        db.get_setting("daily_limit", "40"),
            "schedule_hour":      db.get_setting("schedule_hour", "8"),
            "schedule_minute":    db.get_setting("schedule_minute", "0"),
            "automation_enabled": db.get_setting("automation_enabled", "1"),
            "disabled_platforms": db.get_setting("disabled_platforms", ""),
        })
    data = request.get_json() or {}
    for key in ["firecrawl_api_key", "daily_limit", "schedule_hour", "schedule_minute",
                "automation_enabled", "disabled_platforms"]:
        if key in data:
            db.save_setting(key, data[key])
    _setup_scheduler()
    return jsonify({"ok": True})


@app.route("/api/schedule")
def api_schedule():
    job = scheduler.get_job("daily_scrape")
    return jsonify({
        "hour":     db.get_setting("schedule_hour", "8"),
        "minute":   db.get_setting("schedule_minute", "0"),
        "next_run": str(job.next_run_time) if job else None,
        "enabled":  job is not None,
    })


# Init

def create_app():
    db.init_db()
    app.secret_key = _get_secret_key()
    stale = db.mark_stale_running_failed()
    if stale:
        print(f"[Startup] Marked {stale} interrupted 'running' log(s) as failed.")
    _setup_scheduler()
    return app


if __name__ == "__main__":
    create_app().run(host="127.0.0.1", port=5050, debug=False)
