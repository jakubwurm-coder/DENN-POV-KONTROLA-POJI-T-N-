from __future__ import annotations

import os
import threading
import time
from typing import Any

import requests
from flask import jsonify, request

CLOUD_URL = os.getenv("DENNI_POV_CLOUD_URL", "https://denni-pov-kontrola.onrender.com").rstrip("/")
_CACHE_SECONDS = 10
_cache_lock = threading.Lock()
_cache_at = 0.0
_cache_annotations: dict[str, dict[str, str]] = {}


def _row_key(row: dict[str, Any]) -> str:
    vin = str(row.get("vin") or "").strip().upper()
    spz = str(row.get("spz_tir") or row.get("spz_uniqa") or "").strip().upper()
    return vin or (f"SPZ:{spz}" if spz else "")


def _invalidate_cache() -> None:
    global _cache_at
    with _cache_lock:
        _cache_at = 0.0


def _load_shared_annotations(force: bool = False) -> dict[str, dict[str, str]]:
    global _cache_at, _cache_annotations
    now = time.monotonic()
    with _cache_lock:
        if not force and _cache_at and now - _cache_at < _CACHE_SECONDS:
            return dict(_cache_annotations)

    try:
        response = requests.get(f"{CLOUD_URL}/api/annotations", timeout=6)
        response.raise_for_status()
        payload = response.json()
        annotations = payload.get("annotations") if isinstance(payload, dict) else {}
        if not isinstance(annotations, dict):
            annotations = {}
        clean: dict[str, dict[str, str]] = {}
        for key, value in annotations.items():
            if isinstance(value, dict):
                clean[str(key).strip().upper()] = {
                    "note": str(value.get("note") or ""),
                    "workflow_status": str(value.get("workflow_status") or ""),
                    "updated_at": str(value.get("updated_at") or ""),
                }
        with _cache_lock:
            _cache_annotations = clean
            _cache_at = now
        return dict(clean)
    except Exception as exc:
        print(f"Shared annotations load failed: {exc}")
        with _cache_lock:
            return dict(_cache_annotations)


def install_cloud_annotations(app, cloud_module) -> None:
    @app.get("/api/annotations")
    def api_annotations():
        with cloud_module._lock:
            data = cloud_module._load_state()
            legacy = data.get("annotations") or {}

        try:
            annotations = cloud_module._annotations_load_strict(legacy)
        except cloud_module.PersistenceUnavailable as exc:
            return jsonify({
                "ok": False,
                "storage": "postgres",
                "message": "Centrální statusy a poznámky nejsou dostupné.",
                "detail": str(exc),
            }), 503

        return jsonify({
            "ok": True,
            "storage": "postgres",
            "annotations": annotations,
        })


def install_local_annotations(app) -> None:
    @app.post("/api/result-meta")
    def api_result_meta_local():
        payload = request.get_json(silent=True)
        if not isinstance(payload, dict):
            return jsonify({"ok": False, "message": "Neplatná data."}), 400

        key = str(payload.get("key") or "").strip().upper()
        if not key:
            return jsonify({"ok": False, "message": "Chybí identifikace vozidla."}), 400

        note = str(payload.get("note") or "").strip()[:2000]
        workflow_status = str(payload.get("workflow_status") or "").strip().upper()
        if workflow_status not in {"", "VYŘEŠENO", "ŘEŠÍ SE", "KONTROLA"}:
            return jsonify({"ok": False, "message": "Nepovolený status."}), 400

        try:
            response = requests.post(
                f"{CLOUD_URL}/api/result-meta",
                json={"key": key, "note": note, "workflow_status": workflow_status},
                timeout=8,
            )
            try:
                data = response.json()
            except Exception:
                data = {"message": response.text[:300] or "Online server nevrátil JSON."}
            if not response.ok:
                return jsonify({
                    "ok": False,
                    "persisted": False,
                    "message": data.get("message") or "Centrální uložení selhalo.",
                    "detail": data.get("detail") or "",
                }), response.status_code

            if not bool(data.get("persisted")):
                return jsonify({
                    "ok": False,
                    "persisted": False,
                    "message": "Online server nepotvrdil trvalé uložení. Změna se nepovažuje za uloženou.",
                }), 502

            _invalidate_cache()
            return jsonify({
                "ok": True,
                "persisted": True,
                "storage": data.get("storage") or "postgres",
                "message": "Status a poznámka byly trvale uloženy a zobrazí se na ostatních počítačích.",
            })
        except Exception as exc:
            return jsonify({"ok": False, "message": f"Centrální uložení poznámky se nepodařilo: {exc}"}), 502

    @app.after_request
    def merge_shared_annotations(response):
        if request.path != "/api/state" or response.status_code != 200 or not response.is_json:
            return response
        try:
            payload = response.get_json(silent=True)
            if not isinstance(payload, dict):
                return response
            rows = payload.get("results") or []
            if not isinstance(rows, list):
                return response
            annotations = _load_shared_annotations()
            for row in rows:
                if not isinstance(row, dict):
                    continue
                meta = annotations.get(_row_key(row), {})
                row["note"] = str(meta.get("note") or "")
                row["workflow_status"] = str(meta.get("workflow_status") or "")
                row["workflow_updated_at"] = str(meta.get("updated_at") or "")
                if row["note"]:
                    row["original_detail"] = row.get("detail", "")
                    row["detail"] = row["note"]
                if row["workflow_status"]:
                    row["original_status"] = row.get("status", "")
                    row["status"] = row["workflow_status"]
            response.set_data(app.json.dumps(payload))
            response.content_type = "application/json"
        except Exception as exc:
            print(f"Shared annotations merge failed: {exc}")
        return response
