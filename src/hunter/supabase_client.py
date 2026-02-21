"""Supabase client with service role for upserts and scrape_runs logging."""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Optional

from loguru import logger

LISTINGS_TABLE = "listings"
SCRAPE_RUNS_TABLE = "scrape_runs"
ARCHIVE_RPC = "archive_listings_not_seen_since"


def get_client():
    from supabase import create_client
    from hunter.config import get_config
    cfg = get_config().get("supabase", {})
    url = cfg.get("url")
    key = cfg.get("service_role_key")
    if not url or not key:
        raise ValueError("supabase.url and supabase.service_role_key required (config or env)")
    return create_client(url, key)


def _rows_without_region(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Return copies of rows with 'region' key removed (for DBs that don't have the column yet)."""
    return [{k: v for k, v in r.items() if k != "region"} for r in rows]


def _rows_without_last_seen_at(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Return copies of rows with 'last_seen_at' key removed (for DBs that don't have the column yet)."""
    return [{k: v for k, v in r.items() if k != "last_seen_at"} for r in rows]


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
        err_msg = str(e) if e else ""
        # Table may not have 'region' column yet (PGRST204). Retry without region so upsert succeeds.
        if "PGRST204" in err_msg and "region" in err_msg.lower():
            logger.warning(
                "Supabase listings table has no 'region' column; retrying upsert without region. "
                "Add column 'region' (text) to persist region for frontend filtering."
            )
            result = (
                client.table(LISTINGS_TABLE)
                .upsert(_rows_without_region(rows), on_conflict="source_url")
                .execute()
            )
            count = len(result.data) if result.data is not None else len(rows)
            logger.info("Upserted {} listings (without region)", count)
            return count
        # Table may not have 'last_seen_at' column yet (PGRST204). Retry without it.
        if "PGRST204" in err_msg and "last_seen_at" in err_msg.lower():
            logger.warning(
                "Supabase listings table has no 'last_seen_at' column; retrying upsert without it. "
                "Run supabase_migration_source_archive.sql to add source-archive support."
            )
            result = (
                client.table(LISTINGS_TABLE)
                .upsert(_rows_without_last_seen_at(rows), on_conflict="source_url")
                .execute()
            )
            count = len(result.data) if result.data is not None else len(rows)
            logger.info("Upserted {} listings (without last_seen_at)", count)
            return count
        logger.exception("Supabase upsert failed: {}", e)
        raise


def archive_listings_not_seen_in_last_n_runs(
    client: Any,
    source: str,
    n: int = 5,
) -> int:
    """
    Mark listings as removed-from-source if not seen in the last n successful runs.
    Only runs when there are at least n successful runs for this source.
    Sets removed_from_source_at = now(), notified = true. Does not change status.
    Returns number of listings updated.
    """
    try:
        runs = (
            client.table(SCRAPE_RUNS_TABLE)
            .select("started_at")
            .eq("source", source)
            .eq("status", "success")
            .not_.is_("finished_at", "null")
            .order("finished_at", desc=True)
            .limit(n)
            .execute()
        )
        data = runs.data or []
        if len(data) < n:
            return 0
        cutoff = data[n - 1]["started_at"]
        if not cutoff:
            return 0
        result = client.rpc(ARCHIVE_RPC, {"p_source": source, "p_cutoff": cutoff}).execute()
        raw = result.data
        if raw is None:
            count = 0
        elif isinstance(raw, list) and raw:
            count = int(raw[0])
        else:
            count = int(raw)
        if count > 0:
            logger.bind(source=source).info(
                "Archived {} listings (not seen in last {} runs)",
                count,
                n,
            )
        return count
    except Exception as e:
        logger.bind(source=source).warning("Archive step failed (listings unchanged): {}", e)
        return 0


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
