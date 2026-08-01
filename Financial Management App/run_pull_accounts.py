"""
CLI entry for the EA accounts pull.

Launched from My Desk (new console) or directly:
  python run_pull_accounts.py --config path/to/config.json
"""

import argparse
import json
import sys
from pathlib import Path

_APP_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(_APP_DIR))

from fin_services.pull_accounts import PullAccountsConfig, run_pull_accounts  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description="Pull EA admin accounts grid to CSV")
    parser.add_argument(
        "--config",
        required=True,
        help="JSON config file (output_csv, accounts_url, selectors, scroll params)",
    )
    args = parser.parse_args()

    config_path = Path(args.config)
    with config_path.open(encoding="utf-8") as fh:
        raw = json.load(fh)

    config = PullAccountsConfig(
        output_csv=raw["output_csv"],
        accounts_url=raw.get("accounts_url", PullAccountsConfig.accounts_url),
        api_base=raw.get("api_base", PullAccountsConfig.api_base),
        query=raw.get("query", PullAccountsConfig.query),
        filter=raw.get("filter", PullAccountsConfig.filter),
        sorting=raw.get("sorting", PullAccountsConfig.sorting),
        max_pages=int(raw.get("max_pages", PullAccountsConfig.max_pages)),
    )

    run_pull_accounts(config)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
