-- Required for upsert by source_url. Run if you get:
-- "there is no unique or exclusion constraint matching the ON CONFLICT specification" (42P10).
-- If you have duplicate source_url rows, deduplicate before running this.

-- Option A: unique index (enough for ON CONFLICT (source_url))
CREATE UNIQUE INDEX IF NOT EXISTS listings_source_url_key ON public.listings (source_url);

-- Option B: if you prefer an explicit constraint (optional; index above is sufficient)
-- ALTER TABLE public.listings ADD CONSTRAINT listings_source_url_key UNIQUE (source_url);
