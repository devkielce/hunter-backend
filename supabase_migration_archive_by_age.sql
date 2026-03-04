-- Archive listings older than N months (by auction_date).
-- Run in Supabase SQL editor once after supabase_migration_source_archive.sql.
-- Used for komornik, e_licytacje, amw after "not seen in 5 runs" step.

-- RPC: archive listings for source where auction_date is older than now() - p_interval
CREATE OR REPLACE FUNCTION public.archive_listings_older_than(
  p_source TEXT,
  p_interval TEXT DEFAULT '2 months'
)
RETURNS INT
LANGUAGE plpgsql
SECURITY DEFINER
AS $$
DECLARE
  updated_count INT;
BEGIN
  WITH updated AS (
    UPDATE public.listings
    SET removed_from_source_at = now(), notified = true
    WHERE source = p_source
      AND removed_from_source_at IS NULL
      AND auction_date IS NOT NULL
      AND auction_date < (now() - (p_interval::interval))
    RETURNING id
  )
  SELECT count(*)::INT INTO updated_count FROM updated;
  RETURN updated_count;
END;
$$;
