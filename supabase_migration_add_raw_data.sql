-- Add raw_data if your listings table was created from an older schema or frontend-only migration.
-- Run in Supabase SQL editor once. Taskmaster schema (supabase_schema.sql) already includes this column.

ALTER TABLE public.listings ADD COLUMN IF NOT EXISTS raw_data JSONB DEFAULT '{}';
