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
                            "Spustí NOVOU kontrolu DENNÍ POV, čeká na dokončení a vrátí "
                            "výhradně výsledek stejného request_id/check_id. "
                            "Nikdy nevrací starou kontrolu jako aktuální."
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
            if tool_name != "get_insurance_status":
                return jsonify({
                    "jsonrpc": "2.0",
                    "id": rpc_id,
                    "error": {"code": -32602, "message": "Unknown tool"},
                }), 400

            # Each voice request must launch its own fresh check. If the agent
            # is occupied, wait for the previous operation to finish first.
            if start_check is None:
                data = {"ok": False, "error": "Spuštění kontroly není dostupné.",
                        "fresh_check_completed": False}
            else:
                data = {"ok": False, "fresh_check_completed": False,
                        "error": "Nová kontrola nebyla dokončena."}
                deadline = time.monotonic() + 105
                request_id = None
                while time.monotonic() < deadline:
                    response = app.make_response(start_check())
                    started = response.get_json(silent=True) or {}
                    if response.status_code == 202 and started.get("request_id"):
                        request_id = str(started["request_id"])
                        break
                    if response.status_code != 409:
                        data["error"] = started.get("message") or "Kontrolu nelze spustit."
                        break
                    # A running check or pending agent command is not our own
                    # result. Wait until it releases the slot, then retry.
                    time.sleep(2)
                if request_id:
                    data = {"ok": False, "request_id": request_id,
                            "fresh_check_completed": False, "running": True,
                            "error": "Nová kontrola dosud nebyla dokončena."}
                    while time.monotonic() < deadline:
                        time.sleep(2)
                        with lock:
                            snapshot = public_state(load_state())
                        if str(snapshot.get("check_id") or "") != request_id:
                            continue
                        if snapshot.get("running"):
                            continue
                        if snapshot.get("error"):
                            data = {"ok": False, "request_id": request_id,
                                    "check_id": request_id, "fresh_check_completed": False,
                                    "error": str(snapshot.get("error"))}
                            break
                        if not snapshot.get("finished_at"):
                            continue
                        status = current_status()
                        if str(status.get("check_id") or "") != request_id or status.get("running"):
                            continue
                        source_states = status.get("sources") or {}
                        source_ok = all(
                            str((source_states.get(name) or {}).get("state") or "").lower()
                            in {"ok", "success", "done", "ready", "completed"}
                            for name in ("tirbazar", "uniqa", "allianz")
                        )
                        if not source_ok:
                            data = {"ok": False, "request_id": request_id,
                                    "check_id": request_id, "fresh_check_completed": False,
                                    "error": "Nebylo potvrzeno úspěšné načtení všech tří zdrojů."}
                        else:
                            data = {**status, "ok": True, "request_id": request_id,
                                    "fresh_check_completed": True, "result_is_current": True}
                        break
                elif time.monotonic() >= deadline:
                    data["error"] = "Vypršel čas čekání na uvolnění kontroly."
            return jsonify({
                "jsonrpc": "2.0", "id": rpc_id,
                "result": {
                    "content": [{"type": "text", "text": json.dumps(data, ensure_ascii=False)}],
                    "structuredContent": data,
                    "isError": not bool(data.get("fresh_check_completed")),
                },
            })

        return jsonify({
            "jsonrpc": "2.0",
            "id": rpc_id,
            "error": {"code": -32601, "message": "Method not found"},
        }), 404
