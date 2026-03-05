-- Create public bucket for listing images (used when scraping.download_images is true).
-- Run in Supabase SQL editor once. See docs/IMAGE_DOWNLOAD.md.

INSERT INTO storage.buckets (id, name, public)
VALUES ('listing-images', 'listing-images', true)
ON CONFLICT (id) DO UPDATE SET
  name = EXCLUDED.name,
  public = EXCLUDED.public;

-- Optional: allow uploads from service role (backend) and public read.
-- If you use RLS on storage.objects, add policies as needed for your project.
