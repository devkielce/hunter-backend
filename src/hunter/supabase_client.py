"""Supabase client with service role for upserts and scrape_runs logging."""
from __future__ import annotations

from typing import Any, Optional

from loguru import logger

LISTINGS_TABLE = "listings"
SCRAPE_RUNS_TABLE = "scrape_runs"


def get_client():
    from supabase import create_client
    from hunter.config import get_config
    cfg = get_config().get("supabase", {})
    url = cfg.get("url")
    key = cfg.get("service_role_key")
    if not url or not key:
        raise ValueError("supabase.url and supabase.service_role_key required (config or env)")
    return create_client(url, key)


def upsert_listings(client: Any, rows: list[dict[str, Any]]) -> int:
    """Idempotent upsert by source_url (no select-before-insert). Preserves status/notified."""
    if not rows:
        return 0
    try:
        result = (
            client.table(LISTINGS_TABLE)
            .upsert(rows, on_conflict="source_url")
            .execute()
        )
        count = len(result.data) if result.data is not None else len(rows)
        logger.info("Upserted {} listings", count)
        return count
    except Exception as e:
        logger.exception("Supabase upsert failed: {}", e)
        raise


def log_scrape_run(
    client: Any,
    source: str,
    started_at: str,
    finished_at: Optional[str],
    listings_found: int,
    listings_upserted: int,
    status: str,
    error_message: Optional[str] = None,
) -> None:
    """Insert one row into scrape_runs."""
    row = {
        "source": source,
        "started_at": started_at,
        "finished_at": finished_at,
        "listings_found": listings_found,
        "listings_upserted": listings_upserted,
        "status": status,
        "error_message": error_message,
    }
    try:
        client.table(SCRAPE_RUNS_TABLE).insert(row).execute()
        logger.bind(source=source).info(
            "Scrape run logged: status={} listings_upserted={}",
            status,
            listings_upserted,
        )
    except Exception as e:
        logger.bind(source=source).warning("Failed to log scrape_run: {}", e)
