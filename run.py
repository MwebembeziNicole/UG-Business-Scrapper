"""
Entry point — run this to start the Uganda Business Scraper.
  python run.py
"""

import webbrowser
import threading
import time
import sys
import os

# Ensure the app directory is on the path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from app import create_app

PORT = 5050
URL  = f"http://127.0.0.1:{PORT}"


def _open_browser():
    time.sleep(1.5)
    webbrowser.open(URL)


if __name__ == "__main__":
    print("=" * 55)
    print("  🇺🇬  Uganda Business Scraper")
    print("=" * 55)
    print(f"  Dashboard  →  {URL}")
    print("  Press Ctrl+C to stop")
    print("=" * 55)

    # Open browser in background after server starts
    threading.Thread(target=_open_browser, daemon=True).start()

    app = create_app()
    app.run(host="127.0.0.1", port=PORT, debug=False, use_reloader=False)
