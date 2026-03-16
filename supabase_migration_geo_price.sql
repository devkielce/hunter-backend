-- Migration: add region and price_per_m2 columns to listings
-- Run once in Supabase SQL editor.

-- region: województwo (e.g. "mazowieckie") for geographic filtering
ALTER TABLE public.listings ADD COLUMN IF NOT EXISTS region TEXT;

-- price_per_m2: price per m² in PLN (computed from price_pln/100 / surface_m2)
ALTER TABLE public.listings ADD COLUMN IF NOT EXISTS price_per_m2 NUMERIC;

-- Indexes for fast filtering
CREATE INDEX IF NOT EXISTS listings_region_idx ON public.listings (region);
CREATE INDEX IF NOT EXISTS listings_price_per_m2_idx ON public.listings (price_per_m2);
