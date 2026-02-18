-- Run this if you already have listings from an older backend schema (no status/notified/alert_rules/RLS).
-- New installs: use supabase_schema.sql (taskmaster) instead.

-- Add frontend-needed columns to existing listings table
ALTER TABLE public.listings ADD COLUMN IF NOT EXISTS status TEXT NOT NULL DEFAULT 'new';
ALTER TABLE public.listings ADD COLUMN IF NOT EXISTS notified BOOLEAN NOT NULL DEFAULT false;
ALTER TABLE public.listings ADD COLUMN IF NOT EXISTS raw_data JSONB DEFAULT '{}';

-- Constraint only if not already present (avoid errors on re-run)
DO $$
BEGIN
  IF NOT EXISTS (
    SELECT 1 FROM pg_constraint WHERE conname = 'listings_status_check'
  ) THEN
    ALTER TABLE public.listings ADD CONSTRAINT listings_status_check
      CHECK (status IN ('new', 'contacted', 'viewed', 'archived'));
  END IF;
END $$;

-- Indexes for dashboard and cron
CREATE INDEX IF NOT EXISTS listings_source_url_idx ON public.listings (source_url);
CREATE INDEX IF NOT EXISTS listings_created_at_idx ON public.listings (created_at DESC);
CREATE INDEX IF NOT EXISTS listings_source_idx ON public.listings (source);
CREATE INDEX IF NOT EXISTS listings_notified_idx ON public.listings (notified) WHERE notified = false;

-- Email digest recipients (frontend)
CREATE TABLE IF NOT EXISTS public.alert_rules (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  email TEXT NOT NULL UNIQUE,
  created_at TIMESTAMPTZ DEFAULT now()
);

-- RLS (MVP: allow all; align with taskmaster supabase_schema.sql)
ALTER TABLE public.listings ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.alert_rules ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.scrape_runs ENABLE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS "Allow all on listings" ON public.listings;
CREATE POLICY "Allow all on listings" ON public.listings FOR ALL USING (true) WITH CHECK (true);

DROP POLICY IF EXISTS "Allow all on alert_rules" ON public.alert_rules;
CREATE POLICY "Allow all on alert_rules" ON public.alert_rules FOR ALL USING (true) WITH CHECK (true);

DROP POLICY IF EXISTS "Allow all on scrape_runs" ON public.scrape_runs;
CREATE POLICY "Allow all on scrape_runs" ON public.scrape_runs FOR ALL USING (true) WITH CHECK (true);
