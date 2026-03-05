"""Run one or all scrapers, upsert to Supabase, log scrape_runs."""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Callable, Optional

import httpx
from loguru import logger

from hunter.config import get_config
from hunter.http_utils import DEFAULT_HEADERS
from hunter.image_downloader import download_listing_images
from hunter.investment_score import compute_investment_score, compute_medians_per_region
from hunter.logging_config import setup_logging
from hunter.price_fallback import fetch_price_from_url
from hunter.schema import for_supabase
from hunter.scrapers.common import is_likely_error_page, is_rental_only
from hunter.supabase_client import (
    archive_listings_not_seen_in_last_n_runs,
    archive_listings_older_than,
    get_client,
    log_scrape_run,
    upsert_listings,
)

# Active scrapers only (e_licytacje, komornik, amw; Facebook via webhook)
SCRAPER_NAMES = ["komornik", "e_licytacje", "amw"]

# Sources that have auction_date (or post date) → also archive by age (older than N months)
SOURCES_WITH_AUCTION_DATE = ("komornik", "e_licytacje", "amw", "facebook")


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
            log.info("Scraper returned 0 listings (nothing to upsert for this source)")
            finished_at = datetime.now(timezone.utc).isoformat()
            client = get_client()
            log_scrape_run(client, name, started_at, finished_at, 0, 0, "success", None)
            archive_listings_not_seen_in_last_n_runs(client, name, n=5)
            if name in SOURCES_WITH_AUCTION_DATE:
                months = cfg.get("scraping", {}).get("archive_older_than_months", 2)
                archive_listings_older_than(client, name, interval=f"{months} months")
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
        # Tylko lokale na sprzedaż: odrzuć oferty wyłącznie na wynajem (wszystkie scrapery)
        n_before_sale_filter = len(rows_clean)
        rows_clean = [r for r in rows_clean if not is_rental_only(r.get("title"), r.get("description"))]
        if len(rows_clean) < n_before_sale_filter:
            logger.bind(source=name).info(
                "Filtered out {} rental-only listing(s) (keeping sale/auction only)",
                n_before_sale_filter - len(rows_clean),
            )
        # Gdy brak ceny – pobierz stronę szczegółową (source_url) i wyciągnij cenę (wszystkie scrapery)
        scraping_cfg = cfg.get("scraping", {})
        if scraping_cfg.get("follow_link_for_price", True):
            delay = float(scraping_cfg.get("httpx_delay_seconds", 1.5))
            with httpx.Client(
                headers=DEFAULT_HEADERS, timeout=60.0, follow_redirects=True
            ) as client:
                for r in rows_clean:
                    if r.get("price_pln") is not None:
                        continue
                    url = (r.get("source_url") or "").strip()
                    if not url:
                        continue
                    price_pln = fetch_price_from_url(
                        url, client, delay=delay, timeout=15.0
                    )
                    if price_pln is not None:
                        r["price_pln"] = price_pln
                        r.setdefault("raw_data", {})["price_from_detail_page"] = True
                        logger.bind(source=name).debug(
                            "Price from detail page: {} grosze", price_pln
                        )
        # Opcjonalnie: pobierz zdjęcia i wgraj do Supabase Storage (listing.images → URL-e z bucketu)
        if scraping_cfg.get("download_images"):
            timeout = float(scraping_cfg.get("download_images_timeout_seconds") or 15.0)
            with httpx.Client(
                headers=DEFAULT_HEADERS, timeout=timeout, follow_redirects=True
            ) as http_client:
                supabase_client = get_client()
                rows_clean = [
                    download_listing_images(r, http_client, supabase_client, cfg)
                    for r in rows_clean
                ]
        medians = compute_medians_per_region(rows_clean)
        for r in rows_clean:
            r.setdefault("raw_data", {})
            score = compute_investment_score(r, medians, cfg)
            r["raw_data"]["investment_score"] = score
        prepared = [for_supabase(r) for r in rows_clean]
        finished_at = datetime.now(timezone.utc).isoformat()
        for row in prepared:
            row["last_seen_at"] = finished_at
        client = get_client()
        listings_upserted = upsert_listings(client, prepared)
        log_scrape_run(
            client, name, started_at, finished_at,
            listings_found, listings_upserted, "success", None,
        )
        archive_listings_not_seen_in_last_n_runs(client, name, n=5)
        if name in SOURCES_WITH_AUCTION_DATE:
            months = cfg.get("scraping", {}).get("archive_older_than_months", 2)
            archive_listings_older_than(client, name, interval=f"{months} months")
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
    """Run scrapers in sequence. komornik, e_licytacje, amw; config.scraping.sources can restrict further."""
    from hunter.scrapers import scrape_komornik, scrape_elicytacje, scrape_amw
    cfg = config or get_config()
    setup_logging(cfg)
    all_scrapers = [
        ("komornik", scrape_komornik),
        ("e_licytacje", scrape_elicytacje),
        ("amw", scrape_amw),
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
    """Run a single scraper by name (komornik, e_licytacje, or amw)."""
    from hunter.scrapers import scrape_komornik, scrape_elicytacje, scrape_amw
    cfg = config or get_config()
    setup_logging(cfg)
    map_fn = {
        "komornik": scrape_komornik,
        "e_licytacje": scrape_elicytacje,
        "amw": scrape_amw,
    }
    fn = map_fn.get(source)
    if not fn:
        raise ValueError(f"Unknown source: {source}. Choose from {list(map_fn)}")
    run_scraper(source, fn, cfg, dry_run=dry_run)
