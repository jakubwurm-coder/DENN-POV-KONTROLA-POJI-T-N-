from __future__ import annotations

import csv
import hmac
import io
import json
import os
import threading
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any

from flask import Flask, Response, jsonify, render_template, request

app = Flask(__name__)
app.config["JSON_AS_ASCII"] = False

_lock = threading.Lock()
_STATE_FILE = Path(os.getenv("CLOUD_STATE_FILE", "/tmp/denni_pov_state.json"))
_DATABASE_URL = os.getenv("DATABASE_URL", "").strip()


def _now() -> str:
    return datetime.now().strftime("%d.%m.%Y %H:%M:%S")


def _default_state() -> dict[str, Any]:
    return {
        "running": False,
        "started_at": None,
        "finished_at": None,
        "error": None,
        "sources": {
            "tirbazar": {
                "state": "idle",
                "status": "Čekám na synchronizaci",
                "detail": "Kancelářský agent / TIRBazar SQL",
            },
            "uniqa": {
                "state": "idle",
                "status": "Čekám na synchronizaci",
                "detail": "AIV / Denní POV / Aktivní",
            },
            "allianz": {
                "state": "idle",
                "status": "Čekám na synchronizaci",
                "detail": "Flotilové PDF",
            },
        },
        "summary": {
            "active": 0,
            "ok_total": 0,
            "ok_uniqa": 0,
            "ok_allianz": 0,
            "missing": 0,
            "deposit": 0,
            "sold_uniqa": 0,
            "extra_uniqa": 0,
        },
        "results": [],
        "csv_available": False,
        "synced_at": None,
        "_command": None,
    }


def _db_load() -> dict[str, Any] | None:
    if not _DATABASE_URL:
        return None
    try:
        import psycopg

        with psycopg.connect(_DATABASE_URL, connect_timeout=8) as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    CREATE TABLE IF NOT EXISTS denni_pov_state (
                        id INTEGER PRIMARY KEY,
                        payload JSONB NOT NULL,
                        updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
                    )
                    """
                )
                cur.execute("SELECT payload FROM denni_pov_state WHERE id = 1")
                row = cur.fetchone()
                conn.commit()
                if row:
                    payload = row[0]
                    if isinstance(payload, str):
                        payload = json.loads(payload)
                    if isinstance(payload, dict):
                        return payload
    except Exception as exc:
        print(f"Render Postgres load fallback: {exc}")
    return None


def _db_save(data: dict[str, Any]) -> bool:
    if not _DATABASE_URL:
        return False
    try:
        import psycopg

        with psycopg.connect(_DATABASE_URL, connect_timeout=8) as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    CREATE TABLE IF NOT EXISTS denni_pov_state (
                        id INTEGER PRIMARY KEY,
                        payload JSONB NOT NULL,
                        updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
                    )
                    """
                )
                cur.execute(
                    """
                    INSERT INTO denni_pov_state (id, payload, updated_at)
                    VALUES (1, %s::jsonb, NOW())
                    ON CONFLICT (id)
                    DO UPDATE SET payload = EXCLUDED.payload, updated_at = NOW()
                    """,
                    (json.dumps(data, ensure_ascii=False),),
                )
                conn.commit()
        return True
    except Exception as exc:
        print(f"Render Postgres save fallback: {exc}")
        return False


def _file_load() -> dict[str, Any] | None:
    try:
        if _STATE_FILE.exists():
            data = json.loads(_STATE_FILE.read_text(encoding="utf-8"))
            if isinstance(data, dict):
                return data
    except Exception as exc:
        print(f"Cloud state file load failed: {exc}")
    return None


def _file_save(data: dict[str, Any]) -> None:
    try:
        _STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
        tmp = _STATE_FILE.with_suffix(".tmp")
        tmp.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
        tmp.replace(_STATE_FILE)
    except Exception as exc:
        print(f"Cloud state file save failed: {exc}")


def _load_state() -> dict[str, Any]:
    data = _db_load() or _file_load() or _default_state()
    base = _default_state()
    base.update(data)
    if not isinstance(base.get("sources"), dict):
        base["sources"] = _default_state()["sources"]
    if not isinstance(base.get("summary"), dict):
        base["summary"] = _default_state()["summary"]
    if not isinstance(base.get("results"), list):
        base["results"] = []
    return base


def _save_state(data: dict[str, Any]) -> None:
    if not _db_save(data):
        _file_save(data)


def _public_state(data: dict[str, Any]) -> dict[str, Any]:
    public = dict(data)
    public.pop("_command", None)
    public["csv_available"] = bool(public.get("results"))
    return public


def _authorized() -> bool:
    expected = os.getenv("SYNC_TOKEN", "")
    if not expected:
        return False
    supplied = request.headers.get("Authorization", "")
    return hmac.compare_digest(supplied, f"Bearer {expected}")


@app.get("/")
def index():
    return render_template("index.html")


@app.get("/api/state")
def api_state():
    with _lock:
        data = _load_state()
    return jsonify(_public_state(data))


@app.post("/api/run")
def api_run():
    with _lock:
        data = _load_state()
        if data.get("running") and data.get("_command"):
            return jsonify({"ok": False, "message": "Kontrola už čeká na kancelářský agent."}), 409

        command_id = uuid.uuid4().hex
        data["running"] = True
        data["started_at"] = _now()
        data["finished_at"] = None
        data["error"] = None
        data["_command"] = {
            "id": command_id,
            "action": "run_check",
            "requested_at": _now(),
        }
        data["sources"] = {
            "tirbazar": {
                "state": "loading",
                "status": "Čekám na kancelářský agent…",
                "detail": "TIRBazar SQL je dostupný pouze z interní sítě",
            },
            "uniqa": {
                "state": "idle",
                "status": "Čekám…",
                "detail": "AIV / Denní POV / Aktivní",
            },
            "allianz": {
                "state": "idle",
                "status": "Čekám…",
                "detail": "Flotilové PDF",
            },
        }
        _save_state(data)

    return jsonify({"ok": True, "message": "Požadavek na kontrolu odeslán kancelářskému agentovi."})


@app.get("/api/agent/command")
def agent_command():
    if not _authorized():
        return jsonify({"ok": False, "message": "Unauthorized"}), 401
    with _lock:
        data = _load_state()
        command = data.get("_command")
    return jsonify({"ok": True, "command": command})


@app.post("/api/sync")
def api_sync():
    if not _authorized():
        return jsonify({"ok": False, "message": "Unauthorized"}), 401

    payload = request.get_json(silent=True)
    if not isinstance(payload, dict):
        return jsonify({"ok": False, "message": "Neplatná data synchronizace."}), 400

    required = ("sources", "summary", "results")
    if any(key not in payload for key in required):
        return jsonify({"ok": False, "message": "Synchronizace nemá všechny povinné části."}), 400

    if not isinstance(payload.get("sources"), dict) or not isinstance(payload.get("summary"), dict) or not isinstance(payload.get("results"), list):
        return jsonify({"ok": False, "message": "Neplatný formát synchronizace."}), 400

    with _lock:
        data = _default_state()
        for key in (
            "running",
            "started_at",
            "finished_at",
            "error",
            "sources",
            "summary",
            "results",
        ):
            if key in payload:
                data[key] = payload[key]
        data["running"] = False
        data["finished_at"] = payload.get("finished_at") or _now()
        data["synced_at"] = _now()
        data["csv_available"] = bool(data.get("results"))
        data["_command"] = None
        _save_state(data)

    return jsonify({"ok": True, "message": "Data byla synchronizována na Render."})


@app.get("/download/csv")
def download_csv():
    with _lock:
        data = _load_state()
        rows = list(data.get("results") or [])

    if not rows:
        return jsonify({"ok": False, "message": "CSV zatím není k dispozici."}), 404

    stream = io.StringIO()
    writer = csv.writer(stream, delimiter=";")
    writer.writerow([
        "Stav",
        "Pojišťovna",
        "VIN",
        "SPZ TIRBazar",
        "SPZ UNIQA",
        "Datum výkupu",
        "Datum prodeje",
        "Výsledek",
    ])
    for row in rows:
        writer.writerow([
            row.get("status", ""),
            row.get("pojistovna", ""),
            row.get("vin", ""),
            row.get("spz_tir", ""),
            row.get("spz_uniqa", ""),
            row.get("vykup", ""),
            row.get("prodej", ""),
            row.get("detail", ""),
        ])

    body = "\ufeff" + stream.getvalue()
    return Response(
        body,
        mimetype="text/csv; charset=utf-8",
        headers={"Content-Disposition": "attachment; filename=denni_pov_online.csv"},
    )


@app.get("/health")
def health():
    with _lock:
        data = _load_state()
    return jsonify({
        "ok": True,
        "service": "DENNI POV - KONTROLA",
        "mode": "online",
        "storage": "postgres" if _DATABASE_URL else "file",
        "synced_at": data.get("synced_at"),
        "waiting_for_agent": bool(data.get("_command")),
    })
