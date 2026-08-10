"""
Fetch Dota 2 data from the OpenDota API and store it as raw JSON.

Endpoints used (all free tier - 50,000 calls/month, 60 calls/minute):
  /heroes              hero reference data
  /teams               pro team reference data
  /proMatches          recent pro matches (paginated ~100 per page)
  /matches/{match_id}  full match detail incl. per-player stats

Usage:
  python ingestion/fetch_opendota.py --pages 2 --match-limit 40
  python ingestion/fetch_opendota.py --league-id 16935 --match-limit 60
"""

import argparse
import json
import sys
import time
from pathlib import Path

import requests

BASE_URL = "https://api.opendota.com/api"
RAW_DIR = Path(__file__).resolve().parents[1] / "data" / "raw"
SLEEP_SECONDS = 1.1  # poause between requests so that we stay within the limit
MAX_RETRIES = 3 # exponential backoff logic for retries


def api_get(endpoint: str, params: dict | None = None):
    """Make one GET request to the OpenDota API, retrying on rate limiting.

    On a 429 response, waits with linearly increasing backoff (30s * attempt)
    and retries, up to MAX_RETRIES attempts. On success, sleeps SLEEP_SECONDS
    before returning so subsequent calls stay within the API's rate limit.

    Args:
        endpoint (str): API path relative to BASE_URL, e.g. "heroes" or
            "matches/123456789".
        params (dict | None, optional): Query string parameters to send with
            the request. Defaults to None.

    Raises:
        RuntimeError: If the endpoint still returns 429 after MAX_RETRIES
            attempts.
        requests.HTTPError: If the response is a non-200, non-429 error
            status.

    Returns:
        dict | list: The parsed JSON response body.
    """
    url = f"{BASE_URL}/{endpoint}"
    for attempt in range(1, MAX_RETRIES + 1):
        resp = requests.get(url, params=params, timeout=30)
        if resp.status_code == 200:
            time.sleep(SLEEP_SECONDS)
            return resp.json()
        if resp.status_code == 429:
            wait = 30 * attempt
            print(f"  rate limited on {endpoint}, waiting {wait}s...")
            time.sleep(wait)
            continue
        resp.raise_for_status()
    raise RuntimeError(f"Failed to fetch {endpoint} after {MAX_RETRIES} attempts")


