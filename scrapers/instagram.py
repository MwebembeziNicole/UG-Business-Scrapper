"""
Instagram Uganda Business Scraper — logged-in, direct-site (Selenium).

REPLACES the old Firecrawl + third-party-viewer approach, which returned no
phone numbers because imginn/picuki/dumpor are dead/blocked and no login was
used. This version ports Nicole's working scripts:

  • discover_instagram()         <- google_instagram_search.py
        Google "site:instagram.com ..." search in a persistent Chrome profile,
        collecting business profile URLs.

  • scrape_instagram_profiles()  <- ig_scraper.py
        Visit each profile DIRECTLY on instagram.com while logged in, read the
        header/bio + meta description, and regex the phone number out.

Login is handled by a PERSISTENT Chrome profile (browser_profiles/instagram).
Run  `python login.py`  once to log in; the session then persists.

Function signatures keep an unused `api_key` argument so app.py keeps working
without changes (discovery no longer needs Firecrawl).
"""

from __future__ import annotations

import re
import time
import random
import logging
from urllib.parse import quote_plus, urlparse, parse_qs, unquote
from typing import List, Dict, Optional

from selenium.webdriver.common.by import By

from .browser import (
    build_driver,
    instagram_logged_in,
    phones_from_text,
)
from . import queries as Q

logger = logging.getLogger(__name__)

PROFILE = "instagram"

# ── Discovery queries (Google, site:instagram.com) ────────────────────────────
# Ported & trimmed from google_instagram_search.py — edit freely.
LOCATIONS = [
    "Mukono Uganda", "Kyanja Kampala", "Entebbe Uganda", "Bugolobi Kampala",
    "Nakawa Kampala", "Wandegeya Kampala", "Kikoni Kampala", "Seeta Uganda",
    "Jinja Uganda", "Ntinda Kampala", "Najjera Kampala", "Kira Uganda",
]
NICHES = [
    "homes for sale", "Airbnb", "rentals", "hotels", "rooms for rent",
    "hostels", "1 bedroom apartment", "2 bedroom apartment",
]


def _build_queries() -> List[str]:
    # Broadened: reuse the shared category x location list across all platforms.
    queries = Q.build_site_queries("instagram.com")
    # keep a few high-value catch-all signals
    queries += [
        'site:instagram.com "for rent" Uganda',
        'site:instagram.com "for sale" Uganda',
        'site:instagram.com Airbnb Uganda',
        'site:instagram.com booking Uganda WhatsApp',
    ]
    return queries


UG_LOCATIONS = [
    "Kampala", "Ntinda", "Kololo", "Nakasero", "Nakawa", "Lugogo", "Bugolobi",
    "Wandegeya", "Makerere", "Kawempe", "Kikoni", "Nsambya", "Muyenga",
    "Entebbe", "Mukono", "Jinja", "Mbarara", "Gulu", "Kira", "Naalya",
    "Najjera", "Kyanja", "Seeta", "Bukoto", "Munyonyo", "Uganda",
]

CATEGORIES_KW = {
    "airbnb": "Airbnb & Short-Let", "short let": "Airbnb & Short-Let",
    "hostel": "Hostels", "hotel": "Hotels",
    "apartment": "Apartments", "rent": "Rentals", "rental": "Rentals",
    "for sale": "Homes for Sale", "homes for sale": "Homes for Sale",
    "house": "Houses", "land": "Land & Plots", "plot": "Land & Plots",
    "real estate": "Real Estate", "property": "Real Estate",
    "fashion": "Fashion & Clothing", "boutique": "Fashion & Clothing",
    "salon": "Beauty & Cosmetics", "makeup": "Beauty & Cosmetics",
    "restaurant": "Food & Beverages", "cake": "Food & Beverages",
}

SKIP_HANDLES = {
    "p", "explore", "reel", "reels", "stories", "tv", "accounts", "login",
    "signup", "about", "press", "api", "blog", "jobs", "privacy", "legal",
    "cookie", "hashtag", "ar", "challenge", "share", "directory", "web",
}


# ── Field extractors ──────────────────────────────────────────────────────────

def _location(text: str) -> str:
    low = (text or "").lower()
    for loc in UG_LOCATIONS:
        if loc.lower() in low:
            return loc
    return "Uganda"


def _category(text: str, fallback: str = "Business") -> str:
    low = (text or "").lower()
    for kw, cat in CATEGORIES_KW.items():
        if kw in low:
            return cat
    return fallback


def _username_from_url(url: str) -> Optional[str]:
    m = re.search(r"instagram\.com/([^/?&#\s]+)", url or "")
    if not m:
        return None
    handle = m.group(1).lstrip("@")
    if handle.lower() in SKIP_HANDLES or len(handle) < 2:
        return None
    return handle


def _clean_google_url(href: str) -> str:
    try:
        if "google.com/url?" in href:
            qs = parse_qs(urlparse(href).query)
            if "q" in qs:
                href = qs["q"][0]
        return unquote(href)
    except Exception:
        return href


# ── PHASE 1: discover profile URLs via Google ─────────────────────────────────

def discover_instagram(api_key: str = "", target_count: int = 100,
                       progress_cb=None, headless: bool = False) -> List[Dict]:
    """
    Google-search for Uganda Instagram business profiles in a persistent,
    (optionally logged-in) Chrome profile. Returns [{username, profile_url}].

    If Google shows a CAPTCHA / "unusual traffic" page, the VISIBLE window pauses
    and waits up to 180s for you to solve it manually, then continues.
    """
    logger.info("[Instagram/Discover] start — target %s", target_count)
    found: List[Dict] = []
    seen: set = set()
    queries = _build_queries()
    random.shuffle(queries)

    driver = build_driver(PROFILE, headless=headless)
    try:
        for qi, query in enumerate(queries):
            if len(found) >= target_count:
                break
            driver.get("https://www.google.com/search?q=" + quote_plus(query))
            time.sleep(random.uniform(2.5, 4.0))

            # CAPTCHA / consent handling — wait for the human in the visible window
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
                low = href.lower()
                if "instagram.com" not in low:
                    continue
                if any(seg in low for seg in ("/reel/", "/p/", "/explore/", "/popular/")):
                    continue
                username = _username_from_url(href)
                if not username or username.lower() in seen:
                    continue
                seen.add(username.lower())
                found.append({
                    "username": "@" + username,
                    "profile_url": f"https://www.instagram.com/{username}/",
                })
                if progress_cb:
                    progress_cb(len(found), target_count)
            logger.info("[Instagram/Discover] %s -> +%d (total %d)",
                        query[:48], len(found) - before, len(found))
            time.sleep(random.uniform(1.5, 3.0))
    finally:
        _quit(driver)

    logger.info("[Instagram/Discover] done — %d profiles", len(found))
    return found[:target_count]


def _wait_out_google_block(driver, max_wait: int = 60):
    """If Google blocks us, poll until real results appear (human solves CAPTCHA)."""
    waited = 0
    while waited < max_wait:
        url = (driver.current_url or "").lower()
        src = (driver.page_source or "").lower()
        blocked = ("/sorry/" in url or "unusual traffic" in src
                   or "before you continue" in src or "are you a robot" in src)
        if not blocked:
            return
        logger.warning("[Instagram/Discover] Google check — solve it in the window… (%ds)", waited)
        time.sleep(5)
        waited += 5


# ── PHASE 2: scrape each profile directly on instagram.com ────────────────────

def _extract_business_name(driver) -> str:
    for sel in ("//header//h1", "//header//h2", "//main//header//h1",
                "//main//header//span"):
        try:
            el = driver.find_element(By.XPATH, sel)
            txt = (el.text or "").strip()
            if txt:
                return txt
        except Exception:
            pass
    return ""


def _extract_bio_block(driver) -> str:
    try:
        return (driver.find_element(By.TAG_NAME, "header").text or "").strip()
    except Exception:
        try:
            return (driver.find_element(By.TAG_NAME, "body").text or "").strip()
        except Exception:
            return ""


def _meta_description(driver) -> str:
    try:
        el = driver.find_element(By.XPATH, "//meta[@name='description']")
        return el.get_attribute("content") or ""
    except Exception:
        return ""


def _bio_link(text: str) -> str:
    for pat in (r"(https?://[^\s]+)", r"(www\.[^\s]+)"):
        m = re.search(pat, text or "")
        if m:
            return m.group(1).strip()
    return ""


def scrape_instagram_profiles(api_key: str = "", queued: List[Dict] = None,
                              target_count: int = 40, progress_cb=None,
                              headless: bool = False) -> List[Dict]:
    """
    Visit each queued profile DIRECTLY on instagram.com (logged in) and extract
    business name / phone / location / category. queued = [{username, profile_url}].
    """
    queued = queued or []
    logger.info("[Instagram/Scrape] %d queued, target %d", len(queued), target_count)
    results: List[Dict] = []
    seen_phones: set = set()
    seen_users: set = set()

    driver = build_driver(PROFILE, headless=headless)
    try:
        if not instagram_logged_in(driver):
            logger.error(
                "[Instagram/Scrape] NOT logged in to Instagram in this profile. "
                "Run `python login.py instagram` first. Phones will be missing otherwise."
            )

        for item in queued:
            if len(results) >= target_count:
                break

            username = (item.get("username") or "").lstrip("@").strip()
            profile_url = item.get("profile_url") or f"https://www.instagram.com/{username}/"
            if not username or username.lower() in seen_users:
                continue
            seen_users.add(username.lower())

            try:
                driver.get(profile_url)
                time.sleep(random.uniform(4.0, 6.0))

                bio_block = _extract_bio_block(driver)
                meta = _meta_description(driver)
                combined = bio_block + "\n" + meta

                phones = phones_from_text(combined)
                phone = phones[0] if phones else ""
                if phone and phone in seen_phones:
                    phone = ""  # keep the record but avoid dup key collisions
                if phone:
                    seen_phones.add(phone)

                name = _extract_business_name(driver) or ("@" + username)

                rec = {
                    "business_name": name[:120],
                    "username": "@" + username,
                    "category": _category(combined),
                    "phone": phone,
                    "location": _location(combined),
                    "source_url": profile_url,
                }
                results.append(rec)
                if progress_cb:
                    progress_cb(len(results), target_count)
                logger.info("[Instagram/Scrape] [%d] %s | %s",
                            len(results), name[:35], phone or "(no phone)")
            except Exception as e:
                logger.error("[Instagram/Scrape] %s failed: %s", username, e)

            time.sleep(random.uniform(1.5, 3.0))
    finally:
        _quit(driver)

    logger.info("[Instagram/Scrape] done — %d records", len(results))
    return results[:target_count]


# ── Legacy one-shot entry point (scheduler / "Scrape All") ─────────────────────

def scrape_instagram(api_key: str = "", target_count: int = 40,
                     progress_cb=None, headless: bool = False) -> List[Dict]:
    discovered = discover_instagram(api_key, target_count=target_count * 3,
                                    headless=headless)
    if not discovered:
        logger.warning("[Instagram] no profiles discovered.")
        return []
    return scrape_instagram_profiles(api_key, discovered, target_count=target_count,
                                     progress_cb=progress_cb, headless=headless)


def _quit(driver):
    try:
        driver.quit()
    except Exception:
        pass
