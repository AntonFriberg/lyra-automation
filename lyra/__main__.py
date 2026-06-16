"""Entry point: ``uv run lyra <command>``."""

import argparse

from playwright.sync_api import sync_playwright

from .extract import run_extract
from .bill import run_bill


def main() -> None:
    parser = argparse.ArgumentParser(description="Lyra Automation")
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("extract", help="Extract bookings from Smart Brf calendar")
    sub.add_parser("bill", help="Enter billing from bookings.csv into JM portal")

    args = parser.parse_args()

    with sync_playwright() as playwright:
        if args.command == "extract":
            run_extract(playwright)
        elif args.command == "bill":
            run_bill(playwright)


if __name__ == "__main__":
    main()
