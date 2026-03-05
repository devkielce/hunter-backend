"""
Download listing images from source URLs and upload to Supabase Storage.
When enabled (scraping.download_images), listing.images are replaced by Storage public URLs
so the frontend can serve them from your bucket (no remotePatterns for OLX/Gratka etc.).
"""
from __future__ import annotations

import hashlib
import re
import time
from typing import Any, Optional

import httpx
from loguru import logger

from hunter.http_utils import DEFAULT_HEADERS

# Content-Type -> file extension
_CONTENT_TYPE_EXT = {
    "image/jpeg": "jpg",
    "image/jpg": "jpg",
    "image/png": "png",
    "image/gif": "gif",
    "image/webp": "webp",
}


def _safe_slug(source: str, source_url: str) -> str:
    """Unique path-safe slug per listing: source + short hash of source_url."""
    h = hashlib.sha256(source_url.encode("utf-8")).hexdigest()[:12]
    safe_source = re.sub(r"[^a-z0-9]", "_", source.lower())
    return f"{safe_source}_{h}"


def _extension_from_content_type(content_type: Optional[str]) -> str:
    if not content_type:
        return "jpg"
    ct = content_type.split(";")[0].strip().lower()
    return _CONTENT_TYPE_EXT.get(ct, "jpg")


def download_listing_images(
    listing: dict[str, Any],
    http_client: httpx.Client,
    supabase_client: Any,
    config: Optional[dict[str, Any]] = None,
) -> dict[str, Any]:
    """
    For each URL in listing["images"], fetch the image and upload to Supabase Storage.
    Replaces listing["images"] with the list of public Storage URLs (only successful uploads).
    Returns a copy of the listing with updated "images" (and raw_data["images_uploaded"] = true).
    If download_images is disabled or bucket missing, returns listing unchanged.
    """
    cfg = config or {}
    scraping = cfg.get("scraping") or {}
    if not scraping.get("download_images"):
        return listing

    bucket = (cfg.get("supabase") or {}).get("storage_bucket") or "listing-images"
    max_per_listing = int(scraping.get("download_images_max_per_listing") or 5)
    delay = float(scraping.get("httpx_delay_seconds") or 1.5)
    timeout = float(scraping.get("download_images_timeout_seconds") or 15.0)

    images = listing.get("images") or []
    if not isinstance(images, list) or not images:
        return listing

    source = (listing.get("source") or "unknown").strip() or "unknown"
    source_url = (listing.get("source_url") or "").strip()
    if not source_url:
        return listing

    slug = _safe_slug(source, source_url)
    new_urls: list[str] = []
    to_fetch = images[:max_per_listing]

    for idx, url in enumerate(to_fetch):
        if not isinstance(url, str) or not url.strip():
            continue
        url = url.strip()
        try:
            time.sleep(delay)
            resp = http_client.get(url, timeout=timeout)
            if resp.status_code != 200:
                logger.debug("Image GET {} -> {} (skip)", url[:60], resp.status_code)
                continue
            content_type = resp.headers.get("content-type")
            if content_type and "image/" not in content_type.split(";")[0].lower():
                logger.debug("Image URL not image/*: {} (skip)", url[:60])
                continue
            body = resp.content
            if not body or len(body) > 10 * 1024 * 1024:  # 10 MB cap
                logger.debug("Image empty or too large (skip): {}", url[:60])
                continue
            ext = _extension_from_content_type(content_type)
            path = f"listings/{slug}/{idx}.{ext}"
            file_options: dict[str, str] = {"upsert": "true"}
            if content_type:
                file_options["content-type"] = content_type.split(";")[0].strip()
            supabase_client.storage.from_(bucket).upload(path, body, file_options)
            public_url = supabase_client.storage.from_(bucket).get_public_url(path)
            new_urls.append(public_url)
        except Exception as e:
            logger.debug("Download/upload image failed {}: {}", url[:60], e)
            continue

    if not new_urls:
        return listing

    out = dict(listing)
    out["images"] = new_urls
    out.setdefault("raw_data", {})
    out["raw_data"] = dict(out["raw_data"])
    out["raw_data"]["images_uploaded"] = True
    return out
