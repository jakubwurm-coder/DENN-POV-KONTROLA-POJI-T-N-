from __future__ import annotations
import json
from typing import Any, Callable
from flask import Response, jsonify, request

def install_mcp_api(app, load_state: Callable[[], dict[str, Any]], public_state: Callable[[dict[str, Any]], dict[str, Any]], lock) -> None:
    def current_status() -> dict[str, Any]:
        with lock:
            state = public_state(load_state())
        summary = dict(state.get("summary") or {})
        rows = list(state.get("results") or [])
        bad = {"CHYBÍ V UNIQA", "NEPŘÍTOMNÉ, ALE POJIŠTĚNÉ", "PRODANÉ, ALE V UNIQA", "NAVÍC V UNIQA"}
        resolved = {"VYŘEŠENO", "V POŘÁDKU"}
        problems = []
        for row in rows:
            raw = str(row.get("status_raw") or row.get("status") or "").upper()
            workflow = str(row.get("workflow_status") or "").upper()
            if raw in bad and workflow not in resolved:
                problems.append({
                    "vin": str(row.get("vin") or ""),
                    "spz": str(row.get("spz_tir") or row.get("spz_uniqa") or ""),
                    "vozidlo": str(row.get("vozidlo") or ""),
                    "status": str(row.get("status") or raw),
                    "workflow_status": str(row.get("workflow_status") or ""),
                    "note": str(row.get("note") or ""),
                    "detail": str(row.get("detail") or ""),
                })
        return {
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
        }

    @app.post("/mcp")
    def mcp():
        body = request.get_json(silent=True)
        if not isinstance(body, dict):
            return jsonify({"jsonrpc":"2.0","id":None,"error":{"code":-32700,"message":"Parse error"}}), 400
        method = str(body.get("method") or "")
        rpc_id = body.get("id")
        if method.startswith("notifications/"):
            return Response(status=202)
        if method == "initialize":
            return jsonify({"jsonrpc":"2.0","id":rpc_id,"result":{
                "protocolVersion":"2025-03-26",
                "capabilities":{"tools":{"listChanged":False}},
                "serverInfo":{"name":"denni-pov","version":"1.0.0"},
                "instructions":"Read-only aktuální přehled kontroly pojištění vozidel DENNÍ POV / Vans Centre."
            }})
        if method == "ping":
            return jsonify({"jsonrpc":"2.0","id":rpc_id,"result":{}})
        if method == "tools/list":
            return jsonify({"jsonrpc":"2.0","id":rpc_id,"result":{"tools":[{
                "name":"get_insurance_status",
                "title":"Aktuální stav DENNÍ POV",
                "description":"Načte aktuální souhrn kontroly pojištění a nevyřešená problémová vozidla.",
                "inputSchema":{"type":"object","properties":{},"additionalProperties":False},
                "annotations":{"readOnlyHint":True,"destructiveHint":False,"openWorldHint":False}
            }]}})
        if method == "tools/call":
            params = body.get("params") if isinstance(body.get("params"), dict) else {}
            if params.get("name") != "get_insurance_status":
                return jsonify({"jsonrpc":"2.0","id":rpc_id,"error":{"code":-32602,"message":"Unknown tool"}}), 400
            data = current_status()
            return jsonify({"jsonrpc":"2.0","id":rpc_id,"result":{
                "content":[{"type":"text","text":json.dumps(data, ensure_ascii=False)}],
                "structuredContent":data,
                "isError":False
            }})
        return jsonify({"jsonrpc":"2.0","id":rpc_id,"error":{"code":-32601,"message":"Method not found"}}), 404
