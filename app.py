from __future__ import annotations

import os

from flask import jsonify

from shared_notes import install_cloud_annotations, install_local_annotations
from vehicle_card import install_vehicle_card

ONLINE_MODE = os.getenv("ONLINE_MODE", "").strip().lower() in {"1", "true", "yes", "on"}

if ONLINE_MODE:
    import cloud_app as _cloud
    from assistant_api import install_assistant_api
    from mcp_api import install_mcp_api

    app = _cloud.app
    install_cloud_annotations(app, _cloud)
    install_assistant_api(app, _cloud._load_state, _cloud._public_state, _cloud._lock, start_check=_cloud.api_run)
    install_mcp_api(app, _cloud._load_state, _cloud._save_state, _cloud._public_state, _cloud._lock, start_check=_cloud.api_run)
else:
    import local_app as _local

    app = _local.app
    install_local_annotations(app)
    _run_check_worker = _local._run_check_worker
    _snapshot = _local._snapshot
    _lock = _local._lock
    _state = _local._state
    _now = _local._now

install_vehicle_card(app)


@app.get("/api/windows-status")
def windows_status():
    """Lehký stavový endpoint pro Windows tray klienta DENNÍ POV."""
    if ONLINE_MODE:
        with _cloud._lock:
            state = _cloud._public_state(_cloud._load_state())
    else:
        with _local._lock:
            state = _local._snapshot()

    summary = dict(state.get("summary") or {})
    rows = list(state.get("results") or [])

    issue_raw_statuses = {
        "CHYBÍ V UNIQA",
        "NEPŘÍTOMNÉ, ALE POJIŠTĚNÉ",
        "DEPOZIT, ALE POJIŠTĚNÉ",
        "PRODANÉ, ALE POJIŠTĚNÉ",
        "NAVÍC V UNIQA",
        "SPZ NESOUHLASÍ",
        "NELZE OVĚŘIT",
    }
    resolved_statuses = {"VYŘEŠENO"}

    issues = []
    for row in rows:
        raw = str(row.get("status_raw") or "").strip().upper()
        workflow = str(row.get("workflow_status") or "").strip().upper()
        if raw not in issue_raw_statuses:
            continue
        resolved = workflow == "VYŘEŠENO"
        if resolved:
            continue

        issues.append({
            "spz": str(row.get("spz_tir") or row.get("spz_uniqa") or "").strip(),
            "vin": str(row.get("vin") or "").strip(),
            "vehicle": str(row.get("vozidlo") or "").strip(),
            "status": str(row.get("status") or row.get("status_raw") or "").strip(),
            "detail": str(row.get("detail") or "").strip(),
        })

    running = bool(state.get("running"))
    error = str(state.get("error") or "").strip()
    if error:
        status = "error"
    elif running:
        status = "running"
    elif issues:
        status = "requires_check"
    else:
        status = "ok"

    return jsonify({
        "app": "DENNÍ POV",
        "status": status,
        "running": running,
        "error": error or None,
        "requires_check": len(issues),
        "active": int(summary.get("active") or 0),
        "ok": int(summary.get("ok_total") or 0),
        "last_check": state.get("finished_at") or state.get("synced_at"),
        "issues": issues,
        "web_url": "https://denni-pov-kontrola.onrender.com",
    })


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "5000"))
    app.run(
        host="0.0.0.0",
        port=port,
        debug=os.environ.get("FLASK_DEBUG") == "1",
    )
