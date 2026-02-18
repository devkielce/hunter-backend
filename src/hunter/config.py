"""Load config from config.yaml and env."""
from __future__ import annotations

import os
from pathlib import Path
from typing import Any

def _load_yaml(path: Path) -> dict[str, Any]:
    try:
        import yaml
    except ImportError:
        return {}
    if not path.exists():
        return {}
    with open(path, encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


def get_config() -> dict[str, Any]:
    root = Path(__file__).resolve().parents[2]
    cfg = _load_yaml(root / "config.yaml") or _load_yaml(root / "config.example.yaml")
    # Env overrides
    if url := os.getenv("SUPABASE_URL"):
        cfg.setdefault("supabase", {})["url"] = url
    if key := os.getenv("SUPABASE_SERVICE_ROLE_KEY"):
        cfg.setdefault("supabase", {})["service_role_key"] = key
    if token := os.getenv("APIFY_TOKEN"):
        cfg.setdefault("apify", {})["token"] = token
    if secret := os.getenv("APIFY_WEBHOOK_SECRET"):
        cfg.setdefault("apify", {})["webhook_secret"] = secret
    return cfg
