"""Entry point: ``uv run python -m lyra <command>``."""

import argparse

from playwright.sync_api import sync_playwright


def main() -> None:
    parser = argparse.ArgumentParser(description="Lyra Automation")
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("extract", help="Extract bookings from Smart Brf calendar")
    sub.add_parser("bill", help="Enter billing from bookings.csv into JM portal")

    args = parser.parse_args()

    with sync_playwright() as playwright:
        if args.command == "extract":
            from .extract import run_extract

            run_extract(playwright)
        elif args.command == "bill":
            from .bill import run_bill

            run_bill(playwright)


if __name__ == "__main__":
    main()
