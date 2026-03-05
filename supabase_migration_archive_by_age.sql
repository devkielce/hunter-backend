-- Archive listings older than N months (by auction_date).
-- Run in Supabase SQL editor once after supabase_migration_source_archive.sql.
-- Used for komornik, e_licytacje, amw, facebook after "not seen in 5 runs" step.
--
-- Plan: (1) RPC parameter order (p_interval, p_source) matches PostgREST schema cache
--       so the function is found when called from Python. (2) Same logic: set
--       removed_from_source_at for listings where auction_date < now() - interval.

-- RPC: archive listings for source where auction_date is older than now() - p_interval
CREATE OR REPLACE FUNCTION public.archive_listings_older_than(
  p_interval TEXT DEFAULT '2 months',
  p_source TEXT
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
