"""Entry point: ``uv run lyra <command>``."""

import argparse

from playwright.sync_api import sync_playwright

from .bill import run_bill
from .daily import run_daily
from .extract import run_extract, run_upcoming
from .keys import run_keys


def main() -> None:
    parser = argparse.ArgumentParser(description="Lyra Automation")
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("extract", help="Extract historic bookings from Smart Brf calendar")
    sub.add_parser("upcoming", help="Extract upcoming bookings (next 13 days)")
    sub.add_parser("bill", help="Enter billing from bookings.csv into JM portal")
    sub.add_parser("keys", help="Create Seam access codes and email them to guests")
    sub.add_parser("daily", help="Daily pipeline: extract + keys + bill in one run")

    args = parser.parse_args()

    with sync_playwright() as playwright:
        if args.command == "extract":
            run_extract(playwright)
        elif args.command == "upcoming":
            run_upcoming(playwright)
        elif args.command == "bill":
            run_bill(playwright)
        elif args.command == "keys":
            run_keys(playwright)
        elif args.command == "daily":
            run_daily(playwright)


if __name__ == "__main__":
    main()
