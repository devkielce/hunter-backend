"""CLI: run one source, all sources, or start scheduler."""
from __future__ import annotations

import argparse
import sys


def main() -> None:
    parser = argparse.ArgumentParser(description="Hunter scraping backend")
    sub = parser.add_subparsers(dest="command", help="Command")
    # run all
    run_all_parser = sub.add_parser("run-all", help="Run all scrapers once and exit")
    run_all_parser.add_argument("--dry-run", action="store_true", help="Scrape only, no Supabase")
    # run one
    run_one_parser = sub.add_parser("run", help="Run a single scraper")
    run_one_parser.add_argument(
        "source",
        choices=["komornik", "e_licytacje", "amw"],
        help="Source to scrape",
    )
    run_one_parser.add_argument("--dry-run", action="store_true", help="Scrape only, no Supabase")
    # scheduler
    sub.add_parser("schedule", help="Start scheduler (blocking)")
    # webhook server for Apify (Facebook)
    sub.add_parser("webhook", help="Start Flask server for Apify webhook (POST /webhook/apify)")
    args = parser.parse_args()

    if args.command == "run-all":
        from hunter.run import run_all
        run_all(dry_run=getattr(args, "dry_run", False))
    elif args.command == "run":
        from hunter.run import run_one
        run_one(args.source, dry_run=args.dry_run)
    elif args.command == "schedule":
        from hunter.scheduler import start_scheduler
        start_scheduler()
    elif args.command == "webhook":
        from hunter.webhook_server import main as webhook_main
        webhook_main()
    else:
        parser.print_help()
        sys.exit(1)


if __name__ == "__main__":
    main()
