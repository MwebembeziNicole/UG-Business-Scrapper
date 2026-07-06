# Business Contact Data Collection Platform — Technical Description

## Overview

This project is a multi-source web scraping and data-collection platform that automatically gathers publicly listed business contact information — business names, phone numbers, emails, websites, social handles, categories, and locations — from several online sources, then de-duplicates, stores, and exports it. It is built in Python around a Flask control dashboard, with each online source handled by its own dedicated scraper module behind a shared architecture.

What makes the project a substantial exercise in practical web scraping is that it does not rely on a single technique. Different sources expose their data in fundamentally different ways — some behind a login wall, some rendered by JavaScript, some as plain server-side HTML, and some only reachable through a managed extraction API — so the platform deliberately combines several scraping strategies and selects the right one per source. The sections below describe those techniques in detail.

## Multi-strategy scraping architecture

Every source is implemented as an independent scraper module (Jiji, Instagram, Yellow Pages, Twitter/X, TikTok, Jumia) that conforms to a common contract: it accepts a target record count and a progress callback and returns a list of normalised business records. This uniform interface means the orchestration layer treats all sources identically even though their internals differ enormously. The three broad strategies in use are authenticated real-browser automation, static HTTP scraping with HTML parsing, and managed API extraction.

### 1. Authenticated, session-based scraping with a real browser

The most demanding sources are social platforms where the valuable contact details — a phone number in an Instagram bio, or a seller's number hidden behind a marketplace's "Show Contact" button — are only visible to a logged-in user viewing the genuine site. Naïve approaches (headless requests, or scraping third-party mirror/viewer sites) simply cannot see this data.

The platform solves this with Selenium driving a real Chrome browser, hardened against bot detection using `undetected-chromedriver`, with `webdriver-manager` handling driver provisioning. A shared browser factory gives every scraper one consistent way to launch Chrome. The key technique is persistent browser profiles: each platform keeps its own Chrome user-data directory, so the operator logs in once (in a visible window, solving any 2FA or CAPTCHA by hand), and every subsequent automated run reuses that saved session and is already authenticated. Running the window visibly rather than headless is a deliberate anti-detection choice, since headless fingerprints are among the easiest for sites to flag.

This demonstrates several real-world scraping skills: session and cookie persistence, driving authenticated flows, interacting with dynamic page elements (clicking to reveal hidden contact fields), waiting for JavaScript-rendered content, and configuring page-load timeouts and window sizing for stability.

### 2. Static HTTP scraping with HTML parsing

Directory-style sources that serve server-rendered HTML don't need a browser at all. For these, the platform uses the lightweight `requests` + `BeautifulSoup` combination to fetch pages directly and parse the DOM for listing details. This path is far faster and cheaper than a browser, so it is used wherever the data is present in the raw HTML. It also handles the pragmatic reality that some directory listings have no phone or username, in which case the listing's own URL is treated as the stable identifier. Skills shown here include HTTP request handling, HTML tree parsing and selection, pagination across category pages, request timeouts, and polite inter-request delays.

### 3. Managed API extraction

For sources where maintaining a browser or bespoke parser would be brittle, the platform integrates the Firecrawl extraction API, which handles fetching and structuring page content on the platform's behalf. The API key is supplied through configuration rather than hard-coded, and sources that don't need it (the direct-HTTP directory scraper) are explicitly exempt so a missing key never blocks them. This shows an understanding of when to offload scraping to a managed service versus building it in-house.

## Two-phase discovery-then-detail collection

Several sources are scraped in two phases rather than one pass. A discovery phase crawls search or category pages to find candidate listing URLs or profile handles, which are written into a discovery queue in the database. A separate detail phase then works through that queue, visiting each item to extract the full contact record. Instagram, Jiji, Twitter, and TikTok all use dedicated queues (profile-based for the social platforms, listing-URL-based for the marketplace).

This decoupling is a mature scraping pattern: discovery and extraction can run at different times and rates, the queue survives restarts, work is not lost if a run is interrupted, and each item's "scraped" state is tracked so nothing is processed twice. It also naturally spreads load and makes the whole pipeline resumable.

## Anti-bot and anti-detection strategy

Beyond `undetected-chromedriver` and visible real-browser sessions, the platform reflects a considered approach to staying unobtrusive and avoiding blocks: persistent authenticated profiles so traffic looks like a returning human user, configurable per-category page limits so a single run never crawls unbounded, and deliberate delays between requests in the static-HTTP path. Timeouts and defensive exception handling wrap the fragile network and DOM operations so a single failed element or slow page degrades gracefully instead of crashing the run.

## Data integrity and de-duplication

Collected records are de-duplicated at the database layer using partial unique indexes on phone number, username, and email (and, for directory listings, the source URL), so the same business is never stored twice even across repeated runs or overlapping sources. Each incoming record is checked against existing rows before insertion, and integrity violations are caught and skipped rather than aborting the batch. This is an important, often-overlooked scraping skill: raw collection is easy, but keeping the resulting dataset clean and free of duplicates across many runs is where most real value and difficulty lies.

## Concurrency, progress, and cooperative cancellation

Scrapes run in background threads so the dashboard stays responsive while collection proceeds. Each scraper reports progress through a callback, which the platform surfaces live in the UI. A recent addition is cooperative cancellation: an operator can pause a run that was started by mistake, and the scraper checks for that stop signal each time it reports progress and winds down cleanly at the next safe checkpoint, preserving whatever was already collected. The stop signal is implemented so that it propagates reliably even through the scrapers' own broad error handling. This demonstrates safe control of long-running background work — starting, monitoring, and stopping it without corrupting state or killing threads abruptly.

## Scheduling and automation

The platform uses APScheduler to run collection automatically on a daily schedule, with the schedule time and an on/off switch configurable at runtime. A run can therefore be fully unattended, after which a dated snapshot of the day's results is written out. This turns the scrapers from a manual tool into an automated recurring pipeline.

## Persistence and export

Collected data is written to a relational database through a clean repository abstraction that supports two interchangeable backends — SQLite for a zero-setup local install and PostgreSQL for a server deployment — selected automatically from configuration without changing any scraper code. Results are exported to formatted Excel workbooks (one sheet per source plus a daily "new" sheet) using pandas and openpyxl, giving non-technical users a familiar way to consume the output.

## Orchestration, monitoring, and configuration

A Flask web dashboard ties everything together: it launches individual source scrapers or a full multi-source collection, shows per-source status and counts, streams scrape logs, and manages settings — all behind a login. Configuration and secrets (API keys, database credentials, schedule defaults, crawl limits) are centralised and read from environment variables via a local `.env` file, so nothing sensitive is hard-coded and the same codebase runs unchanged across machines. This orchestration layer is what elevates the project from a collection of scripts to an operable data-collection system.

## Web scraping skills demonstrated

Taken together, the project exercises a broad and practical web-scraping skill set: browser automation with Selenium and anti-detection tooling; authenticated, session-persistent scraping of login-gated content; interaction with JavaScript-rendered and click-to-reveal elements; static HTTP fetching with HTML parsing; integration of a managed scraping API; the two-phase discover-then-extract pattern with durable queues; pagination and rate-limiting; robust error handling around unreliable networks and markup; record normalisation and cross-run de-duplication; background-thread concurrency with live progress and safe cancellation; scheduled unattended automation; and a configurable, multi-backend storage and export pipeline behind a monitoring dashboard. It is a realistic example of building a maintainable, multi-source scraping system rather than a single throwaway script.
