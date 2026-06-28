"""
TikTok Uganda Business Scraper — logged-in, Google-discovery (Selenium).

Same two-phase architecture as Instagram / Twitter:

  • discover_tiktok()        Google "<query> site:tiktok.com" search, collecting
                             business PROFILE URLs (https://www.tiktok.com/@handle).
                             Video URLs (.../@handle/video/123) are CONVERTED to
                             the profile URL; pure video/hashtag URLs are dropped.

  • scrape_tiktok_profiles() Visit each profile on tiktok.com (logged in), read
                             the title / bio, and extract phone / email /
                             category / location.

Login persists via  browser_profiles/tiktok  (run `python login.py tiktok`
once, or sign in from the dashboard). `api_key` args kept but unused.

NOTE: TikTok gates logged-out browsing and changes markup often; the
data-e2e=* selectors below may need tuning — same situation as Jiji/X.
"""

from __future__ import annotations

import re
import time
import random
import logging
from urllib.parse import quote_plus, urlparse, parse_qs, unquote
from typing import List, Dict, Optional

from selenium.webdriver.common.by import By

from .browser import build_driver, phones_from_text
from . import queries as Q

logger = logging.getLogger(__name__)

PROFILE = "tiktok"
DOMAIN = "tiktok.com"

EMAIL_RE = re.compile(r"[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}")


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


def _profile_from_url(url: str) -> Optional[str]:
    """Return the @handle for a TikTok profile, converting video URLs to profiles."""
    low = (url or "").lower()
    if DOMAIN not in low:
        return None
    # must contain an @handle segment; ignore tag/discover/music/etc.
    m = re.search(r"tiktok\.com/(@[^/?&#\s]+)", url or "")
    if not m:
        return None
    handle = m.group(1)  # keeps the leading @
    if len(handle) < 3:
        return None
    return handle


# ── PHASE 1: discover profile URLs via Google ─────────────────────────────────

def discover_tiktok(api_key: str = "", target_count: int = 100,
                    progress_cb=None, headless: bool = False) -> List[Dict]:
    """Google-search Uganda business profiles on tiktok.com. Returns [{username, profile_url}]."""
    logger.info("[TikTok/Discover] start — target %s", target_count)
    found: List[Dict] = []
    seen: set = set()
    queries = Q.build_site_queries("tiktok.com")

    driver = build_driver(PROFILE, headless=headless)
    try:
        for qi, query in enumerate(queries):
            if len(found) >= target_count:
                break
            driver.get("https://www.google.com/search?q=" + quote_plus(query))
            time.sleep(random.uniform(2.5, 4.0))
            _wait_out_google_block(driver, max_wait=180 if qi == 0 else 60)

            before = len(found)
            for a in driver.find_elements(By.TAG_NAME, "a"):
                if len(found) >= target_count:
                    break
                try:
                    href = a.get_attribute("href")
                except Exception:
                    continue   # element went stale while reading results
                if not href:
                    continue
                href = _clean_google_url(href)
                handle = _profile_from_url(href)            # converts video -> profile
                if not handle or handle.lower() in seen:
                    continue
                seen.add(handle.lower())
                found.append({
                    "username": handle,
                    "profile_url": f"https://www.tiktok.com/{handle}",
                })
                if progress_cb:
                    progress_cb(len(found), target_count)
            logger.info("[TikTok/Discover] %s -> +%d (total %d)",
                        query[:48], len(found) - before, len(found))
            time.sleep(random.uniform(1.5, 3.0))
    finally:
        _quit(driver)

    logger.info("[TikTok/Discover] done — %d profiles", len(found))
    return found[:target_count]


def _wait_out_google_block(driver, max_wait: int = 60):
    waited = 0
    while waited < max_wait:
        url = (driver.current_url or "").lower()
        src = (driver.page_source or "").lower()
        blocked = ("/sorry/" in url or "unusual traffic" in src
                   or "before you continue" in src or "are you a robot" in src)
        if not blocked:
            return
        logger.warning("[TikTok/Discover] Google check — solve it in the window… (%ds)", waited)
        time.sleep(5)
        waited += 5


# ── PHASE 2: scrape each profile on tiktok.com ────────────────────────────────

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


def scrape_tiktok_profiles(api_key: str = "", queued: List[Dict] = None,
                           target_count: int = 40, progress_cb=None,
                           headless: bool = False) -> List[Dict]:
    """Visit each queued TikTok profile (logged in) and extract business fields."""
    queued = queued or []
    logger.info("[TikTok/Scrape] %d queued, target %d", len(queued), target_count)
    results: List[Dict] = []
    seen_handles: set = set()

    driver = build_driver(PROFILE, headless=headless)
    try:
        for item in queued:
            if len(results) >= target_count:
                break
            handle = (item.get("username") or "").strip()
            if not handle.startswith("@"):
                handle = "@" + handle.lstrip("@")
            profile_url = item.get("profile_url") or f"https://www.tiktok.com/{handle}"
            if handle.lower() in seen_handles:
                continue
            seen_handles.add(handle.lower())

            try:
                driver.get(profile_url)
                time.sleep(random.uniform(4.0, 6.0))

                name = (_text(driver, "[data-e2e='user-title']")
                        or _text(driver, "[data-e2e='user-subtitle']"))
                bio  = _text(driver, "[data-e2e='user-bio']")
                meta_desc = _meta(driver, "description") or _meta(driver, "og:description", "property")

                # Extra phone sources: tel: links + meta (TikTok often puts the
                # contact in the bio that also surfaces in og:description).
                extra = []
                try:
                    for a in driver.find_elements(By.CSS_SELECTOR, "a[href^='tel:']"):
                        extra.append((a.get_attribute("href") or "").replace("tel:", ""))
                except Exception:
                    pass
                combined = "\n".join([name, bio, meta_desc] + extra)

                if not name:
                    name = handle

                phones = phones_from_text(combined)
                phone = phones[0] if phones else ""
                em = EMAIL_RE.search(combined)
                email = em.group(0).lower() if em else ""

                rec = {
                    "business_name": name[:120],
                    "username": handle,
                    "phone": phone,
                    "email": email,
                    "category": Q.infer_category(combined),
                    "location": Q.infer_location(combined),
                    "source_url": profile_url,
                }
                results.append(rec)
                if progress_cb:
                    progress_cb(len(results), target_count)
                logger.info("[TikTok/Scrape] [%d] %s | %s", len(results), name[:35], phone or "(no phone)")
            except Exception as e:
                logger.error("[TikTok/Scrape] %s failed: %s", handle, e)

            time.sleep(random.uniform(1.5, 3.0))
    finally:
        _quit(driver)

    logger.info("[TikTok/Scrape] done — %d records", len(results))
    return results[:target_count]


# ── Legacy one-shot entry point (Run Collection / scheduler) ──────────────────

def scrape_tiktok(api_key: str = "", target_count: int = 40,
                  progress_cb=None, headless: bool = False) -> List[Dict]:
    discovered = discover_tiktok(api_key, target_count=target_count * 3, headless=headless)
    if not discovered:
        logger.warning("[TikTok] no profiles discovered.")
        return []
    return scrape_tiktok_profiles(api_key, discovered, target_count=target_count,
                                  progress_cb=progress_cb, headless=headless)


def _quit(driver):
    try:
        driver.quit()
    except Exception:
        pass
