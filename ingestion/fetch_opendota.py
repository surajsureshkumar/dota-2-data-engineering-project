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


def save_json(name: str, payload) -> None:
    """Write payload to data/raw as a JSON file named {name}.json.

    Creates the raw data directory if it does not exist, then writes the
    file and prints its size.

    Args:
        name (str): File name to use, without the .json extension.
        payload: JSON-serializable data to write, usually a dict or list.
    """
    RAW_DIR.mkdir(parents=True, exist_ok=True)
    path = RAW_DIR / f"{name}.json"
    with open(path, "w", encoding="utf-8") as f:
        json.dump(payload, f)
    size_kb = path.stat().st_size / 1024
    print(f"  saved {path.name} ({size_kb:,.0f} KB)")


def fetch_reference_data() -> None:
    """Fetch hero and team reference data and save each to its own JSON file."""
    print("Fetching hero reference data...")
    save_json("heroes", api_get("heroes"))
    print("Fetching team reference data...")
    save_json("teams", api_get("teams"))


def fetch_pro_matches(pages: int) -> list[dict]:
    """Fetch recent pro matches from OpenDota, paging backward by match id.

    Each page is fetched with less_than_match_id set to the oldest match id
    seen so far, so pages do not overlap. Stops early if a page comes back
    empty. Saves the combined list to pro_matches.json.

    Args:
        pages (int): Number of pages to fetch, about 100 matches per page.

    Returns:
        list[dict]: All matches collected across the fetched pages.
    """
    print(f"Fetching pro matches ({pages} page(s))...")
    matches: list[dict] = []
    less_than: int | None = None
    for page in range(1, pages + 1):
        params = {"less_than_match_id": less_than} if less_than else None
        batch = api_get("proMatches", params)
        if not batch:
            break
        matches.extend(batch)
        less_than = batch[-1]["match_id"]
        print(f"  page {page}: {len(batch)} matches (total {len(matches)})")
    save_json("pro_matches", matches)
    return matches


def fetch_match_details(matches: list[dict], league_id: int | None, limit: int) -> None:
    """Fetch full match detail for a subset of matches and save the results.

    If league_id is given, only matches from that league are considered.
    The candidate list is then capped to limit matches. Matches that fail
    to fetch are skipped so one bad match does not stop the whole run.
    Saves the collected details to match_details.json.

    Args:
        matches (list[dict]): Match summaries to pick from, as returned by
            fetch_pro_matches.
        league_id (int | None): If set, only fetch matches from this
            league or event.
        limit (int): Maximum number of full match details to fetch.
    """
    if league_id:
        selected = [m for m in matches if m.get("leagueid") == league_id]
        print(f"{len(selected)} matches found for league {league_id}")
    else:
        selected = matches
    selected = selected[:limit]

    print(f"Fetching full detail for {len(selected)} matches "
          f"(~{len(selected) * SLEEP_SECONDS / 60:.1f} min)...")
    details = []
    for i, match in enumerate(selected, 1):
        match_id = match["match_id"]
        try:
            details.append(api_get(f"matches/{match_id}"))
        except Exception as exc:  # noqa: BLE001 - skip bad matches, keep going
            print(f"  skipping match {match_id}: {exc}")
            continue
        if i % 10 == 0:
            print(f"  {i}/{len(selected)} done")
    save_json("match_details", details)


def main() -> int:
    """Parse CLI arguments and run the full fetch pipeline.

    Fetches reference data, then pro matches, then full detail for a
    subset of those matches, writing each result as raw JSON.

    Returns:
        int: Exit code, 0 on success.
    """
    parser = argparse.ArgumentParser(description="Fetch Dota 2 data from OpenDota")
    parser.add_argument("--pages", type=int, default=2,
                        help="Pages of /proMatches to fetch (~100 matches each)")
    parser.add_argument("--league-id", type=int, default=None,
                        help="Only fetch match details for this league/event")
    parser.add_argument("--match-limit", type=int, default=40,
                        help="Max number of full match details to fetch")
    args = parser.parse_args()

    fetch_reference_data()
    matches = fetch_pro_matches(args.pages)
    fetch_match_details(matches, args.league_id, args.match_limit)

    print(f"\nDone. Raw JSON written to {RAW_DIR}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
