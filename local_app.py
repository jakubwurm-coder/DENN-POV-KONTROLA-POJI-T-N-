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
from tirbazar import _is_czech_for_pov, _requires_pov_check, load_tirbazar_vehicles
import tirbazar
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
    "audit": {},
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
    if status == "DEPOZIT, ALE POJIŠTĚNÉ":
        return "DEPOZIT, ALE POJIŠTĚNO"
    if status == "NEPŘÍTOMNÉ, ALE POJIŠTĚNÉ":
        return "NEPŘÍTOMNÉ, ALE POJIŠTĚNO"
    if status == "NEPŘÍTOMNÉ, ALE NEPOJIŠTĚNÉ":
        return "NEPŘÍTOMNÉ, ALE NEPOJIŠTĚNO"
    if status == "PRODANÉ, ALE POJIŠTĚNÉ":
        return "POJIŠTĚNO NAVÍC"
    if status == "OK":
        return "POJIŠTĚNÍ V POŘÁDKU"
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
        # Aktivní počet je přesně množina vozidel vstupujících do běžné POV kontroly.
        # Depozit je samostatná výjimka a do aktivních vozidel se nezapočítává.
        "active": active_count,
        # "Pojištění v pořádku" znamená pouze technický výsledek OK.
        # Nepřítomné bez pojištění jsou správně, ale mají vlastní samostatnou kategorii.
        "ok_total": ok_uniqa + ok_allianz,
        "ok_uniqa": ok_uniqa,
        "ok_allianz": ok_allianz,
        "missing": counts.get("CHYBÍ V UNIQA", 0),
        "absent_insured": counts.get("NEPŘÍTOMNÉ, ALE POJIŠTĚNÉ", 0),
        "absent_uninsured": counts.get("NEPŘÍTOMNÉ, ALE NEPOJIŠTĚNÉ", 0),
        "deposit": deposit,
        "deposit_insured": counts.get("DEPOZIT, ALE POJIŠTĚNÉ", 0),
        "sold_uniqa": counts.get("PRODANÉ, ALE POJIŠTĚNÉ", 0),
        "extra_uniqa": counts.get("NAVÍC V UNIQA", 0),
        "spz_mismatch": counts.get("SPZ NESOUHLASÍ", 0),
        "unverified": counts.get("NELZE OVĚŘIT", 0),
    }


def _is_deposit_vehicle(vehicle) -> bool:
    """Depozit se vyhodnocuje pouze u aktuálně vykoupeného vozidla."""
    state = " ".join(str(getattr(vehicle, "stav", "") or "").strip().upper().split())
    if state not in {"VYKOUPENÉ", "VYKOUPENE"}:
        return False
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
        detail="Depozit - vozidlo nepojištěno",
        datum_vykupu=getattr(vehicle, "datum_vykupu", "") or "",
        datum_prodeje=getattr(vehicle, "datum_prodeje", "") or "",
    )


def _snapshot() -> dict[str, Any]:
    with _lock:
        results = list(_state["results"])

        visible_statuses = {
            "CHYBÍ V UNIQA",
            "PRODANÉ, ALE POJIŠTĚNÉ",
            "NAVÍC V UNIQA",
            "NEPOJIŠTĚNO, ALE DEPOZIT",
            "NEPŘÍTOMNÉ, ALE POJIŠTĚNÉ",
            "NEPŘÍTOMNÉ, ALE NEPOJIŠTĚNÉ",
        }

        # Viditelnost výsledku se nesmí řídit historickým datem prodeje.
        # O významu vozidla rozhoduje už porovnávací logika podle aktuálního
        # stavu TIRBazar.
        visible_results = list(results)

        return {
            "running": _state["running"],
            "started_at": _state["started_at"],
            "finished_at": _state["finished_at"],
            "error": _state["error"],
            "sources": {k: dict(v) for k, v in _state["sources"].items()},
            "summary": _summary(results, _state["active_count"]),
            "results": [_serialize_result(r) for r in visible_results],
            "audit": dict(_state.get("audit") or {}),
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


def _audit_filter_reason(vehicle) -> str:
    state = " ".join(str(getattr(vehicle, "stav", "") or "").strip().upper().split())
    if not getattr(vehicle, "vin", ""):
        return "Bez VIN"
    if not _is_czech_for_pov(vehicle):
        return "Mimo pravidla země / registrační značky"
    # PRODANÉ má přednost i před textem DEPOZIT v poznámce.
    if state in {"PRODANÉ", "PRODANE"}:
        return "Prodané – mimo POV přehled"
    if _is_deposit_vehicle(vehicle):
        return "Depozit"
    if state in {"NEPŘÍTOMNÉ", "NEPRITOMNE", "REZERVOVANÉ", "REZERVOVANE", "V KOMISI"} and not getattr(vehicle, "datum_vykupu", ""):
        return "Bez evidovaného výkupu"
    return f"Stav mimo POV: {getattr(vehicle, 'stav', '') or 'neuveden'}"


def _audit_vehicle_row(vehicle, eligible: bool) -> dict[str, object]:
    state = " ".join(str(getattr(vehicle, "stav", "") or "").strip().upper().split())
    absent = state in {"NEPŘÍTOMNÉ", "NEPRITOMNE"} and bool(getattr(vehicle, "datum_vykupu", ""))
    deposit = _is_deposit_vehicle(vehicle)
    sold = state in {"PRODANÉ", "PRODANE"}
    expected = "NEMÁ BÝT POJIŠTĚNO" if sold or absent or deposit else ("MÁ BÝT POJIŠTĚNO" if eligible else "MIMO POV")
    return {
        "oid": getattr(vehicle, "oid", None),
        "vin": getattr(vehicle, "vin", "") or "",
        "spz": getattr(vehicle, "spz", "") or "",
        "stav": getattr(vehicle, "stav", "") or "",
        "zeme_puvodu": getattr(vehicle, "zeme_puvodu", "") or "",
        "datum_vykupu": getattr(vehicle, "datum_vykupu", "") or "",
        "datum_prodeje": getattr(vehicle, "datum_prodeje", "") or "",
        "ocekavani": expected,
        "filtr": "" if eligible and not deposit else _audit_filter_reason(vehicle),
    }


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

        sold_vehicles = [
            vehicle
            for vehicle in vehicles
            if (
                bool(getattr(vehicle, "datum_prodeje", ""))
                or " ".join(str(getattr(vehicle, "stav", "") or "").strip().upper().split())
                   in {"PRODANÉ", "PRODANE"}
            )
        ]

        # Prodaná vozidla se kontrolují OBRÁCENĚ: očekáváme NEPOJIŠTĚNO.
        # Proto musí vstoupit do porovnání s UNIQA i Allianz, ale nesmí být
        # vyhodnocena jako CHYBÍ POJIŠTĚNÍ. compare.py jim dává vlastní větev.
        compare_vehicles_input = list(eligible_vehicles)
        compare_oids = {getattr(vehicle, "oid", None) for vehicle in compare_vehicles_input}
        for vehicle in sold_vehicles:
            if getattr(vehicle, "oid", None) not in compare_oids:
                compare_vehicles_input.append(vehicle)
                compare_oids.add(getattr(vehicle, "oid", None))

        sold_vins = {vehicle.vin for vehicle in sold_vehicles if vehicle.vin}
        ignored_vehicles = [
            vehicle
            for vehicle in vehicles
            if not _requires_pov_check(vehicle)
        ]

        # Prodané VIN nesmíme odstranit z UNIQA vstupu: právě jejich případnou
        # přítomnost v UNIQA/Allianz potřebujeme odhalit jako pojištění navíc.
        ignored_vins = {
            vehicle.vin
            for vehicle in ignored_vehicles
            if vehicle.vin and vehicle.vin not in sold_vins
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

        # Přímé dohledávání jednotlivých VIN v UNIQA provádíme pouze
        # pro běžná aktivní vozidla. Prodaných vozidel může být v historii
        # velmi mnoho; u nich stačí průnik s načteným seznamem aktivních
        # pojistek UNIQA. Jinak by kontrola dělala stovky až tisíce HTTP dotazů.
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
                f"GitHub · aktual_ALLIANZ.csv · {len(allianz.vehicles)} vozidel",
            )
        else:
            _set_source("allianz", "error", "Načtení selhalo", allianz.error or "Allianz není dostupná")

        uniqa_for_compare = [
            vehicle
            for vehicle in uniqa.vehicles
            if getattr(vehicle, "vin", "") not in ignored_vins
        ]

        results = compare_vehicles(
            tir=compare_vehicles_input,
            uniqa=uniqa_for_compare,
            uniqa_available=uniqa.available,
            uniqa_error=uniqa.error,
            allianz=allianz.vehicles,
            allianz_available=allianz.available,
            allianz_error=allianz.error,
        )

        # Auditní data patří ke stejnému běhu jako výsledek. Díky tomu Excel
        # zpětně ukáže přesně SQL/TIRBazar, UNIQA a Allianz použitá při rozhodnutí.
        result_by_oid = {
            getattr(result, "oid", None): result
            for result in results
            if getattr(result, "oid", None) is not None
        }
        uniqa_vins = {getattr(v, "vin", "") for v in uniqa.vehicles if getattr(v, "vin", "")}
        allianz_vins = {getattr(v, "vin", "") for v in allianz.vehicles if getattr(v, "vin", "")}
        allianz_spz = {getattr(v, "spz", "") for v in allianz.vehicles if getattr(v, "spz", "")}

        sql_rows = []
        for vehicle in vehicles:
            eligible = _requires_pov_check(vehicle)
            row = _audit_vehicle_row(vehicle, eligible)
            vin = getattr(vehicle, "vin", "") or ""
            spz = getattr(vehicle, "spz", "") or ""
            result = result_by_oid.get(getattr(vehicle, "oid", None))
            row["uniqa"] = "ANO" if vin and vin in uniqa_vins else "NE"
            row["allianz"] = "ANO" if (vin and vin in allianz_vins) or (spz and spz in allianz_spz) else "NE"
            row["vysledek"] = _display_status(result) if result is not None else (
                "SPRÁVNĚ NEPOJIŠTĚNO" if row["ocekavani"] == "NEMÁ BÝT POJIŠTĚNO" else row["filtr"]
            )
            sql_rows.append(row)

        audit = {
            "counts": {
                **dict(tirbazar.LAST_LOAD_STATS),
                "eligible_total": len(eligible_vehicles),
                "active_control": len(control_vehicles),
                "deposit": len(deposit_vehicles),
                "expected_insured": sum(1 for v in control_vehicles if " ".join(str(getattr(v, "stav", "") or "").strip().upper().split()) not in {"NEPŘÍTOMNÉ", "NEPRITOMNE"}),
                "expected_uninsured": sum(1 for v in control_vehicles if " ".join(str(getattr(v, "stav", "") or "").strip().upper().split()) in {"NEPŘÍTOMNÉ", "NEPRITOMNE"}) + len(deposit_vehicles),
                "uniqa": len(uniqa.vehicles),
                "allianz": len(allianz.vehicles),
            },
            "sql": sql_rows,
            "uniqa": [
                {
                    "vin": getattr(v, "vin", "") or "",
                    "spz": getattr(v, "spz", "") or "",
                    "cps": getattr(v, "cps", "") or "",
                    "poj_od": getattr(v, "poj_od", "") or "",
                    "poj_do": getattr(v, "poj_do", "") or "",
                }
                for v in uniqa.vehicles
            ],
            "allianz": [
                {
                    "identifikator": getattr(v, "identifier", "") or "",
                    "vin": getattr(v, "vin", "") or "",
                    "spz": getattr(v, "spz", "") or "",
                    "pojistka": getattr(v, "pojistka", "") or "",
                    "poj_od": getattr(v, "poj_od", "") or "",
                    "poj_do": getattr(v, "poj_do", "") or "",
                }
                for v in allianz.vehicles
            ],
            "duplicates": [
                [
                    _audit_vehicle_row(v, _requires_pov_check(v))
                    for v in group
                ]
                for group in duplicates
            ],
        }

        vehicle_by_oid = {
            vehicle.oid: vehicle
            for vehicle in compare_vehicles_input
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
            _state["audit"] = audit
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
