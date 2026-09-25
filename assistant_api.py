from __future__ import annotations

import hmac
import os
from typing import Any, Callable

from flask import jsonify, request


def install_assistant_api(app, load_state: Callable[[], dict[str, Any]], public_state: Callable[[dict[str, Any]], dict[str, Any]], lock) -> None:
    """Install a read-only API intended for ChatGPT/Voice integrations."""

    def authorized() -> bool:
        expected = os.getenv("ASSISTANT_API_TOKEN", "").strip()
        if not expected:
            return False
        supplied = request.headers.get("Authorization", "").strip()
        return hmac.compare_digest(supplied, f"Bearer {expected}")

    @app.get("/api/assistant/status")
    def assistant_status():
        if not authorized():
            return jsonify({"ok": False, "message": "Unauthorized"}), 401

        with lock:
            state = public_state(load_state())

        summary = dict(state.get("summary") or {})
        rows = list(state.get("results") or [])
        problem_raw = {
            "CHYBÍ V UNIQA",
            "NEPŘÍTOMNÉ, ALE POJIŠTĚNÉ",
            "PRODANÉ, ALE V UNIQA",
            "NAVÍC V UNIQA",
        }
        resolved = {"VYŘEŠENO", "V POŘÁDKU"}
        problems = []
        for row in rows:
            raw = str(row.get("status_raw") or row.get("status") or "").upper()
            workflow = str(row.get("workflow_status") or "").upper()
            if raw not in problem_raw or workflow in resolved:
                continue
            problems.append({
                "vin": str(row.get("vin") or ""),
                "spz": str(row.get("spz_tir") or row.get("spz_uniqa") or ""),
                "vozidlo": str(row.get("vozidlo") or ""),
                "status": str(row.get("status") or raw),
                "status_raw": raw,
                "workflow_status": str(row.get("workflow_status") or ""),
                "note": str(row.get("note") or ""),
                "detail": str(row.get("detail") or ""),
            })

        return jsonify({
            "ok": True,
            "generated_at": state.get("finished_at") or state.get("synced_at"),
            "running": bool(state.get("running")),
            "error": state.get("error"),
            "summary": {
                "active": int(summary.get("active") or 0),
                "ok_total": int(summary.get("ok_total") or 0),
                "missing": int(summary.get("missing") or 0),
                "absent_insured": int(summary.get("absent_insured") or 0),
                "absent_uninsured": int(summary.get("absent_uninsured") or 0),
                "sold_uniqa": int(summary.get("sold_uniqa") or 0),
                "extra_uniqa": int(summary.get("extra_uniqa") or 0),
                "problems": len(problems),
            },
            "problems": problems,
        })
