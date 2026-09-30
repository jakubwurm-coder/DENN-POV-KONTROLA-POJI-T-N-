from __future__ import annotations

import argparse
import os
import platform
import smtplib
import subprocess
import sys
import threading
import time
from datetime import datetime
from email.message import EmailMessage
from pathlib import Path
from typing import Any, Callable

BASE_DIR = Path(__file__).resolve().parent
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))

import requests


def _configure_stdio() -> None:
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, OSError, ValueError):
            pass


_configure_stdio()

CLOUD_URL = os.getenv("DENNI_POV_CLOUD_URL", "https://denni-pov-kontrola.onrender.com").rstrip("/")
SYNC_TOKEN = os.getenv("DENNI_POV_SYNC_TOKEN", "OPYnDYQG4X5oVQPsKPE7qB25pw1YV9KUZWzFXcFrygfSvx1aKhkH_-MunoSx7Zof")
POLL_SECONDS = int(os.getenv("DENNI_POV_POLL_SECONDS", "15"))
AUTO_SYNC_SECONDS = int(os.getenv("DENNI_POV_AUTO_SYNC_SECONDS", "43200"))
SERVICE_MODE = os.getenv("DENNI_POV_SERVICE_MODE", "").strip().lower() in {"1", "true", "yes", "on"}


def _auto_update_from_github() -> None:
    base_dir = Path(__file__).resolve().parent
    if not (base_dir / ".git").exists(): return
    try:
        before = subprocess.run(["git", "rev-parse", "HEAD"], cwd=base_dir, capture_output=True, text=True, timeout=15).stdout.strip()
        if SERVICE_MODE:
            fetch = subprocess.run(["git", "fetch", "origin", "main"], cwd=base_dir, capture_output=True, text=True, timeout=60)
            if fetch.returncode != 0:
                print("Automatická aktualizace z GitHubu se nepodařila:", (fetch.stderr or fetch.stdout).strip()); return
            update = subprocess.run(["git", "reset", "--hard", "origin/main"], cwd=base_dir, capture_output=True, text=True, timeout=30)
        else:
            update = subprocess.run(["git", "pull", "--ff-only", "origin", "main"], cwd=base_dir, capture_output=True, text=True, timeout=60)
        if update.returncode != 0:
            print("Automatická aktualizace z GitHubu se nepodařila:", (update.stderr or update.stdout).strip()); return
        after = subprocess.run(["git", "rev-parse", "HEAD"], cwd=base_dir, capture_output=True, text=True, timeout=15).stdout.strip()
        if before and after and before != after:
            print("Stažena nová verze z GitHubu.")
            requirements = base_dir / "requirements.txt"
            if requirements.exists():
                deps = subprocess.run([sys.executable, "-m", "pip", "install", "-r", str(requirements)], cwd=base_dir, capture_output=True, text=True, timeout=180)
                if deps.returncode != 0:
                    print("Varování: aktualizace Python balíčků se nepodařila:", (deps.stderr or deps.stdout).strip())
            print("Restartuji agenta na nové verzi...")
            os.execv(sys.executable, [sys.executable, str(Path(__file__).resolve()), *sys.argv[1:]])
    except Exception as exc:
        print("Kontrola aktualizace GitHubu selhala:", exc)


def _load_local_app():
    if os.name == "nt":
        import windows_bootstrap
        return windows_bootstrap.web_app
    import local_app
    return local_app


def _headers() -> dict[str, str]:
    return {"Authorization": f"Bearer {SYNC_TOKEN}", "Content-Type": "application/json", "User-Agent": f"DENNI-POV-Agent/{platform.system()}"}


def _reset_for_run(local_app) -> None:
    with local_app._lock:
        local_app._state["running"] = True
        local_app._state["started_at"] = local_app._now()
        local_app._state["finished_at"] = None
        local_app._state["error"] = None
        local_app._state["results"] = []
        local_app._state["last_csv"] = None
        local_app._state["sources"] = {
            "tirbazar": {"state": "loading", "status": "Načítám vstupní data přehledu vozidel…", "detail": "SQL Server / pouze čtení"},
            "uniqa": {"state": "idle", "status": "Čekám…", "detail": "Aktivní smlouvy"},
            "allianz": {"state": "idle", "status": "Čekám…", "detail": "Aktivní smlouvy"},
        }


def _progress_for(snapshot: dict[str, Any]) -> dict[str, Any]:
    if snapshot.get("error"):
        return {"percent": 100, "phase": "Kontrola skončila chybou", "eta_seconds": 0}
    if not snapshot.get("running"):
        return {"percent": 100, "phase": "Hotovo", "eta_seconds": 0}
    sources = snapshot.get("sources") or {}
    tir = (sources.get("tirbazar") or {}).get("state", "idle")
    uniqa = (sources.get("uniqa") or {}).get("state", "idle")
    allianz = (sources.get("allianz") or {}).get("state", "idle")
    if tir == "loading":
        return {"percent": 15, "phase": "Načítám vstupní data přehledu vozidel", "eta_seconds": 70}
    if tir == "ok" and uniqa in {"idle", "loading"}:
        return {"percent": 50, "phase": "Kontroluji přehled pojištěných vozidel – UNIQA", "eta_seconds": 35}
    if uniqa in {"ok", "error"} and allianz in {"idle", "loading"}:
        return {"percent": 82, "phase": "Kontroluji přehled pojištěných vozidel – ALLIANZ", "eta_seconds": 12}
    if allianz in {"ok", "error"}:
        return {"percent": 94, "phase": "Porovnávám TIRBazar × UNIQA × ALLIANZ", "eta_seconds": 5}
    return {"percent": 8, "phase": "Připravuji kontrolu", "eta_seconds": 80}


def _decorate_snapshot(snapshot: dict[str, Any]) -> dict[str, Any]:
    snapshot = dict(snapshot)
    snapshot["progress"] = _progress_for(snapshot)
    snapshot["agent"] = {"computer": platform.node(), "system": platform.system()}
    return snapshot


def push_snapshot(snapshot: dict[str, Any]) -> None:
    response = requests.post(f"{CLOUD_URL}/api/sync", headers=_headers(), json=snapshot, timeout=45)
    response.raise_for_status()


def _send_result_email(snapshot: dict[str, Any]) -> bool:
    if snapshot.get("error"):
        return False

    host = os.getenv("SMTP_HOST", "smtp.websupport.cz").strip()
    port = int(os.getenv("SMTP_PORT", "465") or 465)
    user = os.getenv("SMTP_USER", "kontrolapojisteni@vanscentre.com").strip()
    password = os.getenv("SMTP_PASSWORD", "")
    from_addr = os.getenv("ALERT_EMAIL_FROM", user).strip()
    to_addr = os.getenv("ALERT_EMAIL_TO", "jakubwurm@vanscentre.com").strip()
    use_tls = os.getenv("SMTP_TLS", "0").strip().lower() not in {"0", "false", "no", "off"}

    if not host or not user or not password or not from_addr or not to_addr:
        print("E-mail výsledku nebyl odeslán: chybí SMTP nastavení nebo uložené heslo.")
        return False

    # Po finální synchronizaci použij veřejný stav z webu. Ten už zahrnuje
    # trvalé ruční stavy řešení a stejné počítání jako dashboard.
    email_snapshot = snapshot
    try:
        response = requests.get(f"{CLOUD_URL}/api/state", timeout=20)
        response.raise_for_status()
        cloud_state = response.json()
        if isinstance(cloud_state, dict) and isinstance(cloud_state.get("summary"), dict):
            if cloud_state.get("finished_at") != snapshot.get("finished_at") or cloud_state.get("running") or cloud_state.get("error"):
                return False
            email_snapshot = cloud_state
        else:
            return False
    except Exception as exc:
        print("E-mail neodeslán: výsledek webu nelze ověřit:", exc)
        return False

    summary = email_snapshot.get("summary") or {}
    missing = int(summary.get("missing") or 0)
    absent_insured = int(summary.get("absent_insured") or 0)
    sold_uniqa = int(summary.get("sold_uniqa") or 0)
    extra_uniqa = int(summary.get("extra_uniqa") or 0)
    spz_mismatch = int(summary.get("spz_mismatch") or 0)
    unverified = int(summary.get("unverified") or 0)
    problem_statuses = {"CHYBÍ V UNIQA", "NEPŘÍTOMNÉ, ALE POJIŠTĚNÉ", "PRODANÉ, ALE V UNIQA", "NAVÍC V UNIQA", "SPZ NESOUHLASÍ", "NELZE OVĚŘIT"}
    problems = 0
    for row in email_snapshot.get("results") or []:
        raw = str(row.get("status_raw") or "").upper()
        workflow = str(row.get("workflow_status") or "").upper()
        resolved = workflow == "VYŘEŠENO" if raw == "NEPŘÍTOMNÉ, ALE POJIŠTĚNÉ" else workflow in {"VYŘEŠENO", "V POŘÁDKU"}
        problems += raw in problem_statuses and not resolved
    if not problems:
        print("Kontrola bez otevřených případů – e-mail se neodesílá.")
        return False
    active = int(summary.get("active") or 0)
    ok_total = int(summary.get("ok_total") or 0)
    subject = f"DENNÍ POV: VYŽADUJE KONTROLU ({problems})"

    lines = [
        "DENNÍ POV – výsledek kontroly",
        "",
        f"Kontrola dokončena: {email_snapshot.get('finished_at') or snapshot.get('finished_at') or datetime.now().strftime('%d.%m.%Y %H:%M:%S')}",
        f"Aktivní vozidla ke kontrole: {active}",
        f"Pojištěno správně: {ok_total}",
        f"Nepřítomné · nepojištěno: {int(summary.get('absent_uninsured') or 0)}",
        f"Chybí pojištění: {missing}",
        f"Pojištění navíc: {absent_insured + sold_uniqa + extra_uniqa}",
        "",
    ]
    if missing > 0:
        lines.append("Vozidla s chybějícím pojištěním:")
        for row in email_snapshot.get("results") or []:
            status_raw = str(row.get("status_raw") or "").upper()
            status = str(row.get("status") or "").upper()
            if status_raw == "CHYBÍ V UNIQA" or status == "CHYBÍ POJIŠTĚNÍ":
                lines.append(f"VIN: {row.get('vin') or '-'} | SPZ: {row.get('spz_tir') or '-'} | {row.get('detail') or ''}")
        lines.append("")
    lines.append(f"Web: {CLOUD_URL}")

    msg = EmailMessage()
    msg["Subject"] = subject
    msg["From"] = from_addr
    msg["To"] = to_addr
    msg.set_content("\n".join(lines))

    try:
        smtp_class = smtplib.SMTP_SSL if port == 465 else smtplib.SMTP
        with smtp_class(host, port, timeout=12) as smtp:
            if use_tls and port != 465:
                smtp.starttls()
            smtp.login(user, password)
            smtp.send_message(msg)
        print(f"E-mail s výsledkem kontroly byl odeslán na {to_addr}.")
        return True
    except Exception as exc:
        print("E-mail výsledku se nepodařilo odeslat:", exc)
        return False


def run_local_check(progress_callback: Callable[[dict[str, Any]], None] | None = None) -> dict[str, Any]:
    local_app = _load_local_app()
    _reset_for_run(local_app)
    worker = threading.Thread(target=local_app._run_check_worker, daemon=True)
    worker.start()
    while worker.is_alive():
        if progress_callback:
            try:
                progress_callback(_decorate_snapshot(local_app._snapshot()))
            except Exception as exc:
                print("Průběžný stav se nepodařilo odeslat:", exc)
        worker.join(timeout=3)
    return _decorate_snapshot(local_app._snapshot())


def get_command() -> dict[str, Any] | None:
    response = requests.get(f"{CLOUD_URL}/api/agent/command", headers=_headers(), timeout=20)
    response.raise_for_status()
    payload = response.json()
    command = payload.get("command")
    return command if isinstance(command, dict) else None


def lookup_vehicle(command: dict[str, Any]) -> None:
    command_id = str(command.get("id") or "").strip()
    query = str(command.get("query") or command.get("vin") or "").replace(" ", "").strip().upper()
    query_type = str(command.get("query_type") or ("vin" if len(query) == 17 else "spz")).lower()
    payload: dict[str, Any] = {"id": command_id, "query": query, "found": False, "vehicle": None, "error": ""}
    try:
        if not command_id or not query:
            raise ValueError("Neplatný požadavek na vyhledání.")
        local_app = _load_local_app()
        config = local_app.load_config()
        vehicles, _ = local_app.load_tirbazar_vehicles(config)
        if query_type == "vin":
            vehicle = next((item for item in vehicles if str(getattr(item, "vin", "") or "").replace(" ", "").strip().upper() == query), None)
        else:
            vehicle = next((item for item in vehicles if str(getattr(item, "spz", "") or "").replace(" ", "").strip().upper() == query), None)
        if vehicle is not None:
            payload["found"] = True
            payload["vehicle"] = {
                "oid": getattr(vehicle, "oid", None),
                "vin": getattr(vehicle, "vin", "") or "",
                "spz": getattr(vehicle, "spz", "") or "",
                "stav": getattr(vehicle, "stav", "") or "",
                "datum_vykupu": getattr(vehicle, "datum_vykupu", "") or "",
                "datum_prodeje": getattr(vehicle, "datum_prodeje", "") or "",
                "zeme_puvodu": getattr(vehicle, "zeme_puvodu", "") or "",
                "poznamky": getattr(vehicle, "poznamky", "") or "",
                "znacka": getattr(vehicle, "znacka", "") or "",
                "model": getattr(vehicle, "model", "") or "",
            }
    except Exception as exc:
        payload["error"] = str(exc).strip() or exc.__class__.__name__
    response = requests.post(f"{CLOUD_URL}/api/agent/lookup-result", headers=_headers(), json=payload, timeout=30)
    response.raise_for_status()


def _error_snapshot(exc: Exception) -> dict[str, Any]:
    message = str(exc).strip() or exc.__class__.__name__
    now = datetime.now().strftime("%d.%m.%Y %H:%M:%S")
    return {
        "running": False, "started_at": None, "finished_at": now, "error": message,
        "progress": {"percent": 100, "phase": "Kontrola skončila chybou", "eta_seconds": 0},
        "sources": {
            "tirbazar": {"state": "error", "status": "Kontrola se nepodařila", "detail": message},
            "uniqa": {"state": "idle", "status": "Neprovedeno", "detail": "Kontrola skončila před dokončením."},
            "allianz": {"state": "idle", "status": "Neprovedeno", "detail": "Kontrola skončila před dokončením."},
        },
        "summary": {"active": 0, "ok_total": 0, "ok_uniqa": 0, "ok_allianz": 0, "missing": 0, "deposit": 0, "sold_uniqa": 0, "extra_uniqa": 0},
        "results": [], "agent": {"computer": platform.node(), "system": platform.system()},
    }


def run_and_sync(reason: str) -> None:
    _auto_update_from_github()
    print(); print("=============================================="); print(" DENNI POV - ONLINE SYNCHRONIZACE"); print("==============================================")
    print(f"Důvod kontroly: {reason}")
    print("Načítám TIRBazar -> UNIQA -> Allianz...")
    snapshot = run_local_check(progress_callback=push_snapshot)
    if snapshot.get("error"):
        print("Kontrola skončila chybou:", snapshot.get("error"))
    else:
        print("Kontrola dokončena. Ukládám výsledky na web...")
        saving = dict(snapshot)
        saving["running"] = True
        saving["progress"] = {"percent": 98, "phase": "Ukládám výsledky na web", "eta_seconds": 3}
        push_snapshot(saving)
    push_snapshot(snapshot)
    print("Online web byl aktualizován:", CLOUD_URL)
    if not snapshot.get("error"):
        _send_result_email(snapshot)


def main() -> int:
    parser = argparse.ArgumentParser(description="DENNI POV kancelářský agent pro Render")
    parser.add_argument("--once", action="store_true")
    parser.add_argument("--no-initial", action="store_true")
    args = parser.parse_args()
    print("DENNI POV - kancelářský agent")
    print("Online web:", CLOUD_URL)
    print("Automatická kontrola: každých 12 hodin (2× denně).")
    print("Tento proces musí běžet na počítači, který vidí TIRBazar SQL a má přístup do UNIQA.")
    if args.once:
        run_and_sync("ruční jednorázová synchronizace"); return 0
    last_command_id = ""
    next_auto = time.monotonic()
    if args.no_initial: next_auto += AUTO_SYNC_SECONDS
    while True:
        try:
            command = get_command()
            command_id = str((command or {}).get("id", ""))
            if command_id and command_id != last_command_id:
                last_command_id = command_id
                action = str((command or {}).get("action") or "run_check")
                if action == "lookup_vehicle":
                    lookup_vehicle(command or {})
                else:
                    run_and_sync("požadavek z online webu")
                    next_auto = time.monotonic() + AUTO_SYNC_SECONDS
            elif time.monotonic() >= next_auto:
                run_and_sync("automatická kontrola 2× denně")
                next_auto = time.monotonic() + AUTO_SYNC_SECONDS
        except KeyboardInterrupt:
            print("\nAgent ukončen."); return 0
        except Exception as exc:
            print("Synchronizace se nepodařila:", exc)
            try:
                push_snapshot(_error_snapshot(exc)); print("Chyba byla odeslána na online web.")
            except Exception as report_exc:
                print("Nepodařilo se odeslat chybu na online web:", report_exc)
        time.sleep(max(5, POLL_SECONDS))


if __name__ == "__main__":
    sys.exit(main())
