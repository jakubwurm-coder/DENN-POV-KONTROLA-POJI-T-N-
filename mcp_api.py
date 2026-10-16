from __future__ import annotations

import hmac
import json
import os
import re
import time
import uuid
from typing import Any, Callable

from status_projection import project_status

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

        return project_status(state)

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
                        "Aktuální přehled DENNÍ POV. Spuštění bezpečné read-only kontroly je dostupné "
                        "pro autorizované připojení. Po spuštění načítejte stav; při running=true "
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
                    }] if authorized(capability) and start_check else []) + [{
                        "name": "get_insurance_status",
                        "title": "Aktuální stav DENNÍ POV",
                        "description": (
                            "Spustí NOVOU kontrolu a ihned vrátí request_id. "
                            "Pro dokončení volejte get_check_result; starý výsledek není vydáván za nový."
                        ),
                        "inputSchema": {
                            "type": "object",
                            "properties": {},
                            "additionalProperties": False,
                        },
                        "annotations": {
                            "readOnlyHint": False,
                            "destructiveHint": False,
                            "openWorldHint": True,
                        },
                    }, {
                        "name": "get_check_result",
                        "title": "Průběh a výsledek kontroly",
                        "description": "Načte stav přesně určeného request_id bez spuštění další kontroly. Opakujte až do fresh_check_completed=true.",
                        "inputSchema": {"type": "object", "properties": {"request_id": {"type": "string"}}, "required": ["request_id"], "additionalProperties": False},
                        "annotations": {"readOnlyHint": True, "destructiveHint": False, "openWorldHint": False},
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
                if not authorized(capability) or start_check is None:
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
            if tool_name == "get_check_result":
                arguments = params.get("arguments") if isinstance(params.get("arguments"), dict) else {}
                request_id = str(arguments.get("request_id") or "").strip()
                if not re.fullmatch(r"[a-f0-9]{32}", request_id):
                    return jsonify({"jsonrpc": "2.0", "id": rpc_id,
                                    "error": {"code": -32602, "message": "Neplatné request_id."}}), 400
                status = current_status()
                same_run = str(status.get("check_id") or "") == request_id
                completed = same_run and not status.get("running") and bool(status.get("generated_at")) and not status.get("error")
                data = {**status, "ok": bool(completed), "request_id": request_id,
                        "fresh_check_completed": bool(completed)} if same_run else {
                    "ok": False, "request_id": request_id, "fresh_check_completed": False,
                    "running": True, "message": "Výsledek požadované kontroly dosud není dostupný."}
                return jsonify({"jsonrpc": "2.0", "id": rpc_id, "result": {
                    "content": [{"type": "text", "text": json.dumps(data, ensure_ascii=False)}],
                    "structuredContent": data, "isError": bool(same_run and status.get("error")),
                }})
            if tool_name != "get_insurance_status":
                return jsonify({
                    "jsonrpc": "2.0",
                    "id": rpc_id,
                    "error": {"code": -32602, "message": "Unknown tool"},
                }), 400

            # Never block the web worker while the Windows agent performs a check.
            response = app.make_response(start_check()) if start_check else None
            started = response.get_json(silent=True) if response else {}
            started = started or {}
            if response and response.status_code == 202 and started.get("request_id"):
                data = {"ok": True, "running": True, "request_id": str(started["request_id"]),
                        "fresh_check_completed": False,
                        "message": "Kontrola spuštěna. Výsledek načítejte nástrojem get_check_result."}
            else:
                data = {"ok": False, "fresh_check_completed": False,
                        "busy": bool(response and response.status_code == 409),
                        "error": started.get("message") or "Kontrolu nelze spustit."}
            return jsonify({"jsonrpc": "2.0", "id": rpc_id, "result": {
                "content": [{"type": "text", "text": json.dumps(data, ensure_ascii=False)}],
                "structuredContent": data, "isError": not data["ok"],
            }})

        return jsonify({
            "jsonrpc": "2.0",
            "id": rpc_id,
            "error": {"code": -32601, "message": "Method not found"},
        }), 404
