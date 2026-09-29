"""
Twitter / X Uganda Business Scraper — logged-in, Google-discovery (Selenium).

Same two-phase architecture as the Instagram module:

  • discover_twitter()         Google "<query> site:x.com" search in a persistent
                               Chrome profile, collecting business PROFILE URLs
                               (https://x.com/<handle>) — ignores /status/ tweets.

  • scrape_twitter_profiles()  Visit each profile DIRECTLY on x.com (logged in),
                               read the name / bio / location, and extract
                               phone / email / category / location.

Login persists via a Chrome profile in  browser_profiles/twitter  (run
`python login.py twitter` once, or sign in from the dashboard). `api_key` args
are kept but unused so app.py needs no special-casing.

NOTE: X aggressively gates logged-out access, so a signed-in session is required
for profiles to load. Selectors (data-testid=*) may need tuning if X changes its
markup — same as the Jiji "Show contact" button.
"""

from __future__ import annotations

import re
import time
import random
import logging
from urllib.parse import quote_plus, urlparse, parse_qs, unquote
from typing import List, Dict, Optional

from selenium.webdriver.common.by import By

from .browser import build_driver, phones_from_text, twitter_logged_in
from . import queries as Q

logger = logging.getLogger(__name__)

PROFILE = "twitter"
DOMAINS = ("x.com", "twitter.com")

EMAIL_RE = re.compile(r"[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}")

# Reserved X paths that are not business profiles
SKIP_HANDLES = {
    "home", "explore", "search", "hashtag", "i", "messages", "notifications",
    "settings", "login", "signup", "intent", "share", "compose", "status",
    "about", "tos", "privacy", "help", "download", "logout", "account",
    "username", "who_to_follow", "topics", "lists", "bookmarks",
}


# ── URL helpers ───────────────────────────────────────────────────────────────

def _clean_google_url(href: str) -> str:
    try:
        if "google.com/url?" in href:
            qs = parse_qs(urlparse(href).query)
            if "q" in qs:
                href = qs["q"][0]
        return unquote(href)
    except Exception:
        return href


def _handle_from_url(url: str) -> Optional[str]:
    low = (url or "").lower()
    if not any(d in low for d in DOMAINS):
        return None
    if "/status/" in low or "/i/" in low or "/search" in low or "/hashtag/" in low:
        return None
    m = re.search(r"(?:x|twitter)\.com/([^/?&#\s]+)", url or "")
    if not m:
        return None
    handle = m.group(1).lstrip("@")
    if handle.lower() in SKIP_HANDLES or len(handle) < 2:
        return None
    return handle


# ── PHASE 1: discover profile URLs via Google ─────────────────────────────────

def discover_twitter(api_key: str = "", target_count: int = 100,
                     progress_cb=None, headless: bool = False) -> List[Dict]:
    """Google-search Uganda business profiles on x.com. Returns [{username, profile_url}]."""
    logger.info("[Twitter/Discover] start — target %s", target_count)
    found: List[Dict] = []
    seen: set = set()
    queries = Q.build_site_queries("x.com")
    blocked_queries = 0
    zero_result_queries = 0

    driver = build_driver(PROFILE, headless=headless)
    try:
        for qi, query in enumerate(queries):
            if len(found) >= target_count:
                break
            driver.get("https://www.google.com/search?q=" + quote_plus(query))
            time.sleep(random.uniform(2.5, 4.0))
            still_blocked = _wait_out_google_block(driver, max_wait=180 if qi == 0 else 60)
            if still_blocked:
                blocked_queries += 1

            before = len(found)
            links_seen = 0
            for a in driver.find_elements(By.TAG_NAME, "a"):
                if len(found) >= target_count:
                    break
                try:
                    href = a.get_attribute("href")
                except Exception:
                    continue   # element went stale while reading results
                if not href:
                    continue
                links_seen += 1
                href = _clean_google_url(href)
                handle = _handle_from_url(href)
                if not handle or handle.lower() in seen:
                    continue
                seen.add(handle.lower())
                found.append({
                    "username": "@" + handle,
                    "profile_url": f"https://x.com/{handle}",
                })
                if progress_cb:
                    progress_cb(len(found), target_count)
            added = len(found) - before
            if added == 0:
                zero_result_queries += 1
            logger.info("[Twitter/Discover] %s -> +%d (total %d, %d links seen on page)",
                        query[:48], added, len(found), links_seen)
            time.sleep(random.uniform(1.5, 3.0))
    finally:
        _quit(driver)

    if not found:
        # Zero profiles is a common silent-failure mode — spell out the likely
        # cause instead of just returning an empty list, so it shows up in logs.
        if blocked_queries >= max(1, len(queries) // 2):
            logger.warning(
                "[Twitter/Discover] 0 profiles found — Google blocked/CAPTCHA'd "
                "%d of %d searches. Run `python login.py twitter` in a visible "
                "window and solve the CAPTCHA once, or try again later.",
                blocked_queries, len(queries),
            )
        elif zero_result_queries == len(queries):
            logger.warning(
                "[Twitter/Discover] 0 profiles found — every query returned 0 "
                "matching x.com/twitter.com links. Google search result markup "
                "may have changed, or Google is filtering x.com results for this "
                "session/region."
            )
        else:
            logger.warning(
                "[Twitter/Discover] 0 profiles found for an unclear reason — "
                "check browser_profiles/twitter has a valid session and rerun "
                "with headless=False to watch what the search results show."
            )
    logger.info("[Twitter/Discover] done — %d profiles", len(found))
    return found[:target_count]


def _wait_out_google_block(driver, max_wait: int = 60) -> bool:
    """Wait for a Google CAPTCHA/'unusual traffic' block to clear. Returns True if
    still blocked when max_wait is reached (used to explain 0-result runs)."""
    waited = 0
    while waited < max_wait:
        url = (driver.current_url or "").lower()
        src = (driver.page_source or "").lower()
        blocked = ("/sorry/" in url or "unusual traffic" in src
                   or "before you continue" in src or "are you a robot" in src)
        if not blocked:
            return False
        logger.warning("[Twitter/Discover] Google check — solve it in the window… (%ds)", waited)
        time.sleep(5)
        waited += 5
    # Loop exited on the time budget, not because the block cleared — re-check once.
    url = (driver.current_url or "").lower()
    src = (driver.page_source or "").lower()
    return "/sorry/" in url or "unusual traffic" in src or "before you continue" in src or "are you a robot" in src


# ── PHASE 2: scrape each profile on x.com ─────────────────────────────────────

def _text(driver, selector: str) -> str:
    try:
        return (driver.find_element(By.CSS_SELECTOR, selector).text or "").strip()
    except Exception:
        return ""


def _meta(driver, name_or_prop: str, attr: str = "name") -> str:
    try:
        el = driver.find_element(By.XPATH, f"//meta[@{attr}='{name_or_prop}']")
        return el.get_attribute("content") or ""
    except Exception:
        return ""


def scrape_twitter_profiles(api_key: str = "", queued: List[Dict] = None,
                            target_count: int = 40, progress_cb=None,
                            headless: bool = False) -> List[Dict]:
    """Visit each queued x.com profile (logged in) and extract business fields."""
    queued = queued or []
    logger.info("[Twitter/Scrape] %d queued, target %d", len(queued), target_count)
    results: List[Dict] = []
    seen_handles: set = set()
    login_walls = 0

    driver = build_driver(PROFILE, headless=headless)
    try:
        if not twitter_logged_in(driver):
            logger.error(
                "[Twitter/Scrape] NOT logged in to X/Twitter in this profile. "
                "Run `python login.py twitter` (or use the dashboard's 'Sign in to "
                "Twitter/X' button) first — logged-out profile pages are heavily "
                "gated and will return little or no data."
            )

        for item in queued:
            if len(results) >= target_count:
                break
            handle = (item.get("username") or "").lstrip("@").strip()
            profile_url = item.get("profile_url") or f"https://x.com/{handle}"
            if not handle or handle.lower() in seen_handles:
                continue
            seen_handles.add(handle.lower())

            try:
                driver.get(profile_url)
                time.sleep(random.uniform(4.0, 6.0))

                cur = (driver.current_url or "").lower()
                if "/login" in cur or "/i/flow/login" in cur:
                    login_walls += 1
                    logger.warning("[Twitter/Scrape] %s -> redirected to login wall, skipping", handle)
                    continue
                if "suspended" in cur or "account/suspended" in cur:
                    logger.info("[Twitter/Scrape] %s -> account suspended, skipping", handle)
                    continue

                name = _text(driver, "[data-testid='UserName']").split("\n")[0].strip()
                bio  = _text(driver, "[data-testid='UserDescription']")
                loc  = _text(driver, "[data-testid='UserLocation']")
                meta_desc = _meta(driver, "description") or _meta(driver, "og:description", "property")

                # Extra phone sources: tel: links + the full profile column text
                # (many businesses put the number in a pinned post / header, not the bio).
                extra = []
                try:
                    for a in driver.find_elements(By.CSS_SELECTOR, "a[href^='tel:']"):
                        extra.append((a.get_attribute("href") or "").replace("tel:", ""))
                except Exception:
                    pass
                try:
                    extra.append(driver.find_element(By.CSS_SELECTOR, "[data-testid='primaryColumn']").text)
                except Exception:
                    pass
                combined = "\n".join([name, bio, loc, meta_desc] + extra)

                if not name:
                    name = "@" + handle

                phones = phones_from_text(combined)
                phone = phones[0] if phones else ""
                em = EMAIL_RE.search(combined)
                email = em.group(0).lower() if em else ""

                rec = {
                    "business_name": name[:120],
                    "username": "@" + handle,
                    "phone": phone,
                    "email": email,
                    "category": Q.infer_category(combined),
                    "location": Q.infer_location(loc + " " + bio),
                    "source_url": profile_url,
                }
                results.append(rec)
                if progress_cb:
                    progress_cb(len(results), target_count)
                logger.info("[Twitter/Scrape] [%d] %s | %s", len(results), name[:35], phone or "(no phone)")
            except Exception as e:
                logger.error("[Twitter/Scrape] %s failed: %s", handle, e)

            time.sleep(random.uniform(1.5, 3.0))
    finally:
        _quit(driver)

    if not results and login_walls:
        logger.warning(
            "[Twitter/Scrape] 0 records — %d/%d queued profiles hit a login wall. "
            "The saved session has likely expired; re-run `python login.py twitter`.",
            login_walls, len(queued),
        )
    logger.info("[Twitter/Scrape] done — %d records (%d login walls)", len(results), login_walls)
    return results[:target_count]


# ── Legacy one-shot entry point (Run Collection / scheduler) ──────────────────

def scrape_twitter(api_key: str = "", target_count: int = 40,
                   progress_cb=None, headless: bool = False) -> List[Dict]:
    discovered = discover_twitter(api_key, target_count=target_count * 3, headless=headless)
    if not discovered:
        logger.warning("[Twitter] no profiles discovered.")
        return []
    return scrape_twitter_profiles(api_key, discovered, target_count=target_count,
                                   progress_cb=progress_cb, headless=headless)


def _quit(driver):
    try:
        driver.quit()
    except Exception:
        pass
