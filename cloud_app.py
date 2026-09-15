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
        "progress": {"percent": 0, "phase": "Připraveno", "eta_seconds": 0},
        "sources": {
            "tirbazar": {"state": "idle", "status": "Čekám na synchronizaci", "detail": "Kancelářský agent / TIRBazar SQL"},
            "uniqa": {"state": "idle", "status": "Čekám na synchronizaci", "detail": "AIV / Denní POV / Aktivní"},
            "allianz": {"state": "idle", "status": "Čekám na synchronizaci", "detail": "Flotilové PDF"},
        },
        "summary": {"active": 0, "ok_total": 0, "ok_uniqa": 0, "ok_allianz": 0, "missing": 0, "deposit": 0, "sold_uniqa": 0, "extra_uniqa": 0},
        "results": [],
        "annotations": {},
        "csv_available": False,
        "synced_at": None,
        "_command": None,
    }


def _db_init(cur) -> None:
    cur.execute("""
        CREATE TABLE IF NOT EXISTS denni_pov_state (
            id INTEGER PRIMARY KEY,
            payload JSONB NOT NULL,
            updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
        )
    """)
    cur.execute("""
        CREATE TABLE IF NOT EXISTS denni_pov_history (
            id BIGSERIAL PRIMARY KEY,
            checked_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            started_at TEXT,
            finished_at TEXT,
            summary JSONB NOT NULL,
            results JSONB NOT NULL,
            error TEXT,
            alert_sent BOOLEAN NOT NULL DEFAULT FALSE
        )
    """)
    cur.execute("""
        CREATE TABLE IF NOT EXISTS denni_pov_annotations (
            vehicle_key TEXT PRIMARY KEY,
            note TEXT NOT NULL DEFAULT '',
            workflow_status TEXT NOT NULL DEFAULT '',
            updated_at TEXT NOT NULL
        )
    """)


def _db_load() -> dict[str, Any] | None:
    if not _DATABASE_URL:
        return None
    try:
        import psycopg
        with psycopg.connect(_DATABASE_URL, connect_timeout=8) as conn:
            with conn.cursor() as cur:
                _db_init(cur)
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
                _db_init(cur)
                cur.execute("""
                    INSERT INTO denni_pov_state (id, payload, updated_at)
                    VALUES (1, %s::jsonb, NOW())
                    ON CONFLICT (id)
                    DO UPDATE SET payload = EXCLUDED.payload, updated_at = NOW()
                """, (json.dumps(data, ensure_ascii=False),))
                conn.commit()
        return True
    except Exception as exc:
        print(f"Render Postgres save fallback: {exc}")
        return False


def _history_save(data: dict[str, Any], alert_sent: bool) -> None:
    if not _DATABASE_URL:
        return
    try:
        import psycopg
        with psycopg.connect(_DATABASE_URL, connect_timeout=8) as conn:
            with conn.cursor() as cur:
                _db_init(cur)
                cur.execute("""
                    INSERT INTO denni_pov_history
                        (started_at, finished_at, summary, results, error, alert_sent)
                    VALUES (%s, %s, %s::jsonb, %s::jsonb, %s, %s)
                """, (
                    data.get("started_at"),
                    data.get("finished_at"),
                    json.dumps(data.get("summary") or {}, ensure_ascii=False),
                    json.dumps(data.get("results") or [], ensure_ascii=False),
                    data.get("error"),
                    alert_sent,
                ))
                conn.commit()
    except Exception as exc:
        print(f"History save failed: {exc}")


def _history_load(limit: int = 100) -> list[dict[str, Any]]:
    if not _DATABASE_URL:
        return []
    try:
        import psycopg
        with psycopg.connect(_DATABASE_URL, connect_timeout=8) as conn:
            with conn.cursor() as cur:
                _db_init(cur)
                cur.execute("""
                    SELECT id, checked_at, started_at, finished_at, summary, error, alert_sent
                    FROM denni_pov_history
                    ORDER BY id DESC
                    LIMIT %s
                """, (max(1, min(limit, 500)),))
                rows = cur.fetchall()
                conn.commit()
        return [
            {
                "id": row[0],
                "checked_at": row[1].astimezone().strftime("%d.%m.%Y %H:%M:%S") if row[1] else "",
                "started_at": row[2] or "",
                "finished_at": row[3] or "",
                "summary": row[4] if isinstance(row[4], dict) else {},
                "error": row[5] or "",
                "alert_sent": bool(row[6]),
            }
            for row in rows
        ]
    except Exception as exc:
        print(f"History load failed: {exc}")
        return []


def _annotations_load(legacy: dict[str, Any] | None = None) -> dict[str, dict[str, str]]:
    legacy = legacy if isinstance(legacy, dict) else {}
    if not _DATABASE_URL:
        return {
            str(key).strip().upper(): {
                "note": str((value or {}).get("note") or ""),
                "workflow_status": str((value or {}).get("workflow_status") or ""),
                "updated_at": str((value or {}).get("updated_at") or ""),
            }
            for key, value in legacy.items()
            if isinstance(value, dict)
        }
    try:
        import psycopg
        with psycopg.connect(_DATABASE_URL, connect_timeout=8) as conn:
            with conn.cursor() as cur:
                _db_init(cur)
                for key, value in legacy.items():
                    if not isinstance(value, dict):
                        continue
                    vehicle_key = str(key or "").strip().upper()
                    if not vehicle_key:
                        continue
                    cur.execute("""
                        INSERT INTO denni_pov_annotations (vehicle_key, note, workflow_status, updated_at)
                        VALUES (%s, %s, %s, %s)
                        ON CONFLICT (vehicle_key) DO NOTHING
                    """, (
                        vehicle_key,
                        str(value.get("note") or "")[:2000],
                        str(value.get("workflow_status") or "")[:50],
                        str(value.get("updated_at") or _now()),
                    ))
                cur.execute("SELECT vehicle_key, note, workflow_status, updated_at FROM denni_pov_annotations")
                rows = cur.fetchall()
                conn.commit()
        return {
            str(row[0]).strip().upper(): {
                "note": row[1] or "",
                "workflow_status": row[2] or "",
                "updated_at": row[3] or "",
            }
            for row in rows
        }
    except Exception as exc:
        print(f"Annotations load fallback: {exc}")
        return {
            str(key).strip().upper(): {
                "note": str((value or {}).get("note") or ""),
                "workflow_status": str((value or {}).get("workflow_status") or ""),
                "updated_at": str((value or {}).get("updated_at") or ""),
            }
            for key, value in legacy.items()
            if isinstance(value, dict)
        }


def _annotation_save(vehicle_key: str, note: str, workflow_status: str) -> bool:
    if not _DATABASE_URL:
        return False
    try:
        import psycopg
        with psycopg.connect(_DATABASE_URL, connect_timeout=8) as conn:
            with conn.cursor() as cur:
                _db_init(cur)
                cur.execute("""
                    INSERT INTO denni_pov_annotations (vehicle_key, note, workflow_status, updated_at)
                    VALUES (%s, %s, %s, %s)
                    ON CONFLICT (vehicle_key)
                    DO UPDATE SET
                        note = EXCLUDED.note,
                        workflow_status = EXCLUDED.workflow_status,
                        updated_at = EXCLUDED.updated_at
                """, (vehicle_key, note, workflow_status, _now()))
                conn.commit()
        return True
    except Exception as exc:
        print(f"Annotation save fallback: {exc}")
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
    if not isinstance(base.get("sources"), dict): base["sources"] = _default_state()["sources"]
    if not isinstance(base.get("summary"), dict): base["summary"] = _default_state()["summary"]
    if not isinstance(base.get("results"), list): base["results"] = []
    if not isinstance(base.get("annotations"), dict): base["annotations"] = {}
    if not isinstance(base.get("progress"), dict): base["progress"] = _default_state()["progress"]
    return base


def _save_state(data: dict[str, Any]) -> None:
    if not _db_save(data):
        _file_save(data)


def _result_key(row: dict[str, Any]) -> str:
    vin = str(row.get("vin") or "").strip().upper()
    spz = str(row.get("spz_tir") or row.get("spz_uniqa") or "").strip().upper()
    return vin or f"SPZ:{spz}"


def _public_state(data: dict[str, Any]) -> dict[str, Any]:
    public = dict(data)
    public.pop("_command", None)
    public.pop("annotations", None)
    annotations = _annotations_load(data.get("annotations"))
    rows = []
    for original in data.get("results") or []:
        row = dict(original)
        meta = annotations.get(_result_key(row), {})
        row["note"] = str(meta.get("note") or "")
        row["workflow_status"] = str(meta.get("workflow_status") or "")
        row["workflow_updated_at"] = str(meta.get("updated_at") or "")
        if row["workflow_status"]:
            row["original_status"] = row.get("status", "")
            row["status"] = row["workflow_status"]
        rows.append(row)
    public["results"] = rows
    summary = dict(data.get("summary") or {})
    deposit = int(summary.get("deposit") or 0)
    summary["active"] = max(0, int(summary.get("active") or 0) - deposit)
    summary["ok_total"] = max(0, int(summary.get("ok_total") or 0) - deposit)
    public["summary"] = summary
    public["csv_available"] = bool(rows)
    return public


def _authorized() -> bool:
    expected = os.getenv("SYNC_TOKEN", "")
    if not expected: return False
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


@app.get("/api/history")
def api_history():
    limit = request.args.get("limit", "100")
    try:
        limit_i = int(limit)
    except ValueError:
        limit_i = 100
    return jsonify({"ok": True, "history": _history_load(limit_i)})


@app.post("/api/result-meta")
def api_result_meta():
    payload = request.get_json(silent=True)
    if not isinstance(payload, dict): return jsonify({"ok": False, "message": "Neplatná data."}), 400
    key = str(payload.get("key") or "").strip().upper()
    if not key: return jsonify({"ok": False, "message": "Chybí identifikace vozidla."}), 400
    note = str(payload.get("note") or "").strip()[:2000]
    workflow_status = str(payload.get("workflow_status") or "").strip().upper()
    if workflow_status not in {"", "VYŘEŠENO", "ŘEŠÍ SE", "KONTROLA"}:
        return jsonify({"ok": False, "message": "Nepovolený status."}), 400

    _annotation_save(key, note, workflow_status)
    with _lock:
        data = _load_state()
        data.setdefault("annotations", {})[key] = {
            "note": note,
            "workflow_status": workflow_status,
            "updated_at": _now(),
        }
        _save_state(data)

    return jsonify({"ok": True, "message": "Poznámka a status byly uloženy."})


@app.post("/api/run")
def api_run():
    with _lock:
        data = _load_state()
        if data.get("running"):
            return jsonify({"ok": False, "message": "Kontrola už probíhá."}), 409
        command_id = uuid.uuid4().hex
        data["running"] = True
        data["started_at"] = _now()
        data["finished_at"] = None
        data["error"] = None
        data["progress"] = {"percent": 3, "phase": "Čekám na kancelářský agent", "eta_seconds": 90}
        data["_command"] = {"id": command_id, "action": "run_check", "requested_at": _now()}
        data["sources"] = {
            "tirbazar": {"state": "loading", "status": "Čekám na kancelářský agent…", "detail": "TIRBazar SQL je dostupný pouze z interní sítě"},
            "uniqa": {"state": "idle", "status": "Čekám…", "detail": "AIV / Denní POV / Aktivní"},
            "allianz": {"state": "idle", "status": "Čekám…", "detail": "Flotilové PDF"},
        }
        _save_state(data)
    return jsonify({"ok": True, "message": "Požadavek na kontrolu odeslán kancelářskému agentovi."})


@app.get("/api/agent/command")
def agent_command():
    if not _authorized(): return jsonify({"ok": False, "message": "Unauthorized"}), 401
    with _lock:
        data = _load_state()
        command = data.get("_command")
    return jsonify({"ok": True, "command": command})


@app.post("/api/sync")
def api_sync():
    if not _authorized(): return jsonify({"ok": False, "message": "Unauthorized"}), 401
    payload = request.get_json(silent=True)
    if not isinstance(payload, dict): return jsonify({"ok": False, "message": "Neplatná data synchronizace."}), 400
    required = ("sources", "summary", "results")
    if any(key not in payload for key in required): return jsonify({"ok": False, "message": "Synchronizace nemá všechny povinné části."}), 400
    if not isinstance(payload.get("sources"), dict) or not isinstance(payload.get("summary"), dict) or not isinstance(payload.get("results"), list):
        return jsonify({"ok": False, "message": "Neplatný formát synchronizace."}), 400

    final_run = not bool(payload.get("running"))
    alert_sent = False

    with _lock:
        previous = _load_state()
        annotations = _annotations_load(previous.get("annotations"))
        data = _default_state()
        data["annotations"] = annotations
        for key in ("running", "started_at", "finished_at", "error", "sources", "summary", "results", "progress"):
            if key in payload: data[key] = payload[key]
        data["running"] = bool(payload.get("running"))
        if data["running"]:
            data["finished_at"] = None
        else:
            data["finished_at"] = payload.get("finished_at") or _now()
            if not data.get("error"):
                data["progress"] = {"percent": 100, "phase": "Hotovo", "eta_seconds": 0}
        data["synced_at"] = _now()
        data["csv_available"] = bool(data.get("results"))
        data["_command"] = None
        _save_state(data)

    if final_run:
        _history_save(data, alert_sent)

    return jsonify({"ok": True, "message": "Data byla synchronizována na Render.", "alert_sent": alert_sent})


@app.get("/download/csv")
def download_csv():
    with _lock:
        data = _public_state(_load_state())
        rows = list(data.get("results") or [])
    if not rows: return jsonify({"ok": False, "message": "CSV zatím není k dispozici."}), 404
    stream = io.StringIO()
    writer = csv.writer(stream, delimiter=";")
    writer.writerow(["Stav", "Pojišťovna", "VIN", "SPZ TIRBazar", "SPZ UNIQA", "Datum výkupu", "Datum prodeje", "Výsledek", "Poznámka"])
    for row in rows:
        writer.writerow([row.get("status", ""), row.get("pojistovna", ""), row.get("vin", ""), row.get("spz_tir", ""), row.get("spz_uniqa", ""), row.get("vykup", ""), row.get("prodej", ""), row.get("detail", ""), row.get("note", "")])
    body = "\ufeff" + stream.getvalue()
    return Response(body, mimetype="text/csv; charset=utf-8", headers={"Content-Disposition": "attachment; filename=denni_pov_online.csv"})


@app.get("/health")
def health():
    with _lock: data = _load_state()
    return jsonify({"ok": True, "service": "DENNI POV - KONTROLA", "mode": "online", "storage": "postgres" if _DATABASE_URL else "file", "synced_at": data.get("synced_at"), "waiting_for_agent": bool(data.get("_command"))})