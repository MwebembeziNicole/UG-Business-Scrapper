# Scraper fix — why phones were missing, and what changed

## The problem
The system found profiles/listings but captured **no phone numbers**. Two root causes:

1. **Instagram** — `scrapers/instagram.py` scraped phone numbers through
   third-party viewer sites (`imginn.com`, `picuki.com`, `dumpor.com`). Those are
   now **dead or bot-blocked**, so they returned empty pages. Instagram phone
   numbers live in the **bio**, which is only fully visible to a **logged-in**
   session viewing `instagram.com` directly.

2. **Jiji** — `scrapers/jiji.py` ran **headless** Playwright. Jiji sits behind
   Cloudflare and hides the number behind a **"Show Contact"** button; a headless,
   logged-out browser gets blocked, so no number was revealed.

Your own scripts (`ig_scraper.py`, `google_instagram_search.py`,
`scraper_jiji.ipynb`) worked because they used a **real, visible, manually
logged-in Chrome** reading the real sites. That approach is now ported into the
system.

## What changed
| File | Before | After |
|------|--------|-------|
| `scrapers/browser.py` | _new_ | Persistent-profile Chrome factory + shared phone/category/location helpers + login detection |
| `scrapers/instagram.py` | Firecrawl + dead viewers, headless | Google `site:instagram.com` discovery + **logged-in instagram.com** scraping (ports `ig_scraper.py`) |
| `scrapers/jiji.py` | Firecrawl + headless Playwright | jiji.ug category-search discovery + **logged-in "Show Contact"** scraping (ports the notebook) |
| `login.py` | _new_ | One-time login to save each platform's session |

Originals are backed up in `_firecrawl_backup/`.

## How it works now: persistent login
Each platform keeps its own Chrome profile under `browser_profiles/<platform>/`.
You log in **once**; the session is reused on every later run.

### 1. Install
```
pip install -r requirements.txt
```

### 2. Log in once (a real Chrome window opens)
```
python login.py            # logs into both Instagram and Jiji
# or individually:
python login.py instagram
python login.py jiji
```
Log in normally (including 2FA), then press ENTER in the terminal.

### 3. Scrape
Run the dashboard as usual (`python run.py`) and use Discover → Scrape, or call
the scrapers directly. A Chrome window will appear during scraping — that is
expected and required for the numbers to be visible. If Google shows a CAPTCHA
during Instagram discovery, solve it in the window; the script waits.

## Notes
- **Keep the window visible.** Headless is available (`headless=True`) but
  Instagram/Jiji usually hide data or block it headless. Default is visible.
- `api_key` arguments remain in the function signatures only for compatibility
  with `app.py`; discovery no longer uses Firecrawl.
- Pacing/randomised delays are built in. Don't lower them aggressively or you
  risk a temporary block on your account.
- Tune the search scope by editing `LOCATIONS`/`NICHES` in `instagram.py` and
  `CATEGORIES` in `jiji.py`.
