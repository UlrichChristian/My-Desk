"""
Pull the EA admin accounts list into a CSV (lives / premium / advisor / …).

The accounts grid at app.effortlessadmin.com is backed by a paginated JSON API:

    GET /accounts/api/accounts?query=&filter=0-1&page=N&includePreviousPages=false
        &sorting=Name:ascending
    -> {"total": <int>, "accounts": [ {oid, name, livesCount, monthlyPremium,
        brokerList[], consultingHouses[], policies[], planDesignNames[], ...}, ... ]}

We reuse the payment_match machinery: launch Edge (detached), let the user log in
manually, then fetch every page *from inside the authenticated browser* (so the
session cookies come along) and flatten the objects to a CSV. This returns the full
field set the grid hides (advisor, consulting house, etc.) and needs no scrolling.

Read-only: only GETs the accounts API — nothing on the admin site is modified.
"""

from __future__ import annotations

import csv
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import quote

from selenium import webdriver
from selenium.webdriver.edge.options import Options

DEFAULT_ACCOUNTS_URL = "https://app.effortlessadmin.com/accounts/"
DEFAULT_API_BASE = "https://app.effortlessadmin.com/accounts/api/accounts"

# Fetch one page of the accounts API from inside the browser session and hand the
# parsed JSON back to Selenium via the async callback.
_FETCH_JS = """
const url = arguments[0];
const cb = arguments[arguments.length - 1];
fetch(url, {headers: {Accept: 'application/json'}, credentials: 'same-origin'})
    .then(r => r.ok ? r.json() : {__error: 'HTTP ' + r.status})
    .then(d => cb(d))
    .catch(e => cb({__error: String(e)}));
"""


@dataclass
class PullAccountsConfig:
    output_csv: str | Path
    accounts_url: str = DEFAULT_ACCOUNTS_URL
    api_base: str = DEFAULT_API_BASE
    query: str = ""
    filter: str = "0-1;0-2;0-3"         # all statuses: Active;Terminated;Updating
    sorting: str = "Name:ascending"
    max_pages: int = 100                # safety cap (200/page → 20k accounts)


def _wait_for_ready(prompt: str, ready_callback=None) -> None:
    if ready_callback:
        ready_callback(prompt)
        return
    input()


def _page_url(config: PullAccountsConfig, page: int) -> str:
    # Encode the filter's ';' separators (→ %3B); keep ':' in sorting unencoded,
    # matching the request the grid itself issues.
    return (
        f"{config.api_base}?query={quote(config.query, safe='')}"
        f"&filter={quote(config.filter, safe='')}"
        f"&page={page}&includePreviousPages=false"
        f"&sorting={quote(config.sorting, safe=':')}"
    )


def _flatten(account: dict) -> dict:
    """Flatten one account object for CSV: arrays → ' | '-joined, bools → True/False."""
    out = {}
    for key, value in account.items():
        if isinstance(value, list):
            out[key] = " | ".join("" if v is None else str(v) for v in value)
        elif isinstance(value, bool):
            out[key] = "True" if value else "False"
        else:
            out[key] = "" if value is None else value
    return out


def fetch_accounts(driver, config: PullAccountsConfig) -> list[dict]:
    """Page through the accounts API. Returns the raw account objects."""
    driver.set_script_timeout(60)
    all_accounts: list[dict] = []
    total = None

    for page in range(config.max_pages):
        data = driver.execute_async_script(_FETCH_JS, _page_url(config, page))
        if not isinstance(data, dict) or data.get("__error"):
            err = data.get("__error") if isinstance(data, dict) else data
            raise RuntimeError(f"Accounts API fetch failed on page {page}: {err}")

        if total is None:
            total = data.get("total")
        accounts = data.get("accounts") or []
        if not accounts:
            break

        all_accounts.extend(accounts)
        print(f"  page {page}: +{len(accounts)}  ({len(all_accounts)}"
              f"{'/' + str(total) if total is not None else ''})")

        if total is not None and len(all_accounts) >= total:
            break

    return all_accounts


def run_pull_accounts(config: PullAccountsConfig, ready_callback=None) -> dict:
    """Open Edge, wait for manual login, page the accounts API, write CSV."""
    print("=" * 60)
    print("PULL ACCOUNTS — EA admin site (API)")
    print("=" * 60)

    edge_options = Options()
    edge_options.add_experimental_option("detach", True)
    driver = webdriver.Edge(options=edge_options)
    driver.maximize_window()

    driver.get(config.accounts_url)
    print(f"\nBrowser opened at {config.accounts_url}")
    print("Please log in to the EA admin site (the accounts page).")
    print("Press Enter when you're logged in and the accounts list has loaded...")
    _wait_for_ready("Press Enter when logged in...", ready_callback)

    print("\nFetching accounts from the API...")
    accounts = fetch_accounts(driver, config)

    if not accounts:
        print("  ✗ No accounts returned. Nothing written.")
        return {"rows": 0, "output": None}

    rows = [_flatten(a) for a in accounts]

    # Column order: keys in first-seen order across all rows (stable, complete).
    columns: list[str] = []
    seen = set()
    for row in rows:
        for key in row:
            if key not in seen:
                seen.add(key)
                columns.append(key)

    output_path = Path(config.output_csv)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=columns, extrasaction="ignore")
        writer.writeheader()
        for row in rows:
            writer.writerow({c: row.get(c, "") for c in columns})

    print("\n" + "=" * 60)
    print(f"Captured {len(rows)} accounts × {len(columns)} columns")
    print(f"Saved: {output_path}")
    print("=" * 60)

    return {"rows": len(rows), "columns": len(columns), "output": str(output_path)}
