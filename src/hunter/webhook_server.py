"""
Flask server for Apify webhook: POST /webhook/apify.
Verifies x-apify-webhook-secret (if configured), extracts dataset ID, runs process_apify_dataset, returns 200.
On-demand scrapers: POST /api/run starts a background run and returns 202; GET /api/run/status returns run state.
"""
from __future__ import annotations

import os
import threading
from typing import Any

from flask import Flask, request, jsonify
from loguru import logger

from hunter.apify_facebook import process_apify_dataset
from hunter.config import get_config
from hunter.logging_config import setup_logging

app = Flask(__name__)

# Background run state (in-memory; lost on restart).
_run_state: dict[str, Any] = {
    "status": "idle",
    "started_at": None,
    "finished_at": None,
    "results": None,
    "error": None,
}
_run_lock = threading.Lock()


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
    logger.info("Apify webhook received, dataset_id={}", dataset_id or "(missing)")
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


def _check_run_secret() -> tuple[bool, Any]:
    """Return (True, None) if auth OK, else (False, response_tuple)."""
    cfg = get_config()
    secret = (cfg.get("run_api") or {}).get("secret") or (cfg.get("apify", {}) or {}).get("webhook_secret")
    if not secret or not isinstance(secret, str) or not secret.strip():
        return True, None
    provided = request.headers.get("x-run-secret") or request.headers.get("X-Run-Secret")
    if provided != secret.strip():
        return False, (jsonify({"error": "Unauthorized"}), 401)
    return True, None


# When triggered via POST /api/run (Odśwież oferty), cap total listings so the run is quick. Daily/cron scrape is unchanged.
ON_DEMAND_MAX_LISTINGS = 20


def _run_scrapers_background() -> None:
    """Run all scrapers and update _run_state when done. Runs in a daemon thread."""
    from hunter.run import run_scraper
    from hunter.scrapers import scrape_komornik, scrape_elicytacje, scrape_amw
    try:
        cfg = get_config()
        # When triggered via API (Odśwież oferty), limit pages and total listings; daily/cron scrape is unaffected.
        scraping = cfg.get("scraping", {})
        on_demand_pages = scraping.get("on_demand_max_pages_auctions")
        on_demand_listings = scraping.get("on_demand_max_listings")
        max_listings = int(on_demand_listings) if on_demand_listings is not None else ON_DEMAND_MAX_LISTINGS
        scraping_overrides = {}
        if on_demand_pages is not None:
            scraping_overrides["max_pages_auctions"] = int(on_demand_pages)
        scraping_overrides["max_listings"] = max_listings
        cfg = {**cfg, "scraping": {**scraping, **scraping_overrides}}
        all_scrapers = [
            ("komornik", scrape_komornik),
            ("e_licytacje", scrape_elicytacje),
            ("amw", scrape_amw),
        ]
        sources = cfg.get("scraping", {}).get("sources")
        scrapers = [(n, fn) for n, fn in all_scrapers if n in sources] if sources else all_scrapers
        results = []
        remaining = max_listings
        for name, fn in scrapers:
            if remaining <= 0:
                results.append({
                    "source": name,
                    "listings_found": 0,
                    "listings_upserted": 0,
                    "status": "skipped",
                    "error_message": "On-demand cap reached",
                })
                continue
            cfg_for_scraper = {**cfg, "scraping": {**cfg["scraping"], "max_listings": remaining}}
            found, upserted, status, err = run_scraper(name, fn, cfg_for_scraper, dry_run=False)
            results.append({
                "source": name,
                "listings_found": found,
                "listings_upserted": upserted,
                "status": status,
                "error_message": err,
            })
            remaining = max(0, remaining - found)
        with _run_lock:
            _run_state["status"] = "completed"
            _run_state["finished_at"] = __import__("datetime").datetime.now(__import__("datetime").timezone.utc).isoformat()
            _run_state["results"] = results
            _run_state["error"] = None
    except Exception as e:
        logger.exception("Background scrapers failed: {}", e)
        with _run_lock:
            _run_state["status"] = "error"
            _run_state["finished_at"] = __import__("datetime").datetime.now(__import__("datetime").timezone.utc).isoformat()
            _run_state["results"] = _run_state.get("results") or []
            _run_state["error"] = str(e)


@app.route("/api/run", methods=["POST"])
def api_run():
    """
    Start scrapers in the background. Returns 202 Accepted immediately.
    Poll GET /api/run/status for completion and results.
    If a run is already in progress, returns 409 Conflict.
    """
    try:
        setup_logging(get_config())
        ok, err_response = _check_run_secret()
        if not ok:
            return err_response[0], err_response[1]
        with _run_lock:
            if _run_state.get("status") == "running":
                return jsonify({"ok": False, "error": "Run already in progress", "status": "running"}), 409
            _run_state["status"] = "running"
            _run_state["started_at"] = __import__("datetime").datetime.now(__import__("datetime").timezone.utc).isoformat()
            _run_state["finished_at"] = None
            _run_state["results"] = None
            _run_state["error"] = None
        t = threading.Thread(target=_run_scrapers_background, daemon=True)
        t.start()
        return jsonify({
            "ok": True,
            "status": "started",
            "message": "Scrapers running in background. Poll GET /api/run/status for completion.",
        }), 202
    except Exception as e:
        logger.exception("POST /api/run failed: {}", e)
        return jsonify({"ok": False, "error": str(e)}), 500


@app.route("/api/run/status", methods=["GET"])
def api_run_status():
    """
    Return current run state: status (idle|running|completed|error), started_at, finished_at, results, error.
    Same X-Run-Secret auth as POST /api/run.
    """
    try:
        setup_logging(get_config())
        ok, err_response = _check_run_secret()
        if not ok:
            return err_response[0], err_response[1]
        with _run_lock:
            state = dict(_run_state)
        return jsonify({"ok": True, **state}), 200
    except Exception as e:
        logger.exception("GET /api/run/status failed: {}", e)
        return jsonify({"ok": False, "error": str(e)}), 500


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
