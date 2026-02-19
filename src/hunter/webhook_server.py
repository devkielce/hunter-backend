"""
Flask server for Apify webhook: POST /webhook/apify.
Verifies x-apify-webhook-secret (if configured), extracts dataset ID, runs process_apify_dataset, returns 200.
"""
from __future__ import annotations

import os

from flask import Flask, request, jsonify
from loguru import logger

from hunter.apify_facebook import process_apify_dataset
from hunter.config import get_config
from hunter.logging_config import setup_logging

app = Flask(__name__)


def _get_webhook_secret() -> str | None:
    cfg = get_config()
    secret = (cfg.get("apify", {}) or {}).get("webhook_secret")
    if secret and isinstance(secret, str):
        return secret.strip()
    return None


def _dataset_id_from_payload(body: dict) -> str | None:
    """datasetId lub resource.defaultDatasetId (Apify Run)."""
    if not isinstance(body, dict):
        return None
    did = body.get("datasetId")
    if isinstance(did, str) and did.strip():
        return did.strip()
    resource = body.get("resource")
    if isinstance(resource, dict):
        did = resource.get("defaultDatasetId")
        if isinstance(did, str) and did.strip():
            return did.strip()
    return None


@app.route("/webhook/apify", methods=["POST"])
def webhook_apify():
    """
    Apify wywołuje ten endpoint po zakończeniu aktora.
    Nagłówek: x-apify-webhook-secret (opcjonalnie, jeśli ustawiony w config).
    Body (JSON): datasetId lub resource.defaultDatasetId.
    """
    setup_logging(get_config())
    secret = _get_webhook_secret()
    if secret:
        provided = request.headers.get("x-apify-webhook-secret") or request.headers.get("X-Apify-Webhook-Secret")
        if provided != secret:
            logger.warning("Apify webhook: invalid or missing secret")
            return jsonify({"error": "Unauthorized"}), 401
    if not request.is_json:
        return jsonify({"error": "Content-Type must be application/json"}), 400
    body = request.get_json(silent=True) or {}
    dataset_id = _dataset_id_from_payload(body)
    if not dataset_id:
        logger.warning("Apify webhook: no datasetId or resource.defaultDatasetId in body")
        return jsonify({"error": "Missing datasetId or resource.defaultDatasetId"}), 400
    try:
        found, upserted = process_apify_dataset(dataset_id)
        return jsonify({"ok": True, "listings_found": found, "listings_upserted": upserted}), 200
    except ValueError as e:
        logger.warning("Apify webhook: {}", e)
        return jsonify({"error": str(e)}), 400
    except Exception as e:
        logger.exception("Apify webhook failed: {}", e)
        return jsonify({"error": "Internal error"}), 500


@app.route("/api/run", methods=["POST"])
def api_run():
    """
    Run all scrapers on demand (for navbar refresh button).
    Optional auth: set config run_api_secret and send header X-Run-Secret.
    Returns per-source results (listings_found, listings_upserted, status).
    """
    setup_logging(get_config())
    cfg = get_config()
    secret = (cfg.get("run_api") or {}).get("secret") or (cfg.get("apify", {}) or {}).get("webhook_secret")
    # #region agent log
    _log_path = "/Users/arturwillonski/Documents/hunter-backend/.cursor/debug.log"
    _secret_ok = secret and isinstance(secret, str) and bool(secret.strip())
    _provided = request.headers.get("x-run-secret") or request.headers.get("X-Run-Secret")
    _header_present = _provided is not None
    _provided_len = len(_provided) if _provided else 0
    _expected_len = len(secret.strip()) if _secret_ok else 0
    _match = _provided == (secret.strip() if _secret_ok else None)
    _return_401 = _secret_ok and not _match
    _relevant_headers = [k for k in getattr(request.headers, "keys", lambda: [])() if "run" in k.lower() or "secret" in k.lower()]
    import json as _json
    try:
        with open(_log_path, "a") as _f:
            _f.write(_json.dumps({"hypothesisId": "H1", "message": "api_run auth check", "data": {"secret_configured": _secret_ok, "header_present": _header_present, "provided_len": _provided_len, "expected_len": _expected_len, "return_401": _return_401, "relevant_header_names": _relevant_headers}, "timestamp": __import__("time").time(), "location": "webhook_server.py:api_run"}) + "\n")
    except Exception:
        pass
    # #endregion
    if _secret_ok:
        provided = _provided
        if provided != secret.strip():
            return jsonify({"error": "Unauthorized"}), 401
    from hunter.run import run_scraper
    from hunter.scrapers import scrape_komornik, scrape_elicytacje
    all_scrapers = [
        ("komornik", scrape_komornik),
        ("e_licytacje", scrape_elicytacje),
    ]
    sources = cfg.get("scraping", {}).get("sources")
    if sources:
        scrapers = [(n, fn) for n, fn in all_scrapers if n in sources]
    else:
        scrapers = all_scrapers
    results = []
    for name, fn in scrapers:
        found, upserted, status, err = run_scraper(name, fn, cfg, dry_run=False)
        results.append({
            "source": name,
            "listings_found": found,
            "listings_upserted": upserted,
            "status": status,
            "error_message": err,
        })
    return jsonify({"ok": True, "results": results}), 200


@app.route("/health", methods=["GET"])
def health():
    return jsonify({"status": "ok"}), 200


def main() -> None:
    """Uruchom serwer (np. gunicorn lub flask run)."""
    setup_logging(get_config())
    port = int(os.getenv("PORT", "5000"))
    host = os.getenv("HOST", "0.0.0.0")
    logger.info("Starting webhook server on {}:{}", host, port)
    app.run(host=host, port=port)


if __name__ == "__main__":
    main()
