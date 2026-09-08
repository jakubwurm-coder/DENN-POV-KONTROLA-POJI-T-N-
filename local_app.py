from __future__ import annotations

import os
import threading
from collections import Counter
from datetime import datetime
from pathlib import Path
from typing import Any

from flask import Flask, jsonify, render_template, send_file

from allianz import load_allianz_vehicles
from compare import compare_vehicles
from config import load_config
from report import prepare_output, write_comparison, write_duplicates, write_tirbazar_snapshot
from tirbazar import _is_ignored_pov_state, load_tirbazar_vehicles
from uniqa import load_uniqa_vehicles

app = Flask(__name__)
app.config["JSON_AS_ASCII"] = False

_lock = threading.Lock()
_state: dict[str, Any] = {
    "running": False,
    "started_at": None,
    "finished_at": None,
    "error": None,
    "active_count": 0,
    "results": [],
    "last_csv": None,
    "sources": {
        "tirbazar": {"state": "idle", "status": "Zatím nenačteno", "detail": "SQL Server / pouze čtení"},
        "uniqa": {"state": "idle", "status": "Zatím nenačteno", "detail": "AIV / Denní POV / Aktivní"},
        "allianz": {"state": "idle", "status": "Zatím nenačteno", "detail": "Flotilové PDF"},
    },
}


def _now() -> str:
    return datetime.now().strftime("%d.%m.%Y %H:%M:%S")


def _insurance_company(result) -> str:
    detail = (getattr(result, "detail", "") or "").upper()
    if "ALLIANZ" in detail:
        return "ALLIANZ"
    if "UNIQA" in detail:
        return "UNIQA"
    return ""


def _display_status(result) -> str:
    status = getattr(result, "status", "") or ""
    if status == "CHYBÍ V UNIQA":
        return "CHYBÍ POJIŠTĚNÍ"
    if status == "NEPOJIŠTĚNO, ALE DEPOZIT":
        return "NEPOJIŠTĚNO, ALE DEPOZIT"
    if status == "OK":
        company = _insurance_company(result)
        if company == "UNIQA":
            return "OK – UNIQA"
        if company == "ALLIANZ":
            return "OK – ALLIANZ"
        return "OK"
    return status


def _format_date(value) -> str:
    if not value:
        return ""
    text = str(value).strip()
    if len(text) >= 10 and text[4:5] == "-" and text[7:8] == "-":
        return f"{text[8:10]}.{text[5:7]}.{text[0:4]}"
    return text


def _serialize_result(result) -> dict[str, str]:
    return {
        "status_raw": getattr(result, "status", "") or "",
        "status": _display_status(result),
        "pojistovna": _insurance_company(result),
        "vin": getattr(result, "vin", "") or "",
        "spz_tir": getattr(result, "tir_spz", "") or "",
        "spz_uniqa": getattr(result, "uniqa_spz", "") or "",
        "vykup": _format_date(getattr(result, "datum_vykupu", "")),
        "prodej": _format_date(getattr(result, "datum_prodeje", "")),
        "detail": getattr(result, "detail", "") or "",
    }


def _summary(results, active_count: int) -> dict[str, int]:
    counts = Counter(getattr(r, "status", "") for r in results)
    ok_uniqa = sum(1 for r in results if getattr(r, "status", "") == "OK" and _insurance_company(r) == "UNIQA")
    ok_allianz = sum(1 for r in results if getattr(r, "status", "") == "OK" and _insurance_company(r) == "ALLIANZ")
    return {
        "active": active_count,
        "ok_total": ok_uniqa + ok_allianz,
        "ok_uniqa": ok_uniqa,
        "ok_allianz": ok_allianz,
        "missing": counts.get("CHYBÍ V UNIQA", 0),
        "deposit": counts.get("NEPOJIŠTĚNO, ALE DEPOZIT", 0),
        "sold_uniqa": counts.get("PRODANÉ, ALE V UNIQA", 0),
        "extra_uniqa": counts.get("NAVÍC V UNIQA", 0),
    }


def _snapshot() -> dict[str, Any]:
    with _lock:
        results = list(_state["results"])

        visible_statuses = {
            "CHYBÍ V UNIQA",
            "PRODANÉ, ALE V UNIQA",
            "NAVÍC V UNIQA",
            "NEPOJIŠTĚNO, ALE DEPOZIT",
        }

        visible_results = [
            r
            for r in results
            if (
                not getattr(r, "datum_prodeje", "")
                or getattr(r, "status", "") in visible_statuses
            )
        ]

        return {
            "running": _state["running"],
            "started_at": _state["started_at"],
            "finished_at": _state["finished_at"],
            "error": _state["error"],
            "sources": {k: dict(v) for k, v in _state["sources"].items()},
            "summary": _summary(results, _state["active_count"]),
            "results": [_serialize_result(r) for r in visible_results],
            "csv_available": bool(
                _state["last_csv"]
                and Path(_state["last_csv"]).exists()
            ),
        }


def _set_source(name: str, state: str, status: str, detail: str | None = None) -> None:
    with _lock:
        _state["sources"][name]["state"] = state
        _state["sources"][name]["status"] = status
        if detail is not None:
            _state["sources"][name]["detail"] = detail


def _run_check_worker() -> None:
    try:
        config = load_config()

        _set_source("tirbazar", "loading", "Načítám…")
        vehicles, duplicates = load_tirbazar_vehicles(config)

        # Vozidla ve stavech bez povinnosti POV se ponechají pouze interně,
        # abychom jejich VIN odstranili i z UNIQA porovnání. Díky tomu
        # nevznikne falešné "NAVÍC V UNIQA".
        ignored_vehicles = [
            vehicle for vehicle in vehicles if _is_ignored_pov_state(vehicle.stav)
        ]
        ignored_vins = {
            vehicle.vin
            for vehicle in ignored_vehicles
            if vehicle.vin
        }
        control_vehicles = [
            vehicle
            for vehicle in vehicles
            if not _is_ignored_pov_state(vehicle.stav)
        ]

        active_count = sum(
            1
            for vehicle in control_vehicles
            if not vehicle.datum_prodeje
        )
        with _lock:
            _state["active_count"] = active_count
        _set_source(
            "tirbazar",
            "ok",
            f"Načteno: {_now()}",
            (
                f"SQL Server • Aktivních ke kontrole: {active_count}"
                f" • Stavem bez POV ignorováno: {len(ignored_vehicles)}"
            ),
        )

        _set_source("uniqa", "loading", "Načítám UNIQA…")
        uniqa = load_uniqa_vehicles()
        if uniqa.available:
            duplicate_count = len(getattr(uniqa, "duplicates", []))
            _set_source("uniqa", "ok", f"Načteno: {_now()}", f"Aktivních VIN: {len(uniqa.vehicles)} • Duplicitních VIN: {duplicate_count}")
        else:
            _set_source("uniqa", "error", "Načtení selhalo", uniqa.error or "UNIQA není dostupná")

        _set_source("allianz", "loading", "Načítám Allianz…")
        allianz = load_allianz_vehicles()
        if allianz.available:
            _set_source("allianz", "ok", f"Načteno: {_now()}", f"Vozidel: {len(allianz.vehicles)} • Období: {allianz.period_od} – {allianz.period_do}")
        else:
            _set_source("allianz", "error", "Načtení selhalo", allianz.error or "Allianz není dostupná")

        uniqa_for_compare = [
            vehicle
            for vehicle in uniqa.vehicles
            if getattr(vehicle, "vin", "") not in ignored_vins
        ]

        results = compare_vehicles(
            tir=control_vehicles,
            uniqa=uniqa_for_compare,
            uniqa_available=uniqa.available,
            uniqa_error=uniqa.error,
            allianz=allianz.vehicles,
            allianz_available=allianz.available,
            allianz_error=allianz.error,
        )

        base = prepare_output()

        # Snapshot i report dostávají pouze vozidla relevantní pro POV.
        try:
            write_tirbazar_snapshot(control_vehicles, base)
        except TypeError:
            active = [vehicle for vehicle in control_vehicles if not vehicle.datum_prodeje]
            sold = [vehicle for vehicle in control_vehicles if vehicle.datum_prodeje]
            write_tirbazar_snapshot(active, sold, base)

        write_duplicates(duplicates, base)
        csv_path = write_comparison(results, base)

        with _lock:
            _state["results"] = results
            _state["last_csv"] = str(csv_path)
            _state["finished_at"] = _now()
            _state["error"] = None
    except Exception as exc:
        with _lock:
            _state["error"] = str(exc)
            _state["finished_at"] = _now()
    finally:
        with _lock:
            _state["running"] = False


@app.get("/")
def index():
    return render_template("index.html")


@app.get("/api/state")
def api_state():
    return jsonify(_snapshot())


@app.post("/api/run")
def api_run():
    with _lock:
        if _state["running"]:
            return jsonify({"ok": False, "message": "Kontrola už probíhá."}), 409
        _state["running"] = True
        _state["started_at"] = _now()
        _state["finished_at"] = None
        _state["error"] = None
        _state["sources"] = {
            "tirbazar": {"state": "loading", "status": "Čekám…", "detail": "SQL Server / pouze čtení"},
            "uniqa": {"state": "idle", "status": "Čekám…", "detail": "AIV / Denní POV / Aktivní"},
            "allianz": {"state": "idle", "status": "Čekám…", "detail": "Flotilové PDF"},
        }

    threading.Thread(target=_run_check_worker, daemon=True).start()
    return jsonify({"ok": True, "message": "Kontrola spuštěna."})


@app.get("/download/csv")
def download_csv():
    with _lock:
        path = _state["last_csv"]
    if not path or not Path(path).exists():
        return jsonify({"ok": False, "message": "CSV zatím není k dispozici."}), 404
    return send_file(path, as_attachment=True, download_name=Path(path).name)


@app.get("/health")
def health():
    return jsonify({"ok": True, "service": "DENNI POV - KONTROLA"})


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "5000"))
    app.run(host="0.0.0.0", port=port, debug=os.environ.get("FLASK_DEBUG") == "1")
