"""
CLI entry for QuickBooks payment matching.

Launched from My Desk (new console) or directly:
  python run_payment_match.py --config path/to/config.json
"""

import argparse
import json
import sys
from pathlib import Path

_APP_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(_APP_DIR))

from fin_services.payment_match import PaymentMatchConfig, run_payment_match  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description="QuickBooks payment matching batch")
    parser.add_argument(
        "--config",
        required=True,
        help="JSON config file (excel_file, sheet_name, quickbooks_url, max_customers)",
    )
    args = parser.parse_args()

    config_path = Path(args.config)
    with config_path.open(encoding="utf-8") as fh:
        raw = json.load(fh)

    config = PaymentMatchConfig(
        excel_file=raw["excel_file"],
        sheet_name=raw.get("sheet_name", PaymentMatchConfig.sheet_name),
        quickbooks_url=raw.get("quickbooks_url", PaymentMatchConfig.quickbooks_url),
        max_customers=int(raw.get("max_customers", 898)),
    )

    run_payment_match(config)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
