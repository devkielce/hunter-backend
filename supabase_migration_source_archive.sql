-- Archive listings not seen in last 5 runs (source-removed).
-- Run in Supabase SQL editor once. Safe to run on existing DB.

-- New columns on listings
ALTER TABLE public.listings ADD COLUMN IF NOT EXISTS last_seen_at TIMESTAMPTZ;
ALTER TABLE public.listings ADD COLUMN IF NOT EXISTS removed_from_source_at TIMESTAMPTZ;

-- Index for "active" listings (default frontend filter)
CREATE INDEX IF NOT EXISTS listings_removed_from_source_at_idx
  ON public.listings (removed_from_source_at) WHERE removed_from_source_at IS NULL;

-- Preserve removed_from_source_at on UPDATE (once set, never cleared by upsert)
CREATE OR REPLACE FUNCTION public.preserve_removed_from_source_at()
RETURNS TRIGGER AS $$
BEGIN
  IF OLD.removed_from_source_at IS NOT NULL AND (NEW.removed_from_source_at IS NULL OR NEW.removed_from_source_at = OLD.removed_from_source_at) THEN
    NEW.removed_from_source_at := OLD.removed_from_source_at;
  END IF;
  RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS listings_preserve_removed_from_source_at ON public.listings;
CREATE TRIGGER listings_preserve_removed_from_source_at
  BEFORE UPDATE ON public.listings
  FOR EACH ROW EXECUTE FUNCTION public.preserve_removed_from_source_at();

-- RPC: archive listings for source not seen since cutoff (returns count updated)
CREATE OR REPLACE FUNCTION public.archive_listings_not_seen_since(
  p_source TEXT,
  p_cutoff TIMESTAMPTZ
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
      AND (last_seen_at IS NULL OR last_seen_at < p_cutoff)
    RETURNING id
  )
  SELECT count(*)::INT INTO updated_count FROM updated;
  RETURN updated_count;
END;
$$;
