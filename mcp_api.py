from __future__ import annotations

import hmac
import json
import os
import re
import time
import uuid
from typing import Any, Callable

from flask import Response, jsonify, request


def install_mcp_api(
    app,
    load_state: Callable[[], dict[str, Any]],
    save_state: Callable[[dict[str, Any]], Any],
    public_state: Callable[[dict[str, Any]], dict[str, Any]],
    lock,
    start_check: Callable | None = None,
) -> None:
    def control_authorized(capability: str) -> bool:
        expected = os.getenv("MCP_CONTROL_TOKEN", "").strip()
        return bool(expected) and hmac.compare_digest(capability, expected)

    def authorized(capability: str) -> bool:
        expected = os.getenv("MCP_CAPABILITY_TOKEN", "").strip()
        return (bool(expected) and hmac.compare_digest(capability, expected)) or control_authorized(capability)

    def current_status() -> dict[str, Any]:
        with lock:
            state = public_state(load_state())

        summary = dict(state.get("summary") or {})
        rows = list(state.get("results") or [])
        bad = {
            "CHYBÍ V UNIQA",
            "NEPŘÍTOMNÉ, ALE POJIŠTĚNÉ",
            "PRODANÉ, ALE POJIŠTĚNÉ",
            "DEPOZIT, ALE POJIŠTĚNÉ",
            "NAVÍC V UNIQA",
            "SPZ NESOUHLASÍ",
            "NELZE OVĚŘIT",
        }
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
        }

    @app.post("/mcp/<capability>")
    def mcp(capability: str):
        if not authorized(capability):
            return jsonify({"error": "not_found"}), 404

        body = request.get_json(silent=True)
        if not isinstance(body, dict):
            return jsonify({
                "jsonrpc": "2.0",
                "id": None,
                "error": {"code": -32700, "message": "Parse error"},
            }), 400

        method = str(body.get("method") or "")
        rpc_id = body.get("id")

        if method.startswith("notifications/"):
            return Response(status=202)

        if method == "initialize":
            return jsonify({
                "jsonrpc": "2.0",
                "id": rpc_id,
                "result": {
                    "protocolVersion": "2025-03-26",
                    "capabilities": {"tools": {"listChanged": False}},
                    "serverInfo": {"name": "denni-pov", "version": "1.1.0"},
                    "instructions": (
                        "Aktuální přehled DENNÍ POV. Spuštění kontroly je dostupné pouze "
                        "s řídicím tokenem. Po spuštění načítejte stav; při running=true "
                        "jsou souhrny průběžné nebo z předchozí kontroly."
                    ),
                },
            })

        if method == "ping":
            return jsonify({"jsonrpc": "2.0", "id": rpc_id, "result": {}})

        if method == "tools/list":
            return jsonify({
                "jsonrpc": "2.0",
                "id": rpc_id,
                "result": {
                    "tools": ([{
                        "name": "start_insurance_check",
                        "title": "Spustit kontrolu DENNÍ POV",
                        "description": "Odešle stejný požadavek jako tlačítko Spustit kontrolu. Výsledek sledujte přes get_insurance_status. Při souběhu vrátí busy.",
                        "inputSchema": {"type": "object", "properties": {}, "additionalProperties": False},
                        "annotations": {"readOnlyHint": False, "destructiveHint": False, "idempotentHint": False, "openWorldHint": True},
                    }] if control_authorized(capability) and start_check else []) + [{
                        "name": "get_insurance_status",
                        "title": "Aktuální stav DENNÍ POV",
                        "description": (
                            "Načte aktuální souhrn kontroly pojištění "
                            "a nevyřešená problémová vozidla."
                        ),
                        "inputSchema": {
                            "type": "object",
                            "properties": {},
                            "additionalProperties": False,
                        },
                        "annotations": {
                            "readOnlyHint": True,
                            "destructiveHint": False,
                            "openWorldHint": False,
                        },
                    }, {
                        "name": "lookup_vehicle",
                        "title": "Vyhledat vozidlo v TIRBazar",
                        "description": (
                            "Read-only vyhledání libovolného VIN přímo v interní databázi TIRBazar "
                            "přes kancelářského Windows agenta."
                        ),
                        "inputSchema": {
                            "type": "object",
                            "properties": {
                                "vin": {"type": "string", "description": "VIN vozidla, přesně 17 znaků."}
                            },
                            "required": ["vin"],
                            "additionalProperties": False,
                        },
                        "annotations": {
                            "readOnlyHint": True,
                            "destructiveHint": False,
                            "openWorldHint": False,
                        },
                    }]
                },
            })

        if method == "tools/call":
            params = body.get("params") if isinstance(body.get("params"), dict) else {}
            tool_name = str(params.get("name") or "")
            if tool_name == "start_insurance_check":
                if not control_authorized(capability) or start_check is None:
                    return jsonify({"jsonrpc": "2.0", "id": rpc_id,
                                    "error": {"code": -32602, "message": "Spuštění kontroly není povoleno."}}), 403
                arguments = params.get("arguments", {})
                if not isinstance(arguments, dict) or arguments:
                    return jsonify({"jsonrpc": "2.0", "id": rpc_id,
                                    "error": {"code": -32602, "message": "Nástroj nepřijímá argumenty."}}), 400
                response = app.make_response(start_check())
                result = response.get_json()
                return jsonify({"jsonrpc": "2.0", "id": rpc_id, "result": {
                    "content": [{"type": "text", "text": json.dumps(result, ensure_ascii=False)}],
                    "structuredContent": result, "isError": response.status_code >= 400,
                }})
            if tool_name == "lookup_vehicle":
                arguments = params.get("arguments") if isinstance(params.get("arguments"), dict) else {}
                vin = re.sub(r"\s+", "", str(arguments.get("vin") or "")).upper()
                if not re.fullmatch(r"[A-HJ-NPR-Z0-9]{17}", vin):
                    return jsonify({
                        "jsonrpc": "2.0", "id": rpc_id,
                        "error": {"code": -32602, "message": "VIN musí mít 17 platných znaků."},
                    }), 400
                command_id = uuid.uuid4().hex
                with lock:
                    state = load_state()
                    if state.get("running") or state.get("_command"):
                        return jsonify({"jsonrpc": "2.0", "id": rpc_id, "error": {
                            "code": -32602, "message": "Agent právě zpracovává jiný požadavek."}}), 409
                    state["_vehicle_lookup"] = {
                        "id": command_id, "vin": vin, "status": "pending",
                        "found": False, "vehicle": None, "error": "", "requested_at": time.time(),
                    }
                    state["_command"] = {
                        "id": command_id, "action": "lookup_vehicle", "vin": vin,
                    }
                    save_state(state)
                deadline = time.monotonic() + 110
                result = None
                while time.monotonic() < deadline:
                    time.sleep(2)
                    with lock:
                        state = load_state()
                        lookup = state.get("_vehicle_lookup") if isinstance(state.get("_vehicle_lookup"), dict) else {}
                    if str(lookup.get("id") or "") == command_id and lookup.get("status") in {"done", "error"}:
                        result = dict(lookup)
                        break
                if result is None:
                    result = {
                        "id": command_id, "vin": vin, "status": "pending", "found": False,
                        "vehicle": None, "error": "Kancelářský agent zatím nevrátil výsledek.",
                    }
                return jsonify({
                    "jsonrpc": "2.0", "id": rpc_id,
                    "result": {
                        "content": [{"type": "text", "text": json.dumps(result, ensure_ascii=False)}],
                        "structuredContent": result,
                        "isError": bool(result.get("error")) and result.get("status") == "error",
                    },
                })
            if tool_name != "get_insurance_status":
                return jsonify({
                    "jsonrpc": "2.0",
                    "id": rpc_id,
                    "error": {"code": -32602, "message": "Unknown tool"},
                }), 400

            data = current_status()
            return jsonify({
                "jsonrpc": "2.0",
                "id": rpc_id,
                "result": {
                    "content": [{
                        "type": "text",
                        "text": json.dumps(data, ensure_ascii=False),
                    }],
                    "structuredContent": data,
                    "isError": False,
                },
            })

        return jsonify({
            "jsonrpc": "2.0",
            "id": rpc_id,
            "error": {"code": -32601, "message": "Method not found"},
        }), 404
