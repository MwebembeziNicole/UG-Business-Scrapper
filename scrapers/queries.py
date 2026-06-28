"""
Shared business query list — one broadened source of categories + locations that
ALL scrapers (Jiji, Instagram, Twitter/X, TikTok) reuse, so the search coverage
is consistent and easy to widen in one place.

- LOCATIONS      : Kampala-area + upcountry areas to qualify searches.
- CATEGORIES     : broad business categories (clinics, pharmacies, law firms,
                   manufacturing, schools, hospitals, banks, media, telecom,
                   agriculture, transport, real estate, hospitality, etc.).
- SECTOR_PHRASES : ready-made "private X in Uganda" lead phrases.

Helpers:
- build_plain_queries()          -> "<category> <location>"          (on-site search, e.g. Jiji)
- build_site_queries(domain)     -> "<category> <location> site:<d>" (Google discovery: IG / X / TikTok)
- infer_category(text) / infer_location(text)  -> best-guess labels from a bio/description
"""

from __future__ import annotations

import random
from typing import List

# ── Locations (the requested set + nearby high-density areas) ──────────────────
LOCATIONS = [
    "Kampala", "Ntinda", "Kololo", "Bugolobi", "Kiwatule", "Kyanja",
    "Mukono", "Entebbe", "Jinja", "Nakawa", "Najjera", "Naalya",
    "Wandegeya", "Muyenga", "Nsambya", "Kira", "Seeta", "Bukoto",
]

# ── Broad business categories (search-friendly terms) ─────────────────────────
CATEGORIES = [
    # Real estate / accommodation
    "real estate", "real estate agents", "property developers",
    "houses for sale", "houses for rent", "land for sale", "plots for sale",
    "apartments for rent", "furnished apartments", "Airbnb", "short stay apartments",
    "vacation rentals", "hostels", "hotels", "guest houses", "lodges",
    # Food & hospitality
    "restaurants", "cafes", "bars", "catering services",
    # Healthcare
    "clinics", "medical clinics", "skin clinics", "dermatology clinics",
    "dental clinics", "eye clinics", "optical clinics", "maternity clinics",
    "specialist clinics", "hospitals", "private hospitals", "medical centres",
    "pharmacies", "drug shops", "diagnostic laboratories",
    # Beauty / wellness
    "spas", "massage parlours", "salons", "beauty parlours", "barber shops",
    # Optical / eyewear
    "glasses shops", "spectacle shops", "opticians",
    # Professional services
    "law firms", "advocates", "consultancy firms", "business consultants",
    "audit firms", "accounting firms",
    # Finance
    "loan companies", "money lenders", "microfinance", "SACCOs",
    "forex bureaus", "banks", "insurance companies", "insurance brokers",
    # Education
    "private schools", "primary schools", "secondary schools",
    "international schools", "nursery schools", "universities", "colleges",
    "vocational institutes", "nursing schools", "business schools",
    # Manufacturing / industry
    "manufacturing companies", "food processing companies", "beverage companies",
    "textile companies", "steel companies", "plastic manufacturers",
    "furniture manufacturers", "agro-processing firms", "pharmaceutical manufacturers",
    # Construction / hardware
    "construction companies", "contractors", "engineering firms",
    "building materials", "hardware shops", "cement dealers", "roofing", "tiles",
    # Tech / electronics / telecom
    "solar companies", "solar installers", "electronics shops", "phone shops",
    "computer shops", "ICT companies", "software companies",
    "internet service providers", "telecom companies",
    # Automotive
    "car dealers", "used cars", "car hire", "self drive", "car rental",
    "garages", "spare parts",
    # Creative / events
    "printing companies", "branding", "signage", "graphic design",
    "photography", "videography", "event management", "event hire",
    # Tourism / travel
    "tour operators", "travel agencies", "safari companies", "tourism companies",
    # Agriculture
    "agribusiness", "coffee companies", "tea companies", "seed companies",
    "dairy companies", "poultry farms", "farm supplies",
    # Transport / logistics
    "transport companies", "logistics companies", "courier companies",
    "bus companies", "freight forwarders",
    # Retail / fashion
    "groceries", "supermarkets", "wholesale shops", "fresh produce",
    "fashion boutiques", "clothing shops", "shoe shops", "tailoring",
    # Media
    "media companies", "TV stations", "radio stations", "newspapers",
    "production companies", "advertising agencies", "publishing companies",
]

# ── Ready-made sector lead phrases (good for Google discovery) ─────────────────
SECTOR_PHRASES = [
    "private manufacturing firms in Uganda", "top private manufacturers in Uganda",
    "private schools in Uganda", "registered private schools in Uganda",
    "private hospitals in Uganda", "licensed private hospitals in Uganda",
    "private clinics in Uganda", "private dental clinics in Uganda",
    "private pharmacies in Uganda", "private banks in Uganda",
    "licensed commercial banks in Uganda", "private microfinance companies in Uganda",
    "private insurance companies in Uganda", "private media companies in Uganda",
    "top private media houses in Uganda", "private telecom companies in Uganda",
    "private law firms in Uganda", "private consultancy firms in Uganda",
    "private real estate companies in Uganda", "private hotels in Uganda",
    "private tour companies in Uganda", "private logistics companies in Uganda",
]

# ── Keyword -> canonical category (for inferring a category from a bio) ────────
CATEGORY_KEYWORDS = {
    "airbnb": "Airbnb & Short-Let", "short let": "Airbnb & Short-Let",
    "hostel": "Hostels", "hotel": "Hotels", "lodge": "Hotels",
    "apartment": "Apartments", "rent": "Rentals", "rental": "Rentals",
    "for sale": "Real Estate", "real estate": "Real Estate", "property": "Real Estate",
    "land": "Land & Plots", "plot": "Land & Plots",
    "restaurant": "Restaurant", "cafe": "Restaurant", "catering": "Catering",
    "dental": "Dental Clinic", "dentist": "Dental Clinic",
    "skin": "Skin Clinic", "dermatology": "Skin Clinic",
    "eye": "Eye / Optical Clinic", "optical": "Eye / Optical Clinic",
    "glasses": "Eyewear", "spectacle": "Eyewear", "optician": "Eyewear",
    "maternity": "Maternity Clinic", "clinic": "Clinic", "hospital": "Hospital",
    "pharmacy": "Pharmacy", "drug shop": "Pharmacy", "laboratory": "Diagnostics",
    "spa": "Spa", "massage": "Massage", "salon": "Salon & Beauty",
    "beauty": "Salon & Beauty", "barber": "Barber",
    "law firm": "Law Firm", "advocate": "Law Firm", "lawyer": "Law Firm",
    "consult": "Consultancy", "audit": "Audit & Accounting", "account": "Audit & Accounting",
    "loan": "Loans & Microfinance", "microfinance": "Loans & Microfinance",
    "sacco": "Loans & Microfinance", "forex": "Forex Bureau",
    "bank": "Bank", "insurance": "Insurance",
    "school": "School", "university": "University", "college": "College",
    "manufactur": "Manufacturing", "factory": "Manufacturing",
    "construction": "Construction", "contractor": "Construction",
    "engineering": "Engineering", "hardware": "Hardware",
    "cement": "Building Materials", "roofing": "Building Materials", "tiles": "Building Materials",
    "solar": "Solar", "electronics": "Electronics", "phone": "Phones & Accessories",
    "computer": "Computers & IT", "software": "Software & IT", "ict": "Software & IT",
    "internet": "Internet / Telecom", "telecom": "Internet / Telecom",
    "car": "Automotive", "vehicle": "Automotive", "garage": "Automotive",
    "printing": "Printing & Branding", "branding": "Printing & Branding",
    "signage": "Printing & Branding", "graphic": "Printing & Branding",
    "photography": "Photography", "videography": "Photography",
    "event": "Events", "tour": "Tourism & Travel", "travel": "Tourism & Travel",
    "safari": "Tourism & Travel",
    "coffee": "Agriculture", "tea": "Agriculture", "dairy": "Agriculture",
    "poultry": "Agriculture", "agri": "Agriculture", "farm": "Agriculture",
    "logistics": "Logistics", "courier": "Courier", "transport": "Transport",
    "supermarket": "Retail", "grocery": "Retail", "wholesale": "Retail",
    "fashion": "Fashion", "boutique": "Fashion", "clothing": "Fashion",
    "shoe": "Fashion", "tailor": "Fashion",
    "media": "Media", "radio": "Media", "tv": "Media",
    "newspaper": "Media", "advertising": "Advertising",
}


# ── Query builders ────────────────────────────────────────────────────────────

def build_plain_queries(shuffle: bool = True, seed: int | None = None) -> List[str]:
    """`<category> <location>` combos for on-site search engines (e.g. Jiji)."""
    out = [f"{cat} {loc}" for cat in CATEGORIES for loc in LOCATIONS]
    out += [c + " Uganda" for c in CATEGORIES]
    _maybe_shuffle(out, shuffle, seed)
    return out


def build_site_queries(domain: str, include_sectors: bool = True,
                       shuffle: bool = True, seed: int | None = None) -> List[str]:
    """
    Google discovery queries: `<category> <location> site:<domain>`.
    Used by the Instagram / Twitter / TikTok modules.
    """
    out = [f"{cat} {loc} site:{domain}" for cat in CATEGORIES for loc in LOCATIONS]
    out += [f"{cat} Uganda site:{domain}" for cat in CATEGORIES]
    if include_sectors:
        out += [f"{phrase} site:{domain}" for phrase in SECTOR_PHRASES]
    _maybe_shuffle(out, shuffle, seed)
    return out


def _maybe_shuffle(items: List[str], shuffle: bool, seed):
    if shuffle:
        (random.Random(seed) if seed is not None else random).shuffle(items)


# ── Inference helpers (shared by extractors) ──────────────────────────────────

def infer_category(text: str, fallback: str = "Business") -> str:
    low = (text or "").lower()
    for kw, cat in CATEGORY_KEYWORDS.items():
        if kw in low:
            return cat
    return fallback


def infer_location(text: str, fallback: str = "Uganda") -> str:
    low = (text or "").lower()
    for loc in LOCATIONS:
        if loc.lower() in low:
            return loc
    return fallback
