"""
Jiji Uganda Business Scraper — logged-in, direct-site (Selenium).

REPLACES the old Firecrawl-discovery + headless-Playwright approach (which got
blocked by Cloudflare and returned no phones). Ports Nicole's working notebook
(scraper_jiji.ipynb):

  • discover_jiji()          <- notebook cell 1
        Search jiji.ug/search?query=<category>, page through results, collect
        listing (.html) URLs in a persistent Chrome profile.

  • scrape_jiji_listings()   <- notebook cell 3
        Open each listing (logged in), click the "Show contact" button
        (a.qa-show-contact), then read the revealed tel: links for phone numbers,
        plus seller name / location / category.

Login persists via browser_profiles/jiji  (run `python login.py jiji` once).
`api_key` args are kept but unused so app.py needs no changes.
"""

from __future__ import annotations

import re
import time
import random
import logging
from typing import List, Dict

from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC

from .browser import build_driver, phones_from_text, clean_phone
from . import queries as Q

import config

logger = logging.getLogger(__name__)

PROFILE = "jiji"

# ── Discovery categories (ported from the notebook) ───────────────────────────
CATEGORIES = [
    "building materials", "cement", "roofing sheets", "tiles", "hardware store",
    "cake ingredients", "baking equipment", "cake supplies",
    "kitchen appliances", "cookware", "restaurant equipment", "home appliances",
    "solar equipment", "solar panels", "inverters",
    "cars", "used cars", "car dealership",
    "land for sale", "plots for sale", "houses for sale", "houses for rent",
    "property for rent", "real estate", "office space", "shops for rent",
    "airbnb kampala", "airbnb entebbe", "short stay apartments",
    "furnished apartments", "vacation rentals",
    "delivery services", "courier services",
    "printing services", "graphic design", "branding services",
    "party hire", "event hire", "dj services", "event planning",
    "photography", "videography", "wedding photography",
    "car hire", "self drive", "car rental", "tourism", "travel agency", "safaris",
    "groceries", "organic food", "fresh produce",
    "flowers", "flower delivery", "bouquets",
    "pets", "pet shop", "pet food",
]

CATEGORY_MAP = [
    (["shoes", "footwear", "sneakers", "sandals", "heels", "boots"],          "Shoes"),
    (["bags", "handbag", "purse", "suitcase", "backpack"],                    "Bags"),
    (["sofa", "furniture", "decor", "curtain", "rug", "mattress"],            "Furniture"),
    (["building", "cement", "roofing", "tiles", "hardware", "construction"],  "Building & Construction"),
    (["cake", "bakery", "baking"],                                            "Cakes & Baking"),
    (["kitchen", "cookware", "appliance"],                                    "Kitchen & Appliances"),
    (["solar", "panel", "inverter"],                                          "Solar Equipment"),
    (["car hire", "self drive", "self-drive", "car rental"],                  "Car Hire / Self-Drive"),
    (["car", "vehicle", "truck", "toyota", "land cruiser"],                   "Cars"),
    (["land", "plot", "acre"],                                                "Land & Plots"),
    (["airbnb", "short let", "short stay", "vacation", "furnished apartment"], "Airbnb & Short-Stay"),
    (["house", "apartment", "flat", "rent", "office space", "shop"],          "Houses & Rentals"),
    (["real estate", "property"],                                            "Real Estate"),
    (["photography", "videography", "camera"],                               "Photography & Videography"),
    (["printing", "graphic design", "branding", "signage"],                  "Printing & Branding"),
    (["party hire", "event", "dj", "sound"],                                 "Events & Entertainment"),
    (["tourism", "tour", "safari", "travel"],                                "Tourism & Travel"),
    (["delivery", "errand", "courier", "parcel"],                            "Delivery & Courier"),
    (["organic", "groceries", "fresh produce", "farmers"],                   "Groceries & Farm Produce"),
    (["flower", "bouquet", "florist"],                                       "Flowers"),
    (["pet", "dog", "cat", "puppy", "kitten"],                               "Pets"),
]

UG_CITIES = [
    "Kampala", "Ntinda", "Kololo", "Nakasero", "Nakawa", "Lugogo", "Bugolobi",
    "Wandegeya", "Makerere", "Kawempe", "Kikuubo", "Nsambya", "Muyenga",
    "Entebbe", "Mukono", "Jinja", "Mbarara", "Gulu", "Kira", "Naalya", "Mbale",
    "Lira", "Arua", "Fort Portal", "Masaka", "Wakiso", "Hoima", "Makindye",
    "Rubaga", "Bunga", "Kyambogo",
]

MAX_PAGES_PER_CATEGORY = config.JIJI_MAX_PAGES_PER_CATEGORY


def _daily_seed() -> int:
    """Seed that changes every calendar day so discovery rotates daily."""
    import datetime as _dt
    return int(_dt.date.today().strftime("%Y%m%d"))


def _build_daily_queries() -> List[tuple]:
    """
    Build a rotated list of (search_term, category) for discovery.

    Two reasons this surfaces NEW businesses each day rather than the same top
    ads: (1) the category order is shuffled with a per-day seed, so different
    categories are searched first before the target count is hit; (2) a rotating
    subset of categories is combined with Ugandan cities (e.g. "hardware store
    Mbarara"), reaching listings the bare category search never reaches.
    """
    rnd  = random.Random(_daily_seed())
    cats = Q.CATEGORIES[:]          # broadened shared category list
    rnd.shuffle(cats)
    cities = Q.LOCATIONS[:]         # broadened shared location list
    rnd.shuffle(cities)

    queries: List[tuple] = [(c, c) for c in cats]
    # Add category x city combinations for a rotating subset.
    for c in cats[:24]:
        for city in cities[:4]:
            queries.append((f"{c} {city}", c))
    return queries


def _map_category(text: str) -> str:
    low = (text or "").lower()
    for keywords, cat in CATEGORY_MAP:
        if any(kw in low for kw in keywords):
            return cat
    return "Business"


def _clean_location(raw: str) -> str:
    if not raw:
        return "Uganda"
    clean = re.sub(r",?\s*\d+\s+(?:hour|day|minute|second|week|month)s?\s+ago.*",
                   "", raw, flags=re.IGNORECASE).strip().strip(",").strip()
    for city in UG_CITIES:
        if city.lower() in clean.lower():
            return city
    return clean[:40] or "Uganda"


def _is_listing(url: str) -> bool:
    return bool(url) and "jiji.ug" in url and ".html" in url


# ── PHASE 1: discover listing URLs ────────────────────────────────────────────

def discover_jiji(api_key: str = "", target_count: int = 120,
                  progress_cb=None, headless: bool = False) -> List[Dict]:
    """
    Search jiji.ug categories and collect listing (.html) URLs.
    Returns [{listing_url, title, category}].
    """
    logger.info("[Jiji/Discover] start — target %s", target_count)
    found: List[Dict] = []
    seen: set = set()

    queries = _build_daily_queries()
    driver = build_driver(PROFILE, headless=headless)
    try:
        for search_term, category in queries:
            if len(found) >= target_count:
                break
            search_url = "https://jiji.ug/search?query=" + search_term.replace(" ", "+")
            try:
                driver.get(search_url)
                time.sleep(random.uniform(4.0, 6.0))
            except Exception as e:
                logger.warning("[Jiji/Discover] %s nav failed: %s", search_term, e)
                continue

            for _ in range(MAX_PAGES_PER_CATEGORY):
                if len(found) >= target_count:
                    break
                time.sleep(random.uniform(2.0, 3.5))
                before = len(found)
                for link in driver.find_elements(By.TAG_NAME, "a"):
                    try:
                        href = link.get_attribute("href")
                    except Exception:
                        continue   # element went stale as the SPA re-rendered
                    if not _is_listing(href) or href in seen:
                        continue
                    seen.add(href)
                    found.append({
                        "listing_url": href,
                        "title": (link.text or "").strip()[:120],
                        "category": category,
                    })
                    if progress_cb:
                        progress_cb(len(found), target_count)
                    if len(found) >= target_count:
                        break
                logger.info("[Jiji/Discover] %s -> +%d (total %d)",
                            category, len(found) - before, len(found))

                # next page
                try:
                    nxt = driver.find_element(By.CSS_SELECTOR, "[aria-label='Next Page']")
                    driver.execute_script("arguments[0].click();", nxt)
                    time.sleep(random.uniform(2.5, 4.0))
                except Exception:
                    break
    finally:
        _quit(driver)

    logger.info("[Jiji/Discover] done — %d listings", len(found))
    return found[:target_count]


# ── PHASE 2: scrape each listing (click Show Contact) ─────────────────────────

def _scrape_listing(driver, url: str, hint_category: str = "") -> dict:
    out = {"business_name": "", "phone": "", "location": "Uganda", "category": ""}
    driver.get(url)
    WebDriverWait(driver, 15).until(
        EC.presence_of_element_located((By.TAG_NAME, "body"))
    )
    time.sleep(random.uniform(3.0, 4.5))

    # Business / seller name
    for sel in (".b-seller-block__name", ".b-seller__name",
                ".b-advert-seller-other__name", ".qa-seller-name"):
        try:
            txt = (driver.find_element(By.CSS_SELECTOR, sel).text or "").strip()
            if txt:
                out["business_name"] = txt[:120]
                break
        except Exception:
            pass

    # Location
    for sel in (".b-advert-info-statistics--region", "[class*='location']",
                ".b-advert-title__region", ".qa-advert-location"):
        try:
            txt = (driver.find_element(By.CSS_SELECTOR, sel).text or "").strip()
            if txt:
                out["location"] = _clean_location(txt)
                break
        except Exception:
            pass

    # Category — from URL path, fall back to category hint / title
    try:
        parts = url.split("/")
        url_cat = parts[3] if len(parts) > 3 else ""
    except Exception:
        url_cat = ""
    out["category"] = _map_category(
        " ".join([url_cat.replace("-", " "), hint_category, out["business_name"]])
    )

    # Phone — click "Show contact", then read tel: links
    phones: List[str] = []
    try:
        btn = WebDriverWait(driver, 10).until(
            EC.element_to_be_clickable((By.CSS_SELECTOR, "a.qa-show-contact"))
        )
        driver.execute_script("arguments[0].click();", btn)
        time.sleep(random.uniform(2.5, 3.5))
    except Exception:
        # button may have a different class on some templates
        for sel in (".b-show-contact", "[class*='show-contact']",
                    "button[class*='contact']"):
            try:
                b = driver.find_element(By.CSS_SELECTOR, sel)
                driver.execute_script("arguments[0].click();", b)
                time.sleep(2.5)
                break
            except Exception:
                pass

    try:
        for a in driver.find_elements(By.CSS_SELECTOR, "a[href^='tel:']"):
            raw = (a.get_attribute("href") or "").replace("tel:", "")
            c = clean_phone(raw)
            if c and c not in phones:
                phones.append(c)
    except Exception:
        pass

    if not phones:  # fallback: regex the whole page
        try:
            body = driver.find_element(By.TAG_NAME, "body").text
            phones = phones_from_text(body)
        except Exception:
            pass

    out["phone"] = ", ".join(phones[:2])
    return out


def scrape_jiji_listings(api_key: str = "", queued: List[Dict] = None,
                         target_count: int = 40, progress_cb=None,
                         headless: bool = False) -> List[Dict]:
    """
    Scrape queued Jiji listings for phone + metadata.
    queued = [{listing_url, title, category}].
    """
    queued = queued or []
    logger.info("[Jiji/Scrape] %d queued, target %d", len(queued), target_count)
    results: List[Dict] = []
    seen_phones: set = set()
    seen_urls: set = set()

    driver = build_driver(PROFILE, headless=headless)
    try:
        # Warm-up so Cloudflare/login cookies apply before the first listing.
        try:
            driver.get("https://jiji.ug/")
            time.sleep(5)
        except Exception:
            pass

        for item in queued:
            if len(results) >= target_count:
                break
            url = item.get("listing_url", "")
            if not _is_listing(url) or url in seen_urls:
                continue
            seen_urls.add(url)

            try:
                data = _scrape_listing(driver, url, item.get("category", ""))
            except Exception as e:
                logger.error("[Jiji/Scrape] %s failed: %s", url[20:70], e)
                continue

            name = data["business_name"] or (item.get("title", "") or "")[:120]
            phone = data["phone"]
            if not name and not phone:
                continue
            if phone and phone in seen_phones:
                continue
            if phone:
                seen_phones.add(phone)

            results.append({
                "business_name": name,
                "username": "",
                "phone": phone,
                "category": data["category"],
                "location": data["location"],
                "source_url": url,
            })
            if progress_cb:
                progress_cb(len(results), target_count)
            logger.info("[Jiji/Scrape] [%d] %s | %s",
                        len(results), name[:35], phone or "(no phone)")
            time.sleep(random.uniform(2.0, 3.5))
    finally:
        _quit(driver)

    logger.info("[Jiji/Scrape] done — %d records", len(results))
    return results[:target_count]


# ── Legacy one-shot entry point ───────────────────────────────────────────────

def scrape_jiji(api_key: str = "", target_count: int = 40,
                progress_cb=None, headless: bool = False) -> List[Dict]:
    discovered = discover_jiji(api_key, target_count=target_count * 3, headless=headless)
    if not discovered:
        return []
    return scrape_jiji_listings(api_key, discovered, target_count=target_count,
                                progress_cb=progress_cb, headless=headless)


def _quit(driver):
    try:
        driver.quit()
    except Exception:
        pass
