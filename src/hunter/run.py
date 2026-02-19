"""Run one or all scrapers, upsert to Supabase, log scrape_runs."""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Callable, Optional

from loguru import logger

from hunter.config import get_config
from hunter.logging_config import setup_logging
from hunter.schema import for_supabase
from hunter.scrapers.common import is_likely_error_page
from hunter.supabase_client import get_client, log_scrape_run, upsert_listings

# Active scrapers only (e_licytacje, komornik; Facebook via webhook)
SCRAPER_NAMES = ["komornik", "e_licytacje"]


def run_scraper(
    name: str,
    scrape_fn: Callable[[dict], list[dict[str, Any]]],
    config: Optional[dict] = None,
    dry_run: bool = False,
) -> tuple[int, int, str, Optional[str]]:
    """
    Run a scraper, upsert results, log scrape_run.
    Returns (listings_found, listings_upserted, status, error_message).
    If dry_run=True, only run the scraper and do not call Supabase.
    """
    cfg = config or get_config()
    started_at = datetime.now(timezone.utc).isoformat()
    listings_found = 0
    listings_upserted = 0
    status = "success"
    error_message: Optional[str] = None

    try:
        rows = scrape_fn(cfg)
        listings_found = len(rows)
        log = logger.bind(source=name)
        if dry_run:
            log.info("[dry-run] found {} listings (Supabase skipped)", listings_found)
            if rows:
                sample = rows[0]
                log.info("[dry-run] sample: title={!r} source_url={}", sample.get("title"), sample.get("source_url"))
            return listings_found, 0, "success", None

        if not rows:
            finished_at = datetime.now(timezone.utc).isoformat()
            client = get_client()
            log_scrape_run(client, name, started_at, finished_at, 0, 0, "success", None)
            return 0, 0, "success", None

        # Defense-in-depth: skip any row that looks like an error page before upsert
        rows_clean = [
            r for r in rows
            if not is_likely_error_page(r.get("title"), r.get("description"))
        ]
        if len(rows_clean) < len(rows):
            logger.bind(source=name).warning(
                "Skipped {} listing(s) as likely error pages before upsert",
                len(rows) - len(rows_clean),
            )
        prepared = [for_supabase(r) for r in rows_clean]
        client = get_client()
        listings_upserted = upsert_listings(client, prepared)
        finished_at = datetime.now(timezone.utc).isoformat()
        log_scrape_run(
            client, name, started_at, finished_at,
            listings_found, listings_upserted, "success", None,
        )
        return listings_found, listings_upserted, "success", None
    except Exception as e:
        status = "error"
        error_message = str(e)
        logger.exception("Scraper {} failed: {}", name, e)
        finished_at = datetime.now(timezone.utc).isoformat()
        if not dry_run:
            try:
                client = get_client()
                log_scrape_run(
                    client, name, started_at, finished_at,
                    listings_found, listings_upserted, "error", error_message,
                )
            except Exception:
                pass
        return listings_found, listings_upserted, "error", error_message


def run_all(config: Optional[dict] = None, dry_run: bool = False) -> None:
    """Run scrapers in sequence. Only komornik and e_licytacje; config.scraping.sources can restrict further."""
    from hunter.scrapers import scrape_komornik, scrape_elicytacje
    cfg = config or get_config()
    setup_logging(cfg)
    all_scrapers = [
        ("komornik", scrape_komornik),
        ("e_licytacje", scrape_elicytacje),
    ]
    sources = cfg.get("scraping", {}).get("sources")
    if sources:
        scrapers = [(n, fn) for n, fn in all_scrapers if n in sources]
    else:
        scrapers = all_scrapers
    for name, fn in scrapers:
        logger.bind(source=name).info("Running scraper")
        run_scraper(name, fn, cfg, dry_run=dry_run)
    logger.info("All scrapers finished" + (" [dry-run]" if dry_run else ""))


def run_one(source: str, config: Optional[dict] = None, dry_run: bool = False) -> None:
    """Run a single scraper by name (komornik or e_licytacje)."""
    from hunter.scrapers import scrape_komornik, scrape_elicytacje
    cfg = config or get_config()
    setup_logging(cfg)
    map_fn = {
        "komornik": scrape_komornik,
        "e_licytacje": scrape_elicytacje,
    }
    fn = map_fn.get(source)
    if not fn:
        raise ValueError(f"Unknown source: {source}. Choose from {list(map_fn)}")
    run_scraper(source, fn, cfg, dry_run=dry_run)
