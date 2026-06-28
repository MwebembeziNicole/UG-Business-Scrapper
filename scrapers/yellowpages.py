"""
Yellow Pages Uganda scraper — static HTML (requests + BeautifulSoup).

Site: https://www.yellowpages-uganda.com

WHY THIS ONE IS SIMPLE
----------------------
Unlike Jiji/Instagram, Yellow Pages Uganda is a plain server-rendered WordPress
(GeoDirectory) site. No login, no JavaScript, no anti-bot. A normal HTTP GET
returns the full listing cards, and every field we want is already on the
category page — no need to open each business's detail page.

FLOW
----
  discover_yellowpages():  read /location -> all category URLs (+ counts)
  scrape_yellowpages():    for each category, page through ?bdp_page=N and parse
                           each listing card.

Fields per business:
  business_name, category, email, location (address), website, facebook,
  source_url (the listing's detail URL).

Signatures keep an unused `api_key` arg so app.py's generic scrape path works
unchanged. `target_count` is treated as a safety cap; by default it crawls the
whole site, so the dashboard's "Scrape Now" collects every category.
"""

from __future__ import annotations

import re
import time
import logging
from typing import List, Dict, Tuple
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup

logger = logging.getLogger(__name__)

BASE = "https://www.yellowpages-uganda.com"
LOCATION_URL = BASE + "/location"
HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
    )
}

EMAIL_RE = re.compile(r"[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}")
# Yellow Pages does not publish a phone field, but a few listings include a
# Ugandan mobile number in their description/address. This best-effort regex
# captures those when present (no login, no extra requests).
PHONE_RE = re.compile(r"(?:\+?256|0)[\s\-]?7\d{2}[\s\-]?\d{3}[\s\-]?\d{3}")
MAX_PAGES_PER_CATEGORY = 60          # safety cap
REQUEST_TIMEOUT = 30
DELAY = 1.0                          # polite delay between requests


# ── HTTP ──────────────────────────────────────────────────────────────────────

def _get(url: str, session: requests.Session) -> str:
    try:
        r = session.get(url, headers=HEADERS, timeout=REQUEST_TIMEOUT)
        if r.status_code == 200:
            return r.text
        logger.warning("[YellowPages] HTTP %s for %s", r.status_code, url)
    except Exception as e:
        logger.warning("[YellowPages] request failed %s: %s", url, e)
    return ""


# ── Field parsing helpers ─────────────────────────────────────────────────────

def _clean(text: str) -> str:
    return re.sub(r"\s+", " ", (text or "").replace("\xa0", " ")).strip()


def _is_business_url(href: str) -> bool:
    """Detail listing URLs look like /listings/uganda/<region>/<city>/<cat>/<slug>/."""
    if not href or "/listings/uganda/" not in href:
        return False
    tail = href.split("/listings/uganda/", 1)[1].rstrip("/")
    return tail.count("/") >= 3  # region/city/category/slug


def _card_container(title_anchor):
    """Ascend from a title <a> to the smallest ancestor that also holds the
    'Category:' label — that element is the listing card."""
    node = title_anchor
    for _ in range(8):
        node = node.parent
        if node is None:
            break
        if "Category:" in node.get_text():
            return node
    return title_anchor.parent


def _extract_address(card_text: str) -> str:
    """Text after 'Address:' up to the next label."""
    m = re.search(
        r"Address:\s*(.*?)(?:Email:|Website|Facebook|Read more|Category:|$)",
        card_text, flags=re.IGNORECASE | re.DOTALL,
    )
    if not m:
        return ""
    addr = _clean(m.group(1))
    # Drop placeholder + trailing bare postal-code-only fragments
    if "cannot determine address" in addr.lower():
        addr = ""
    return addr[:200]


def parse_listings(html: str) -> List[Dict]:
    """Parse all business cards from a category listing page."""
    soup = BeautifulSoup(html, "html.parser")
    results: List[Dict] = []
    seen_urls = set()

    # Title links carry title="View: <name>" in this theme.
    anchors = soup.select('a[title^="View:"]')
    if not anchors:
        # Fallback: any business-detail anchor with non-empty text
        anchors = [a for a in soup.find_all("a", href=True)
                   if _is_business_url(a.get("href")) and a.get_text(strip=True)]

    for a in anchors:
        href = a.get("href", "")
        if not _is_business_url(href):
            continue
        url = urljoin(BASE, href.split("#")[0])
        name = _clean(a.get_text())
        if not name or url in seen_urls:
            continue
        seen_urls.add(url)

        card = _card_container(a)
        card_text = card.get_text("\n")

        # Category
        category = ""
        cat_a = card.select_one('a[href*="/listings/category/"]')
        if cat_a:
            category = _clean(cat_a.get_text())

        # Email — appears as the link text near "Email:"; regex the card text
        email = ""
        em = EMAIL_RE.search(card_text)
        if em:
            email = em.group(0).lower()

        # Phone — best effort: most YP listings have none, but capture any
        # Ugandan mobile number that appears in the card text.
        phone = ""
        pm = PHONE_RE.search(card_text)
        if pm:
            phone = re.sub(r"[\s\-]+", " ", pm.group(0)).strip()

        # Website / Facebook anchors
        website, facebook = "", ""
        for link in card.find_all("a", href=True):
            lhref = link["href"]
            ltext = _clean(link.get_text()).lower()
            if "facebook.com" in lhref.lower() and not facebook:
                facebook = lhref
            elif ltext == "website" and not website:
                website = lhref

        location = _extract_address(card_text)

        results.append({
            "business_name": name[:120],
            "username":      "",
            "phone":         phone,
            "email":         email,
            "website":       website,
            "facebook":      facebook,
            "category":      category or "Yellow Pages",
            "location":      location or "Uganda",
            "source_url":    url,
        })

    return results


def parse_categories(html: str) -> List[Tuple[str, str, int]]:
    """From /location, return list of (name, url, count)."""
    soup = BeautifulSoup(html, "html.parser")
    out: List[Tuple[str, str, int]] = []
    seen = set()
    for a in soup.find_all("a", href=True):
        href = a["href"]
        if "/listings/category/" not in href:
            continue
        url = urljoin(BASE, href.rstrip("/") + "/")
        if url in seen:
            continue
        seen.add(url)
        name = _clean(a.get_text()) or url.rstrip("/").split("/")[-1]
        # The count often follows the link text in the parent
        count = 0
        tail = _clean(a.parent.get_text()) if a.parent else ""
        mcount = re.search(re.escape(name) + r"\s*(\d+)", tail)
        if mcount:
            count = int(mcount.group(1))
        out.append((name, url, count))
    return out


# ── PHASE 1: discover categories ──────────────────────────────────────────────

def discover_yellowpages(api_key: str = "", target_count: int = 0,
                         progress_cb=None) -> List[Dict]:
    """Return all category pages as queue items: [{listing_url, title, category}]."""
    logger.info("[YellowPages/Discover] reading category index")
    session = requests.Session()
    html = _get(LOCATION_URL, session)
    cats = parse_categories(html)
    items = [{"listing_url": url, "title": name, "category": name}
             for (name, url, _cnt) in cats]
    logger.info("[YellowPages/Discover] found %d categories", len(items))
    if progress_cb:
        progress_cb(len(items), len(items))
    return items


# ── PHASE 2 / one-shot: scrape every category ─────────────────────────────────

def scrape_yellowpages(api_key: str = "", target_count: int = 0,
                       progress_cb=None) -> List[Dict]:
    """
    Crawl all categories from /location and return every business record.

    target_count: optional safety cap on number of records (0 = no cap → full site).
    """
    session = requests.Session()
    cats = parse_categories(_get(LOCATION_URL, session))
    if not cats:
        logger.warning("[YellowPages] no categories found")
        return []

    total_est = sum(c[2] for c in cats) or None
    cap = target_count if target_count and target_count > 100 else 0  # treat small limits as 'no cap'

    results: List[Dict] = []
    seen_urls = set()
    seen_emails = set()

    logger.info("[YellowPages] %d categories, est %s listings", len(cats), total_est)

    for (name, cat_url, _cnt) in cats:
        page_seen = set()
        for page in range(1, MAX_PAGES_PER_CATEGORY + 1):
            url = cat_url if page == 1 else f"{cat_url}?bdp_page={page}"
            html = _get(url, session)
            if not html:
                break
            cards = parse_listings(html)
            if not cards:
                break

            new_on_page = 0
            for rec in cards:
                u = rec["source_url"]
                if u in page_seen:
                    continue
                page_seen.add(u)
                if u in seen_urls:
                    continue
                # de-dup across whole crawl (by url, then by email)
                seen_urls.add(u)
                em = rec.get("email", "")
                if em and em in seen_emails:
                    rec["email"] = ""  # keep record, drop duplicate email to avoid clash
                elif em:
                    seen_emails.add(em)
                rec["category"] = rec["category"] or name
                results.append(rec)
                new_on_page += 1
                if progress_cb:
                    progress_cb(len(results), total_est or len(results))

            logger.info("[YellowPages] %s p%d: +%d (total %d)",
                        name[:24], page, new_on_page, len(results))

            # Pagination ends when a page adds nothing new (site repeats last page)
            if new_on_page == 0:
                break
            if cap and len(results) >= cap:
                logger.info("[YellowPages] hit cap %d", cap)
                return results[:cap]
            time.sleep(DELAY)
        time.sleep(DELAY)

    logger.info("[YellowPages] done — %d records", len(results))
    return results


# ── Quick CLI test ────────────────────────────────────────────────────────────

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    recs = scrape_yellowpages(target_count=20)
    for r in recs[:20]:
        print(f"{r['business_name'][:30]:32} | {r['email']:30} | {r['category']}")
    print("Total:", len(recs))
