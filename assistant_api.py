from __future__ import annotations

import hmac
import os
from typing import Any, Callable

from status_projection import project_status

from flask import jsonify, request


def install_assistant_api(app, load_state: Callable[[], dict[str, Any]], public_state: Callable[[dict[str, Any]], dict[str, Any]], lock, start_check: Callable | None = None) -> None:
    """Install status API and optional separately authorized check trigger."""

    def authorized() -> bool:
        expected = os.getenv("ASSISTANT_API_TOKEN", "").strip()
        supplied = request.headers.get("Authorization", "").strip()
        control = os.getenv("ASSISTANT_CONTROL_TOKEN", "").strip()
        return (bool(expected) and hmac.compare_digest(supplied, f"Bearer {expected}")) or (
            bool(control) and hmac.compare_digest(supplied, f"Bearer {control}")
        )

    @app.post("/api/assistant/run")
    def assistant_run():
        expected = os.getenv("ASSISTANT_CONTROL_TOKEN", "").strip()
        supplied = request.headers.get("Authorization", "").strip()
        if not expected or not hmac.compare_digest(supplied, f"Bearer {expected}"):
            return jsonify({"ok": False, "message": "Unauthorized"}), 401
        if start_check is None:
            return jsonify({"ok": False, "message": "Spuštění kontroly není dostupné."}), 503
        return start_check()

    @app.get("/api/assistant/status")
    def assistant_status():
        if not authorized():
            return jsonify({"ok": False, "message": "Unauthorized"}), 401

        with lock:
            state = public_state(load_state())

        return jsonify({"ok": True, **project_status(state)})


        return jsonify({
            "ok": True,
            "check_id": state.get("check_id"),
            "generated_at": state.get("finished_at") or state.get("synced_at"),
            "running": bool(state.get("running")),
            "started_at": state.get("started_at"),
            "progress": state.get("progress") or {},
            "sources": state.get("sources") or {},
            "result_is_current": not bool(state.get("running")) and bool(state.get("finished_at")) and not bool(state.get("error")),
            "error": state.get("error"),
            "summary": {
                "active": int(summary.get("active") or 0),
                "ok_total": int(summary.get("ok_total") or 0),
                "missing": int(summary.get("missing") or 0),
                "absent_insured": int(summary.get("absent_insured") or 0),
                "absent_uninsured": int(summary.get("absent_uninsured") or 0),
                "sold_uniqa": int(summary.get("sold_uniqa") or 0),
                "extra_uniqa": int(summary.get("extra_uniqa") or 0),
                "spz_mismatch": int(summary.get("spz_mismatch") or 0),
                "unverified": int(summary.get("unverified") or 0),
                "problems": len(problems),
            },
            "problems": problems,
        })
