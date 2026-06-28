"""
Selenium + undetected-chromedriver scraper for Uganda business listings.

Replaces / augments the Playwright approach in jiji.py.
Uses undetected-chromedriver (uc) to bypass Cloudflare / anti-bot checks,
clicks the "Show Contact" button, waits for the phone number to appear,
then extracts it via regex on the full page text.

Supported platforms
-------------------
  • Jiji Uganda  (jiji.ug)        — primary target, has "Show Contact" button
  • Facebook     (facebook.com)   — public business pages with "Contact" section
  • Instagram    (instagram.com)  — bio phone numbers via third-party viewers

Usage
-----
  from scrapers.selenium_scraper import (
      scrape_jiji_selenium,
      scrape_facebook_selenium,
      scrape_instagram_selenium,
  )

  results = scrape_jiji_selenium(urls=["https://jiji.ug/..."])
"""

from __future__ import annotations

import re
import time
import random
import logging
from typing import List, Dict, Optional

logger = logging.getLogger(__name__)

# ── Phone helpers ─────────────────────────────────────────────────────────────

PHONE_RE = re.compile(
    r'(\+?256[\s\-]?\d{3}[\s\-]?\d{3}[\s\-]?\d{3}|\b0[37]\d{8}|\b07\d{8}|\b08\d{8})'
)

UG_CITIES = [
    "Kampala", "Ntinda", "Kololo", "Nakasero", "Nakawa", "Lugogo",
    "Bugolobi", "Wandegeya", "Makerere", "Kawempe", "Kikuubo",
    "Nsambya", "Muyenga", "Entebbe", "Mukono", "Jinja", "Mbarara",
    "Gulu", "Kira", "Naalya", "Mbale", "Lira", "Arua", "Fort Portal",
    "Masaka", "Wakiso", "Hoima", "Makindye", "Rubaga", "Bunga",
    "Kyambogo", "Central Division", "Uganda",
]

CATEGORY_MAP = [
    (["shoes", "footwear", "sneakers", "sandals", "heels", "boots"],          "Shoes"),
    (["bags", "handbag", "purse", "backpack"],                                "Bags"),
    (["sofa", "furniture", "decor", "curtain", "rug", "mattress"],            "Furniture"),
    (["perfume", "fragrance", "cologne"],                                     "Perfumes"),
    (["men fashion", "suits", "shirt men"],                                   "Men's Fashion"),
    (["ladies", "women fashion", "dress", "skirt", "blouse"],                 "Ladies' Fashion"),
    (["gomesi", "traditional wear"],                                          "Gomesi"),
    (["kitenge", "african wear", "ankara"],                                   "Kitenge/African Wear"),
    (["bridal", "wedding dress", "wedding gown"],                             "Bridal/Wedding Attire"),
    (["cake", "bakery", "baking"],                                            "Cakes"),
    (["catering", "food delivery"],                                           "Catering & Food Delivery"),
    (["fast food", "restaurant", "takeaway"],                                 "Fast Food"),
    (["gym", "fitness", "workout"],                                           "Fitness/Gym"),
    (["nails", "manicure", "pedicure"],                                       "Nails"),
    (["hair salon", "barber", "weave", "braids"],                             "Hair"),
    (["makeup", "lashes", "cosmetics", "skincare"],                           "Makeup & Lashes"),
    (["phones", "mobile", "smartphone", "tablet"],                            "Phones & Accessories"),
    (["laptop", "computer", "pc", "desktop"],                                 "Laptops & Computers"),
    (["solar", "panel", "inverter"],                                          "Solar Equipment"),
    (["gadget", "electronics", "appliance"],                                  "Gadgets & Electronics"),
    (["car hire", "self-drive", "car rental"],                                "Car Hire / Self-Drive"),
    (["car", "vehicle", "truck", "toyota", "land cruiser"],                   "Cars"),
    (["land", "plot", "acre"],                                                "Land & Plots"),
    (["airbnb", "short let"],                                                 "Airbnb & Short-Let"),
    (["house", "apartment", "flat", "rental"],                                "Houses"),
    (["real estate", "property"],                                             "Real Estate"),
    (["photography", "videography"],                                          "Photography"),
    (["printing", "graphic design", "branding"],                              "Printing & Design"),
    (["party hire", "dj", "sound system"],                                    "Events & Entertainment"),
    (["tourism", "tour", "safari", "travel"],                                 "Tourism"),
    (["delivery", "errand", "courier"],                                       "Delivery Services"),
    (["cleaning", "laundry", "housekeeping"],                                 "Cleaning Services"),
    (["fashion", "clothing", "clothes", "wear", "outfit"],                    "Fashion"),
]


def _clean_phone(raw: str) -> str:
    d = re.sub(r"[^\d+]", "", raw or "")
    if d.startswith("256") and len(d) >= 12:
        return "+" + d
    if len(d) == 10 and d.startswith("0"):
        return "+256" + d[1:]
    return d if len(d) >= 9 else ""


def _phones_from_text(text: str) -> List[str]:
    seen, result = set(), []
    for m in PHONE_RE.findall(text or ""):
        c = _clean_phone(re.sub(r"\s", "", m))
        if c and c not in seen:
            seen.add(c)
            result.append(c)
    return result


def _map_category(text: str) -> str:
    low = (text or "").lower()
    for keywords, cat in CATEGORY_MAP:
        if any(kw in low for kw in keywords):
            return cat
    return "Business"


def _clean_location(raw: str) -> str:
    if not raw:
        return "Uganda"
    clean = re.sub(
        r",?\s*\d+\s+(?:hour|day|minute|second|week|month)s?\s+ago.*",
        "", raw, flags=re.IGNORECASE,
    ).strip().strip(",").strip()
    for city in UG_CITIES:
        if city.lower() in clean.lower():
            return city
    return clean[:40] or "Uganda"


# ── Driver factory ────────────────────────────────────────────────────────────

def _build_driver(headless: bool = True):
    """
    Returns an undetected-chromedriver instance.
    Falls back to plain selenium if uc is not installed.
    """
    try:
        import undetected_chromedriver as uc  # pip install undetected-chromedriver
        options = uc.ChromeOptions()
        if headless:
            options.add_argument("--headless=new")
        options.add_argument("--no-sandbox")
        options.add_argument("--disable-dev-shm-usage")
        options.add_argument("--disable-gpu")
        options.add_argument("--window-size=1280,900")
        options.add_argument(
            "--user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/124.0.0.0 Safari/537.36"
        )
        driver = uc.Chrome(options=options, use_subprocess=True)
        logger.info("[Selenium] Using undetected-chromedriver ✓")
        return driver

    except ImportError:
        logger.warning("[Selenium] undetected-chromedriver not found — falling back to selenium")
        from selenium import webdriver
        from selenium.webdriver.chrome.options import Options
        from selenium.webdriver.chrome.service import Service

        try:
            from webdriver_manager.chrome import ChromeDriverManager
            service = Service(ChromeDriverManager().install())
        except ImportError:
            service = Service()

        opts = Options()
        if headless:
            opts.add_argument("--headless=new")
        opts.add_argument("--no-sandbox")
        opts.add_argument("--disable-dev-shm-usage")
        opts.add_argument("--disable-gpu")
        opts.add_argument("--window-size=1280,900")
        opts.add_experimental_option("excludeSwitches", ["enable-automation"])
        opts.add_experimental_option("useAutomationExtension", False)
        opts.add_argument(
            "--user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/124.0.0.0 Safari/537.36"
        )
        driver = webdriver.Chrome(service=service, options=opts)
        driver.execute_cdp_cmd(
            "Page.addScriptToEvaluateOnNewDocument",
            {"source": "Object.defineProperty(navigator,'webdriver',{get:()=>undefined})"},
        )
        logger.info("[Selenium] Using plain selenium webdriver")
        return driver


# ── Jiji scraper ──────────────────────────────────────────────────────────────

# All CSS selectors tried in order for the "Show Contact" button on jiji.ug
JIJI_SHOW_CONTACT_SELECTORS = [
    ".b-show-contact",
    ".qa-show-contact",
    "[class*='show-contact']",
    "button[class*='contact']",
    "a[class*='contact']",
    ".b-advert-contact__button",
    "[data-testid='show-contact-button']",
    "button.b-contact-seller__btn",
]

# Selectors for the revealed phone element (after clicking)
JIJI_PHONE_SELECTORS = [
    ".b-contact-seller__phone",
    ".qa-phone-number",
    "[class*='phone-number']",
    ".b-advert-contact__phone",
    "a[href^='tel:']",
]

# Seller name selectors
JIJI_SELLER_SELECTORS = [
    ".b-seller__name",
    ".b-advert-seller-other__name",
    ".qa-seller-name",
    ".b-seller-block__name",
    "[data-testid='seller-name']",
]

# Location selectors
JIJI_LOCATION_SELECTORS = [
    "[class*='location']",
    ".b-advert-title__region",
    ".qa-advert-location",
    ".b-advert__region",
]


def _scrape_jiji_listing_selenium(driver, url: str) -> dict:
    """
    Open one Jiji listing URL, click "Show Contact", extract phone + metadata.
    Returns a dict with keys: phones, seller_name, location, breadcrumb.
    """
    from selenium.webdriver.common.by import By
    from selenium.webdriver.support.ui import WebDriverWait
    from selenium.webdriver.support import expected_conditions as EC
    from selenium.common.exceptions import (
        TimeoutException, NoSuchElementException, ElementClickInterceptedException,
    )

    result = {"phones": [], "seller_name": "", "location": "Uganda", "breadcrumb": ""}

    try:
        driver.get(url)
        time.sleep(random.uniform(2.5, 4.0))  # let JS render

        # ── 1. Close cookie / modal overlays if present ───────────────────────
        for close_sel in ["[class*='modal'] button[class*='close']",
                          "[class*='cookie'] button", ".b-popup__close"]:
            try:
                btn = driver.find_element(By.CSS_SELECTOR, close_sel)
                if btn.is_displayed():
                    btn.click()
                    time.sleep(0.5)
            except (NoSuchElementException, Exception):
                pass

        # ── 2. Click "Show Contact" ───────────────────────────────────────────
        clicked = False
        for sel in JIJI_SHOW_CONTACT_SELECTORS:
            try:
                btn = WebDriverWait(driver, 5).until(
                    EC.element_to_be_clickable((By.CSS_SELECTOR, sel))
                )
                driver.execute_script("arguments[0].scrollIntoView(true);", btn)
                time.sleep(0.3)
                try:
                    btn.click()
                except ElementClickInterceptedException:
                    driver.execute_script("arguments[0].click();", btn)
                clicked = True
                logger.debug(f"[Jiji/Selenium] Clicked contact btn via: {sel}")
                break
            except (TimeoutException, NoSuchElementException):
                continue

        if clicked:
            time.sleep(random.uniform(2.5, 3.5))  # wait for AJAX phone reveal

        # ── 3. Try dedicated phone element first ─────────────────────────────
        phones_found: List[str] = []
        for sel in JIJI_PHONE_SELECTORS:
            try:
                els = driver.find_elements(By.CSS_SELECTOR, sel)
                for el in els:
                    txt = (el.get_attribute("href") or el.text or "").replace("tel:", "")
                    c = _clean_phone(txt)
                    if c and c not in phones_found:
                        phones_found.append(c)
            except Exception:
                pass

        # ── 4. Fallback: regex over full page text ────────────────────────────
        if not phones_found:
            body_text = driver.find_element(By.TAG_NAME, "body").text
            phones_found = _phones_from_text(body_text)

        result["phones"] = phones_found

        # ── 5. Seller name ────────────────────────────────────────────────────
        for sel in JIJI_SELLER_SELECTORS:
            try:
                el = driver.find_element(By.CSS_SELECTOR, sel)
                name = (el.text or "").strip()
                if name:
                    result["seller_name"] = name
                    break
            except NoSuchElementException:
                pass

        # ── 6. Location ───────────────────────────────────────────────────────
        for sel in JIJI_LOCATION_SELECTORS:
            try:
                el = driver.find_element(By.CSS_SELECTOR, sel)
                txt = (el.text or "").strip()
                if txt:
                    result["location"] = _clean_location(txt)
                    break
            except NoSuchElementException:
                pass

        # ── 7. Breadcrumb for category ────────────────────────────────────────
        try:
            crumbs = driver.find_elements(
                By.CSS_SELECTOR, "[class*='breadcrumb'] a, nav a"
            )
            result["breadcrumb"] = " ".join(a.text for a in crumbs if a.text).strip()
        except Exception:
            pass

    except Exception as e:
        logger.error(f"[Jiji/Selenium] Error on {url}: {e}")

    return result


def scrape_jiji_selenium(
    urls: List[str],
    headless: bool = True,
    delay: tuple = (1.5, 2.5),
    progress_cb=None,
) -> List[Dict]:
    """
    Scrape a list of Jiji Uganda listing URLs using Selenium.

    Parameters
    ----------
    urls        : list of jiji.ug listing URLs to scrape
    headless    : run Chrome without a visible window (default True)
    delay       : (min, max) seconds to wait between listings
    progress_cb : optional callable(done, total) for progress reporting

    Returns
    -------
    List of dicts with keys:
        business_name, phone, category, location, source_url
    """
    results: List[Dict] = []
    seen_phones: set = set()
    seen_urls: set = set()

    driver = _build_driver(headless=headless)
    try:
        for i, url in enumerate(urls):
            if url in seen_urls:
                continue
            seen_urls.add(url)

            logger.info(f"[Jiji/Selenium] [{i+1}/{len(urls)}] {url[20:80]}")
            data = _scrape_jiji_listing_selenium(driver, url)

            phones = data.get("phones", [])
            phone = ", ".join(phones[:2])
            name = data.get("seller_name") or ""
            cat_text = data.get("breadcrumb", "") + " " + url

            if not name and not phone:
                logger.debug(f"[Jiji/Selenium] No data — skipping {url}")
            else:
                key = phone or url
                if key not in seen_phones:
                    if phone:
                        seen_phones.add(phone)
                    rec = {
                        "business_name": name[:80],
                        "username": "",
                        "phone": phone,
                        "category": _map_category(cat_text),
                        "location": data.get("location", "Uganda"),
                        "source_url": url,
                    }
                    results.append(rec)
                    logger.info(
                        f"[Jiji/Selenium]   ✓ {name[:30]!r} | {phone}"
                    )
                    if progress_cb:
                        progress_cb(len(results), len(urls))

            time.sleep(random.uniform(*delay))

    finally:
        try:
            driver.quit()
        except Exception:
            pass

    logger.info(f"[Jiji/Selenium] Done — {len(results)} records.")
    return results


# ── Facebook public business page scraper ────────────────────────────────────

FB_CONTACT_SELECTORS = [
    "a[href^='tel:']",
    "[aria-label*='Call']",
    "[aria-label*='Phone']",
    "span[class*='phone']",
    "div[class*='contact'] a",
]


def _scrape_facebook_page_selenium(driver, url: str) -> dict:
    """
    Visit a public Facebook business page's /about section
    and extract phone numbers.
    """
    from selenium.webdriver.common.by import By
    from selenium.common.exceptions import NoSuchElementException

    result = {"phones": [], "name": "", "location": "Uganda"}

    # Navigate to /about for contact info
    about_url = url.rstrip("/") + "/about"
    try:
        driver.get(about_url)
        time.sleep(random.uniform(3.0, 5.0))

        # Try dedicated phone elements
        for sel in FB_CONTACT_SELECTORS:
            try:
                els = driver.find_elements(By.CSS_SELECTOR, sel)
                for el in els:
                    txt = (el.get_attribute("href") or el.text or "").replace("tel:", "")
                    c = _clean_phone(txt)
                    if c and c not in result["phones"]:
                        result["phones"].append(c)
            except Exception:
                pass

        # Fallback: regex on body
        if not result["phones"]:
            body = driver.find_element(By.TAG_NAME, "body").text
            result["phones"] = _phones_from_text(body)

        # Page title = business name
        try:
            result["name"] = driver.title.replace(" | Facebook", "").strip()
        except Exception:
            pass

        # Location
        for loc in UG_CITIES:
            try:
                body_text = driver.find_element(By.TAG_NAME, "body").text
                if loc.lower() in body_text.lower():
                    result["location"] = loc
                    break
            except Exception:
                pass

    except Exception as e:
        logger.error(f"[Facebook/Selenium] Error on {url}: {e}")

    return result


def scrape_facebook_selenium(
    page_urls: List[str],
    headless: bool = True,
    delay: tuple = (2.0, 4.0),
    progress_cb=None,
) -> List[Dict]:
    """
    Scrape Facebook public business page URLs for phone numbers.

    Note: Facebook's /about page is public for business pages
    that have chosen to display contact info publicly.
    """
    results: List[Dict] = []
    seen: set = set()

    driver = _build_driver(headless=headless)
    try:
        for i, url in enumerate(page_urls):
            logger.info(f"[Facebook/Selenium] [{i+1}/{len(page_urls)}] {url}")
            data = _scrape_facebook_page_selenium(driver, url)

            phone = ", ".join(data.get("phones", [])[:2])
            name = data.get("name", "")

            if phone and phone not in seen:
                seen.add(phone)
                results.append({
                    "business_name": name[:80],
                    "username": "",
                    "phone": phone,
                    "category": _map_category(url + " " + name),
                    "location": data.get("location", "Uganda"),
                    "source_url": url,
                })
                logger.info(f"[Facebook/Selenium]   ✓ {name[:30]!r} | {phone}")
                if progress_cb:
                    progress_cb(len(results), len(page_urls))

            time.sleep(random.uniform(*delay))
    finally:
        try:
            driver.quit()
        except Exception:
            pass

    logger.info(f"[Facebook/Selenium] Done — {len(results)} records.")
    return results


# ── Instagram via third-party viewer ─────────────────────────────────────────

IG_VIEWERS = [
    "https://imginn.com/{username}/",
    "https://www.picuki.com/profile/{username}",
]


def _scrape_instagram_via_viewer(driver, username: str) -> dict:
    """
    Try public Instagram viewer sites (no login needed) to get bio + phone.
    """
    from selenium.webdriver.common.by import By

    result = {"phones": [], "bio": "", "name": username}

    for template in IG_VIEWERS:
        url = template.format(username=username)
        try:
            driver.get(url)
            time.sleep(random.uniform(3.0, 5.0))
            body = driver.find_element(By.TAG_NAME, "body").text
            phones = _phones_from_text(body)
            if phones:
                result["phones"] = phones
                # Try to get display name
                try:
                    h1 = driver.find_element(By.TAG_NAME, "h1")
                    result["name"] = (h1.text or username).strip()
                except Exception:
                    pass
                break
        except Exception as e:
            logger.debug(f"[Instagram/Selenium] Viewer {url} failed: {e}")
            continue

    return result


def scrape_instagram_selenium(
    usernames: List[str],
    headless: bool = True,
    delay: tuple = (2.0, 4.0),
    progress_cb=None,
) -> List[Dict]:
    """
    Scrape Instagram business profiles for phone numbers using public viewers.
    Does NOT require Instagram login.

    Parameters
    ----------
    usernames : list of Instagram usernames (without @)
    """
    results: List[Dict] = []
    seen: set = set()

    driver = _build_driver(headless=headless)
    try:
        for i, username in enumerate(usernames):
            username = username.lstrip("@").strip()
            logger.info(f"[Instagram/Selenium] [{i+1}/{len(usernames)}] @{username}")
            data = _scrape_instagram_via_viewer(driver, username)

            phone = ", ".join(data.get("phones", [])[:2])
            if phone and phone not in seen:
                seen.add(phone)
                results.append({
                    "business_name": data.get("name", username)[:80],
                    "username": username,
                    "phone": phone,
                    "category": "Business",
                    "location": "Uganda",
                    "source_url": f"https://www.instagram.com/{username}/",
                })
                logger.info(f"[Instagram/Selenium]   ✓ @{username} | {phone}")
                if progress_cb:
                    progress_cb(len(results), len(usernames))

            time.sleep(random.uniform(*delay))
    finally:
        try:
            driver.quit()
        except Exception:
            pass

    logger.info(f"[Instagram/Selenium] Done — {len(results)} records.")
    return results


# ── Convenience wrapper: auto-detect URL type ─────────────────────────────────

def scrape_urls_selenium(
    urls: List[str],
    headless: bool = True,
    progress_cb=None,
) -> List[Dict]:
    """
    Dispatch a mixed list of URLs to the right Selenium scraper by domain.

    Supported:
      jiji.ug       → scrape_jiji_selenium
      facebook.com  → scrape_facebook_selenium
      instagram.com → converts to username list → scrape_instagram_selenium
    """
    jiji_urls, fb_urls, ig_usernames, other = [], [], [], []

    for url in urls:
        u = url.lower()
        if "jiji.ug" in u:
            jiji_urls.append(url)
        elif "facebook.com" in u or "fb.com" in u:
            fb_urls.append(url)
        elif "instagram.com" in u:
            m = re.search(r"instagram\.com/([^/?&#\s/]+)", url)
            if m:
                ig_usernames.append(m.group(1))
        else:
            other.append(url)

    if other:
        logger.warning(f"[Selenium] {len(other)} URL(s) not handled: {other[:3]}")

    all_results: List[Dict] = []
    if jiji_urls:
        all_results += scrape_jiji_selenium(jiji_urls, headless=headless, progress_cb=progress_cb)
    if fb_urls:
        all_results += scrape_facebook_selenium(fb_urls, headless=headless, progress_cb=progress_cb)
    if ig_usernames:
        all_results += scrape_instagram_selenium(ig_usernames, headless=headless, progress_cb=progress_cb)

    return all_results


# ── Quick CLI test ─────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import json
    logging.basicConfig(level=logging.INFO, format="%(message)s")

    # Replace with real Jiji listing URLs to test
    TEST_URLS = [
        # "https://jiji.ug/kampala/phones-tablets/...-XXXXXXXXXXXXXXXXXXXX.html",
    ]

    if not TEST_URLS:
        print(
            "Add at least one Jiji listing URL to TEST_URLS to run a quick test.\n"
            "Example:\n"
            "  python -m scrapers.selenium_scraper\n"
        )
    else:
        results = scrape_jiji_selenium(TEST_URLS, headless=True)
        print(json.dumps(results, indent=2, ensure_ascii=False))
