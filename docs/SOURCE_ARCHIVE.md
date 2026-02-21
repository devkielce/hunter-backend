# Source-archive: listings not seen in last 5 runs

After each **successful** scrape run per source, the backend marks listings as "removed from source" if they were **not seen in the last 5 successful runs** for that source.

## Behaviour

- **Columns:** `last_seen_at` (set on every scraper upsert), `removed_from_source_at` (set by the archive step). See [supabase_schema.sql](../supabase_schema.sql) or [supabase_migration_source_archive.sql](../supabase_migration_source_archive.sql).
- **When:** Archive step runs only when the source has **at least 5 successful runs** in `scrape_runs`. Then we take the 5th-to-last run’s `started_at` as the cutoff; any listing for that source with `last_seen_at < cutoff` (or `last_seen_at IS NULL`) and not already archived gets `removed_from_source_at = now()` and `notified = true`. **Status is not changed** (e.g. contacted stays contacted).
- **No dis-archive:** Once `removed_from_source_at` is set, it is never cleared by the backend (a DB trigger preserves it on update). Listings that reappear on the site may be upserted to refresh data but remain archived.
- **Daily run:** With one run per day, "not seen in 5 runs" means not seen for 5 days.

## Frontend

- Default list should filter with **`removed_from_source_at IS NULL`** so source-archived listings are hidden. Optionally add a toggle or section for "Removed from source".

## Migration

Run [supabase_migration_source_archive.sql](../supabase_migration_source_archive.sql) in the Supabase SQL editor once to add columns, trigger, and RPC. Until then, the backend still works (upsert retries without `last_seen_at` if the column is missing).
