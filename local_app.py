from __future__ import annotations

import os
import threading
from collections import Counter
from datetime import datetime
from pathlib import Path
from typing import Any

from flask import Flask, jsonify, render_template, request, send_file

from allianz import load_allianz_vehicles
from compare import compare_vehicles
from config import load_config
from models import ComparisonResult
from report import prepare_output, write_comparison, write_duplicates, write_tirbazar_snapshot
from tirbazar import _requires_pov_check, load_tirbazar_vehicles
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
        "tirbazar": {"state": "idle", "status": "Zatím nenačteno", "detail": "• ke kontrole: 0"},
        "uniqa": {"state": "idle", "status": "Zatím nenačteno", "detail": "Aktivních VIN: 0 • Duplicitních VIN: 0"},
        "allianz": {"state": "idle", "status": "Zatím nenačteno", "detail": ""},
    },
}


@app.errorhandler(404)
def _api_not_found(exc):
    if request.path.startswith("/api/"):
        return jsonify({"ok": False, "message": f"API endpoint {request.path} nebyl nalezen."}), 404
    return exc


@app.errorhandler(500)
def _api_internal_error(exc):
    if request.path.startswith("/api/"):
        original = getattr(exc, "original_exception", None)
        detail = str(original or exc).strip() or "Interní chyba serveru"
        return jsonify({"ok": False, "message": detail}), 500
    return exc


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
    if status == "NEPŘÍTOMNÉ, ALE POJIŠTĚNÉ":
        return "NEPŘÍTOMNÉ, ALE POJIŠTĚNO"
    if status == "NEPŘÍTOMNÉ, ALE NEPOJIŠTĚNÉ":
        return "NEPŘÍTOMNÉ, ALE NEPOJIŠTĚNO"
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
        "znacka": getattr(result, "znacka", "") or "",
        "model": getattr(result, "model", "") or "",
        "vozidlo": " ".join(
            part for part in (
                getattr(result, "znacka", "") or "",
                getattr(result, "model", "") or "",
            )
            if part
        ),
        "vykup": _format_date(getattr(result, "datum_vykupu", "")),
        "prodej": _format_date(getattr(result, "datum_prodeje", "")),
        "detail": getattr(result, "detail", "") or "",
    }


def _summary(results, active_count: int) -> dict[str, int]:
    counts = Counter(getattr(r, "status", "") for r in results)
    ok_uniqa = sum(1 for r in results if getattr(r, "status", "") == "OK" and _insurance_company(r) == "UNIQA")
    ok_allianz = sum(1 for r in results if getattr(r, "status", "") == "OK" and _insurance_company(r) == "ALLIANZ")
    deposit = counts.get("NEPOJIŠTĚNO, ALE DEPOZIT", 0)
    return {
        # Cloud i e-mailová vrstva historicky odečítají depozit až při zobrazení.
        # Proto transportní souhrn drží hrubé počty včetně depozitů, zatímco
        # samotné porovnání pojištění depozitní vozidla vůbec nekontroluje.
        "active": active_count + deposit,
        "ok_total": ok_uniqa + ok_allianz + deposit + counts.get("NEPŘÍTOMNÉ, ALE NEPOJIŠTĚNÉ", 0),
        "ok_uniqa": ok_uniqa,
        "ok_allianz": ok_allianz,
        "missing": counts.get("CHYBÍ V UNIQA", 0),
        "absent_insured": counts.get("NEPŘÍTOMNÉ, ALE POJIŠTĚNÉ", 0),
        "absent_uninsured": counts.get("NEPŘÍTOMNÉ, ALE NEPOJIŠTĚNÉ", 0),
        "deposit": deposit,
        "sold_uniqa": counts.get("PRODANÉ, ALE V UNIQA", 0),
        "extra_uniqa": counts.get("NAVÍC V UNIQA", 0),
    }


def _is_deposit_vehicle(vehicle) -> bool:
    """Depozit je výjimka z POV kontroly bez ohledu na stav v pojišťovně."""
    return "DEPOZIT" in str(getattr(vehicle, "poznamky", "") or "").strip().upper()


def _deposit_result(vehicle) -> ComparisonResult:
    note = " ".join(str(getattr(vehicle, "poznamky", "") or "").split())
    if len(note) > 180:
        note = note[:177] + "..."
    return ComparisonResult(
        oid=getattr(vehicle, "oid", None),
        vin=getattr(vehicle, "vin", "") or "",
        tir_spz=getattr(vehicle, "spz", "") or "",
        uniqa_spz="",
        status="NEPOJIŠTĚNO, ALE DEPOZIT",
        detail=(
            "Vozidlo je v TIRBazar označeno jako DEPOZIT a proto je vyřazeno "
            "z kontroly povinného ručení."
            + (f" Poznámka: {note}" if note else "")
        ),
        datum_vykupu=getattr(vehicle, "datum_vykupu", "") or "",
        datum_prodeje=getattr(vehicle, "datum_prodeje", "") or "",
    )


def _snapshot() -> dict[str, Any]:
    with _lock:
        results = list(_state["results"])

        visible_statuses = {
            "CHYBÍ V UNIQA",
            "PRODANÉ, ALE V UNIQA",
            "NAVÍC V UNIQA",
            "NEPOJIŠTĚNO, ALE DEPOZIT",
            "NEPŘÍTOMNÉ, ALE POJIŠTĚNÉ",
            "NEPŘÍTOMNÉ, ALE NEPOJIŠTĚNÉ",
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

        eligible_vehicles = [
            vehicle for vehicle in vehicles if _requires_pov_check(vehicle)
        ]

        deposit_vehicles = [
            vehicle for vehicle in eligible_vehicles if _is_deposit_vehicle(vehicle)
        ]
        control_vehicles = [
            vehicle for vehicle in eligible_vehicles if not _is_deposit_vehicle(vehicle)
        ]

        ignored_vehicles = [
            vehicle
            for vehicle in vehicles
            if not _requires_pov_check(vehicle) or _is_deposit_vehicle(vehicle)
        ]

        ignored_vins = {
            vehicle.vin
            for vehicle in ignored_vehicles
            if vehicle.vin
        }

        active_count = len(control_vehicles)
        deposit_count = len(deposit_vehicles)

        with _lock:
            _state["active_count"] = active_count

        _set_source(
            "tirbazar",
            "ok",
            f"Načteno: {_now()}",
            f"– • ke kontrole: {active_count} • depozit vyřazen: {deposit_count}",
        )

        _set_source("uniqa", "loading", "Načítám UNIQA…")

        control_vins = [
            vehicle.vin
            for vehicle in control_vehicles
            if vehicle.vin
        ]
        uniqa = load_uniqa_vehicles(required_vins=control_vins)

        if uniqa.available:
            duplicate_count = len(getattr(uniqa, "duplicates", []))
            _set_source(
                "uniqa",
                "ok",
                f"Načteno: {_now()}",
                (
                    f"Aktivních VIN: {len(uniqa.vehicles)}"
                    f" • Duplicitních VIN: {duplicate_count}"
                ),
            )
        else:
            _set_source("uniqa", "error", "Načtení selhalo", uniqa.error or "UNIQA není dostupná")

        _set_source("allianz", "loading", "Načítám Allianz…")
        allianz = load_allianz_vehicles()
        if allianz.available:
            _set_source(
                "allianz",
                "ok",
                f"Načteno: {_now()}",
                "",
            )
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

        results.extend(_deposit_result(vehicle) for vehicle in deposit_vehicles)

        vehicle_by_oid = {
            vehicle.oid: vehicle
            for vehicle in [*control_vehicles, *deposit_vehicles]
        }
        for result in results:
            source_vehicle = vehicle_by_oid.get(getattr(result, "oid", None))
            if source_vehicle is not None:
                result.znacka = getattr(source_vehicle, "znacka", "") or ""
                result.model = getattr(source_vehicle, "model", "") or ""

        base = prepare_output()

        try:
            write_tirbazar_snapshot(control_vehicles, base)
        except TypeError:
            write_tirbazar_snapshot(control_vehicles, [], base)

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
            "tirbazar": {"state": "loading", "status": "Čekám…", "detail": "• ke kontrole: 0"},
            "uniqa": {"state": "idle", "status": "Čekám…", "detail": "Aktivních VIN: 0 • Duplicitních VIN: 0"},
            "allianz": {"state": "idle", "status": "Čekám…", "detail": ""},
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
