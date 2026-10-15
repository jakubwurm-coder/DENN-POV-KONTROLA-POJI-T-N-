"""Shared insurance status projection for ChatGPT MCP and assistant API.

The cloud application's public_state is the single source of truth for counts.
"""
from typing import Any

ISSUE_STATUSES = frozenset({
    "CHYBÍ V UNIQA", "NEPŘÍTOMNÉ, ALE POJIŠTĚNÉ",
    "PRODANÉ, ALE POJIŠTĚNÉ", "DEPOZIT, ALE POJIŠTĚNÉ",
    "NAVÍC V UNIQA", "NAVÍC V ALLIANZ", "DVOJÍ POJIŠTĚNÍ",
    "SPZ NESOUHLASÍ", "NELZE OVĚŘIT",
})


def project_status(state: dict[str, Any]) -> dict[str, Any]:
    summary = dict(state.get("summary") or {})
    problems = []
    for row in state.get("results") or []:
        raw = str(row.get("status_raw") or row.get("status") or "").upper()
        workflow = str(row.get("workflow_status") or "").upper()
        if raw not in ISSUE_STATUSES or workflow in {"VYŘEŠENO", "V POŘÁDKU"}:
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
    # Do not recompute dashboard figures independently in either API.
    result = {
        "check_id": state.get("check_id"),
        "generated_at": state.get("finished_at") or state.get("synced_at"),
        "running": bool(state.get("running")),
        "started_at": state.get("started_at"),
        "progress": state.get("progress") or {},
        "sources": state.get("sources") or {},
        "result_is_current": not bool(state.get("running")) and bool(state.get("finished_at")) and not bool(state.get("error")),
        "error": state.get("error"),
        "summary": {**summary, "problems": len(problems)},
        "problems": problems,
    }
    return result
