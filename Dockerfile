# Uganda Business Scraper — container image for Fly.io
# Includes Google Chrome so Selenium / undetected-chromedriver can run
# headless against the persistent, already-logged-in browser profiles.

FROM python:3.11-slim

# ── System deps + Google Chrome ────────────────────────────────────────────
RUN apt-get update && apt-get install -y --no-install-recommends \
        wget gnupg unzip curl ca-certificates fonts-liberation \
        libasound2 libatk-bridge2.0-0 libatk1.0-0 libcups2 libdbus-1-3 \
        libdrm2 libgbm1 libgtk-3-0 libnspr4 libnss3 libx11-xcb1 \
        libxcomposite1 libxdamage1 libxfixes3 libxkbcommon0 libxrandr2 \
        xdg-utils \
    && wget -q -O /tmp/chrome.deb \
        https://dl.google.com/linux/direct/google-chrome-stable_current_amd64.deb \
    && apt-get install -y /tmp/chrome.deb \
    && rm /tmp/chrome.deb \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt gunicorn

COPY . .

ENV PYTHONUNBUFFERED=1
EXPOSE 8080

# Single worker: APScheduler and the in-memory scrape_status dict are process-local,
# so more than one gunicorn worker would duplicate the daily job and split state.
# Shell form (not exec-array) so $PORT expands — Railway assigns its own port at
# runtime and won't always be 8080; Fly.io users can keep setting PORT=8080 in env.
CMD gunicorn "app:create_app()" --bind 0.0.0.0:${PORT:-8080} --workers 1 --threads 4 --timeout 180
