"""Single-instance, process-independent XLSX jobs on private ephemeral storage.

Gunicorn requests only enqueue/poll/send_file. A separate Python process writes XLSX.
Files expire after one hour; a deployment discards them, and clients can retry.
"""
from __future__ import annotations
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import threading
import time
import uuid
from contextlib import contextmanager

TTL = 3600
ROOT = Path(os.getenv("POV_EXPORT_DIR", "/tmp/denni_pov_exports"))


def atomic_json(path, data):
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    temporary.replace(path)


def read_status(folder):
    try:
        status = json.loads((folder / "status.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    if time.time() - status["created"] > TTL:
        return {**status, "status": "expired", "error": "Platnost exportu vypršela. Připravte nový soubor."}
    if status["status"] == "running":
        try:
            pid = int((folder / "pid").read_text())
            os.kill(pid, 0)
        except (OSError, ValueError):
            return {**status, "status": "error", "error": "Příprava byla přerušena restartem serveru. Zkuste export znovu."}
    return status


@contextmanager
def admission_lock():
    import fcntl  # Render/Linux; keep cloud_app importable by Windows local clients.
    ROOT.mkdir(mode=0o700, parents=True, exist_ok=True)
    with (ROOT / "admission.lock").open("a") as handle:
        fcntl.flock(handle, fcntl.LOCK_EX)
        yield


def public_status(status):
    return {key: value for key, value in status.items() if key not in {"owner", "created"}}


def install_export_routes(app, load_snapshot, snapshot_lock):
    from flask import jsonify, request, session, render_template, send_file

    @app.post("/api/xlsx-export")
    def start_xlsx_export():
        owner = session.setdefault("xlsx_owner", uuid.uuid4().hex)
        with admission_lock():
            for folder in ROOT.iterdir():
                if not folder.is_dir():
                    continue
                status = read_status(folder)
                if not status or status["status"] == "expired":
                    shutil.rmtree(folder, ignore_errors=True)
                    continue
                if status["status"] == "running":
                    if status["owner"] == owner:
                        return jsonify(public_status(status)), 202
                    return jsonify(ok=False, message="Právě se připravuje jiný Excel. Zkuste to za chvíli."), 409
            with snapshot_lock:
                data = load_snapshot()
            audit_status = data.get("_audit_export") or {}
            audit_snapshot = data.get("_audit_export_snapshot")
            if isinstance(audit_status, dict) and audit_status.get("status") == "pending":
                return jsonify(ok=False, message="Nový audit se dosud připravuje."), 409
            if isinstance(audit_snapshot, dict) and audit_snapshot.get("audit"):
                data = audit_snapshot
            elif isinstance(audit_status, dict) and audit_status.get("status") == "ready":
                return jsonify(ok=False, message="Chybí odpovídající výsledky auditu. Načtěte kompletní audit znovu."), 409
            if not data.get("results") and not (data.get("audit") or {}).get("sql"):
                return jsonify(ok=False, message="Přehled zatím není k dispozici."), 404
            job_id = uuid.uuid4().hex
            folder = ROOT / job_id
            folder.mkdir(mode=0o700)
            status = {"id": job_id, "owner": owner, "created": time.time(),
                      "status": "running", "phase": "starting", "completed": 0, "total": None}
            atomic_json(folder / "status.json", status)
            try:
                atomic_json(folder / "snapshot.json", data)
                process = subprocess.Popen([sys.executable, str(Path(__file__).resolve()), str(folder)],
                                           start_new_session=True, stdin=subprocess.DEVNULL)
                (folder / "pid").write_text(str(process.pid))
                threading.Thread(target=process.wait, daemon=True).start()  # reap child on completion
            except Exception:
                shutil.rmtree(folder, ignore_errors=True)
                app.logger.exception("XLSX process could not start")
                return jsonify(ok=False, message="Přípravu Excelu nelze spustit. Zkuste to znovu."), 503
            return jsonify(public_status(status)), 202

    def owned_job(job_id):
        if not re.fullmatch(r"[a-f0-9]{32}", job_id):
            return None, None
        folder = ROOT / job_id
        status = read_status(folder)
        if not status or status["owner"] != session.get("xlsx_owner"):
            return None, None
        return folder, status

    @app.get("/api/xlsx-export/<job_id>")
    def xlsx_export_status(job_id):
        _, status = owned_job(job_id)
        if not status:
            return jsonify(ok=False, message="Export není dostupný. Po restartu serveru jej připravte znovu."), 404
        return jsonify(public_status(status))

    @app.get("/download/xlsx")
    def download_xlsx():
        job_id = request.args.get("job", "")
        if not job_id:
            # Old bookmarks also use the visible asynchronous flow.
            return render_template("xlsx_export.html")
        folder, status = owned_job(job_id)
        if not status:
            return jsonify(ok=False, message="Export není dostupný."), 404
        if status["status"] != "ready":
            return jsonify(public_status(status)), 409
        path = folder / "audit.xlsx"
        if not path.is_file():
            return jsonify(ok=False, message="Soubor už není dostupný. Připravte nový export."), 410
        # Werkzeug file wrapper streams the finished file, supplies exact Content-Length,
        # and supports Range requests. XLSX generation never runs in this request.
        return send_file(path, as_attachment=True, download_name=status["filename"],
                         mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                         conditional=True, max_age=0)


def run_worker(folder):
    import logging
    from datetime import datetime
    from zoneinfo import ZoneInfo
    from xlsx_report import write_report
    import tempfile
    # Keep intermediate worksheet XML inside the private, expiring job directory.
    original_tempdir = tempfile.tempdir
    tempfile.tempdir = str(folder)
    status = json.loads((folder / "status.json").read_text(encoding="utf-8"))
    last_update = 0.0

    def progress(done, total, phase):
        nonlocal last_update
        now = time.monotonic()
        if now - last_update < 0.25 and phase == status["phase"] and done != total:
            return
        status.update(phase=phase, completed=done, total=total)
        atomic_json(folder / "status.json", status)
        last_update = now

    try:
        data = json.loads((folder / "snapshot.json").read_text(encoding="utf-8"))
        write_report(data, folder / "audit.part", progress)
        (folder / "audit.part").replace(folder / "audit.xlsx")
        status.update(status="ready", phase="ready", size=(folder / "audit.xlsx").stat().st_size,
                      filename="denni_pov_audit_" + datetime.now(ZoneInfo("Europe/Prague")).strftime("%Y-%m-%d_%H-%M") + ".xlsx")
        atomic_json(folder / "status.json", status)
    except Exception:
        logging.exception("XLSX generation failed")
        status.update(status="error", error="Excel se nepodařilo vytvořit. Zkuste přípravu znovu.")
        atomic_json(folder / "status.json", status)
        (folder / "audit.part").unlink(missing_ok=True)
    finally:
        tempfile.tempdir = original_tempdir
        (folder / "snapshot.json").unlink(missing_ok=True)


if __name__ == "__main__":
    run_worker(Path(sys.argv[1]))
