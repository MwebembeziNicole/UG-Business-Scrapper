"""
One-time login helper for the persistent Chrome profiles.

WHY: Phone numbers on Instagram (bio) and Jiji (Show Contact) are only visible
to a logged-in browser. Each platform uses its own persistent Chrome profile
under  browser_profiles/<platform>/  . You log in ONCE here; every scrape after
that reuses the saved session — no Firecrawl, no third-party viewers.

USAGE
-----
    python login.py                # log into both instagram and jiji
    python login.py instagram      # just Instagram
    python login.py jiji           # just Jiji

A real Chrome window opens. Log in normally (solve any 2FA / CAPTCHA), then
return to the terminal and press ENTER. The cookies persist in the profile.
"""

import sys
import time

from scrapers.browser import build_driver

SITES = {
    "instagram": "https://www.instagram.com/accounts/login/",
    "jiji": "https://jiji.ug/login",
}


def login(platform: str):
    url = SITES.get(platform)
    if not url:
        print(f"Unknown platform: {platform}  (choose: {', '.join(SITES)})")
        return
    print(f"\n=== Logging into {platform} ===")
    driver = build_driver(platform, headless=False)  # MUST be visible to log in
    try:
        driver.get(url)
        print("A Chrome window is open.")
        input(f"Log into {platform} in that window, then press ENTER here… ")
        time.sleep(2)
        print(f"✓ {platform} session saved to browser_profiles/{platform}")
    finally:
        try:
            driver.quit()
        except Exception:
            pass


if __name__ == "__main__":
    targets = sys.argv[1:] or ["instagram", "jiji"]
    for t in targets:
        login(t.lower())
    print("\nDone. You can now run scrapes from the dashboard and phones will be captured.")
