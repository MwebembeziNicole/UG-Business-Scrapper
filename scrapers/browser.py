"""
Shared Selenium browser factory + extraction helpers.

WHY THIS EXISTS
---------------
The old scrapers failed to get phone numbers because they ran **headless**
and pulled Instagram data from dead third-party viewer sites (imginn / picuki /
dumpor), with no login. Phone numbers on Instagram live in the bio, and on Jiji
behind the "Show Contact" button — both require a **real, logged-in browser
session** viewing the real site directly.

This module gives every scraper one consistent way to open a **persistent,
logged-in Chrome profile**:

  • A user-data-dir is kept per platform under  <project>/browser_profiles/<name>
  • You log in ONCE (run  python login.py)  in a visible window.
  • Every later run reuses that profile -> already logged in -> phones visible.

By default the window is VISIBLE (headless=False) because that is what reliably
defeats Instagram/Jiji bot checks and matches the scripts that already work.
"""

from __future__ import annotations

import os
import re
import time
import logging
from typing import List

import config

logger = logging.getLogger(__name__)

# ── Profile storage ───────────────────────────────────────────────────────────
PROFILE_ROOT = config.BROWSER_PROFILE_DIR


def profile_dir(name: str) -> str:
    """Absolute path to the persistent Chrome profile for a platform."""
    path = os.path.join(PROFILE_ROOT, name)
    os.makedirs(path, exist_ok=True)
    return path


def _clear_profile_locks(udd: str) -> None:
    """Remove stale Chrome 'singleton' lock files left behind when a previous
    run crashed or was force-closed. When these linger, Chrome exits instantly
    with 'session not created: Chrome instance exited'. Safe to call before a
    scrape, when no Chrome is using this profile (the normal case)."""
    for name in ("SingletonLock", "SingletonCookie", "SingletonSocket"):
        p = os.path.join(udd, name)
        try:
            if os.path.lexists(p):
                os.remove(p)
        except OSError:
            pass


def _chrome_major_version():
    """Best-effort major version of the installed Chrome (e.g. 138), so the
    driver can be matched to it. A driver/Chrome version mismatch is the most
    common cause of 'Chrome instance exited'. Returns None if it can't be found."""
    import subprocess

    # Windows registry — per-user (HKCU) then machine-wide (HKLM)
    for hive in ("HKCU", "HKLM"):
        try:
            out = subprocess.check_output(
                ["reg", "query", rf"{hive}\Software\Google\Chrome\BLBeacon", "/v", "version"],
                stderr=subprocess.DEVNULL, text=True, timeout=5,
            )
            m = re.search(r"version\s+REG_SZ\s+(\d+)\.", out)
            if m:
                return int(m.group(1))
        except Exception:
            pass

    # chrome.exe --version on the usual install locations
    for exe in (
        r"C:\Program Files\Google\Chrome\Application\chrome.exe",
        r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
        os.path.expandvars(r"%LOCALAPPDATA%\Google\Chrome\Application\chrome.exe"),
    ):
        try:
            if not os.path.exists(exe):
                continue
            out = subprocess.check_output([exe, "--version"], stderr=subprocess.DEVNULL,
                                          text=True, timeout=5)
            m = re.search(r"(\d+)\.", out)
            if m:
                return int(m.group(1))
        except Exception:
            pass
    return None


# ── Driver factory ────────────────────────────────────────────────────────────

def build_driver(profile_name: str, headless: bool = False):
    """
    Return a Chrome driver bound to a persistent profile.

    profile_name : 'instagram' | 'jiji' | ...  -> picks the user-data-dir
    headless     : keep False for login-gated sites (default).

    Tries undetected-chromedriver first (best anti-bot), falls back to plain
    selenium + webdriver-manager.
    """
    udd = profile_dir(profile_name)
    _clear_profile_locks(udd)               # recover from a crashed previous run
    chrome_major = _chrome_major_version()  # match the driver to installed Chrome

    # 1) undetected-chromedriver --------------------------------------------------
    try:
        import undetected_chromedriver as uc

        options = uc.ChromeOptions()
        options.add_argument(f"--user-data-dir={udd}")
        options.add_argument("--no-sandbox")
        options.add_argument("--disable-dev-shm-usage")
        options.add_argument("--disable-gpu")
        options.add_argument(f"--window-size={config.BROWSER_WINDOW_SIZE}")
        options.add_argument("--start-maximized")
        if headless:
            options.add_argument("--headless=new")
        uc_kwargs = {"options": options, "use_subprocess": True}
        if chrome_major:
            uc_kwargs["version_main"] = chrome_major   # avoid driver/Chrome mismatch
        driver = uc.Chrome(**uc_kwargs)
        driver.set_page_load_timeout(config.BROWSER_PAGE_LOAD_TIMEOUT)
        logger.info("[Browser] undetected-chromedriver OK  profile=%s (chrome v%s)",
                    profile_name, chrome_major or "?")
        return driver
    except ImportError:
        logger.warning("[Browser] undetected-chromedriver not installed — using plain selenium")
    except Exception as e:
        logger.warning("[Browser] uc failed (%s) — falling back to plain selenium", e)
        _clear_profile_locks(udd)   # uc may have left a lock behind when it crashed

    # 2) plain selenium -----------------------------------------------------------
    from selenium import webdriver
    from selenium.webdriver.chrome.options import Options
    from selenium.webdriver.chrome.service import Service

    opts = Options()
    opts.add_argument(f"--user-data-dir={udd}")
    opts.add_argument("--no-sandbox")
    opts.add_argument("--disable-dev-shm-usage")
    opts.add_argument("--disable-gpu")
    opts.add_argument(f"--window-size={config.BROWSER_WINDOW_SIZE}")
    if headless:
        opts.add_argument("--headless=new")
    opts.add_experimental_option("excludeSwitches", ["enable-automation"])
    opts.add_experimental_option("useAutomationExtension", False)
    opts.add_argument(
        "--user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
    )

    _clear_profile_locks(udd)
    # Prefer Selenium Manager (built into selenium ≥ 4.6): it auto-downloads the
    # chromedriver that matches the installed Chrome, fixing the common
    # 'Chrome instance exited' version mismatch. Fall back to webdriver-manager.
    try:
        driver = webdriver.Chrome(options=opts)
    except Exception:
        try:
            from webdriver_manager.chrome import ChromeDriverManager
            driver = webdriver.Chrome(service=Service(ChromeDriverManager().install()), options=opts)
        except Exception:
            driver = webdriver.Chrome(service=Service(), options=opts)
    try:
        driver.execute_cdp_cmd(
            "Page.addScriptToEvaluateOnNewDocument",
            {"source": "Object.defineProperty(navigator,'webdriver',{get:()=>undefined})"},
        )
    except Exception:
        pass
    driver.set_page_load_timeout(config.BROWSER_PAGE_LOAD_TIMEOUT)
    logger.info("[Browser] plain selenium webdriver  profile=%s", profile_name)
    return driver


# ── Login detection ───────────────────────────────────────────────────────────

def instagram_logged_in(driver) -> bool:
    """Heuristic: are we logged into instagram.com in this profile?"""
    try:
        driver.get("https://www.instagram.com/")
        time.sleep(4)
        page = (driver.page_source or "").lower()
        cur = (driver.current_url or "").lower()
        if "/accounts/login" in cur:
            return False
        if 'name="username"' in page and 'name="password"' in page:
            return False
        return True
    except Exception:
        return False


def jiji_logged_in(driver) -> bool:
    """Heuristic: are we logged into jiji.ug in this profile?"""
    try:
        driver.get("https://jiji.ug/")
        time.sleep(4)
        page = (driver.page_source or "").lower()
        return "log out" in page or "my profile" in page or "sign out" in page
    except Exception:
        return False


# ── Phone / location / category helpers (shared) ──────────────────────────────

# Ugandan numbers carry a 9-digit national number after +256 / 256 / 0.
# Accepts spaces or hyphens between groups: +256 772 123 456, 0772 123 456,
# 0701 234 567, +256772123456, 0772123456, etc.
PHONE_RE = re.compile(
    r'(\+?256[\s\-]?(?:\d[\s\-]?){8}\d'   # +256 / 256 + 9 digits (sep-tolerant)
    r'|\b0[\s\-]?(?:\d[\s\-]?){8}\d)'      # 0 + 9 digits (sep-tolerant)
)


def clean_phone(raw: str) -> str:
    """Normalise a raw phone string to +256XXXXXXXXX (9 digits after +256)."""
    if not raw:
        return ""
    d = re.sub(r"\D", "", raw)            # digits only
    if d.startswith("256"):
        nat = d[3:12]
    elif d.startswith("0"):
        nat = d[1:10]
    elif len(d) >= 9 and d[0] in "73":
        nat = d[:9]
    else:
        return ""
    # A valid UG mobile/landline national number is 9 digits starting 7/3/2/4.
    if len(nat) == 9 and nat[0] in "7342":
        return "+256" + nat
    return ""


def phones_from_text(text: str) -> List[str]:
    """All unique, cleaned Ugandan phone numbers found in a blob of text."""
    seen, out = set(), []
    for m in PHONE_RE.findall(text or ""):
        c = clean_phone(m)
        if c and c not in seen:
            seen.add(c)
            out.append(c)
    return out
