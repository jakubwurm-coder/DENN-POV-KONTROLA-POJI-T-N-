from __future__ import annotations

import os
import re
from datetime import datetime, timezone
from typing import Any

import requests
from flask import jsonify, render_template, request

KOSTKA_URL = "https://api.dataovozidlech.cz/api/vehicletechnicaldata/v2"
EDALNICE_TOKEN_URL = "https://auth.edalnice.cz/auth/connect/token"
EDALNICE_CHECK_BASE = "https://eshop.edalnice.cz/api/v3/charge_registrations/3906ba89-153c-4038-8e36-0ca1deb76076"
VIN_RE = re.compile(r"[A-HJ-NPR-Z0-9]{17}\Z")
SPZ_RE = re.compile(r"^[A-Z0-9]{5,10}$")


def _first_env(*names: str) -> str:
    for name in names:
        value = os.getenv(name, "").strip()
        if value:
            return value
    return ""


def _kostka_keys() -> list[str]:
    return list(dict.fromkeys(v for v in (
        _first_env("DATOVA_KOSTKA_API_KEY"),
        _first_env("DATOVA_KOSTKA_API_KEY_1"),
        _first_env("DATOVA_KOSTKA_API_KEY_2"),
    ) if v))


def _norm_key(value: Any) -> str:
    return re.sub(r"[^A-Z0-9]", "", str(value or "").upper())


def _find_value(data: Any, aliases: set[str]) -> Any:
    aliases = {_norm_key(a) for a in aliases}
    if isinstance(data, dict):
        for key, value in data.items():
            if _norm_key(key) in aliases and value not in (None, "", [], {}):
                return value
        for value in data.values():
            found = _find_value(value, aliases)
            if found not in (None, "", [], {}):
                return found
    elif isinstance(data, list):
        for value in data:
            found = _find_value(value, aliases)
            if found not in (None, "", [], {}):
                return found
    return None


def _date(value: Any) -> str:
    text = str(value or "").strip()
    if not text:
        return ""
    text = text[:10]
    for fmt in ("%Y-%m-%d", "%d.%m.%Y", "%d/%m/%Y"):
        try:
            return datetime.strptime(text, fmt).strftime("%d.%m.%Y")
        except ValueError:
            pass
    return text


def _technical_summary(data: dict[str, Any], vin: str) -> dict[str, str]:
    fields = {
        "spz": {"REGISTRACNIZNACKA", "RZ", "SPZ", "REGISTRATIONPLATE", "REGISTRATIONNUMBER"},
        "make": {"TOVARNIZNACKA", "ZNACKA", "MAKE", "VYROBCE"},
        "model": {"OBCHODNIOZNACENI", "MODEL", "TRADEDESCRIPTION"},
        "status": {"STATUSNAZEV", "STATUS", "STAV"},
        "stk_until": {"PRAVIDELNATECHNICKAPROHLIDKADO", "STKDO", "TECHNICKAPROHLIDKADO"},
        "first_registration": {"DATUMPRVNIREGISTRACE", "PRVNIREGISTRACE", "FIRSTREGISTRATIONDATE"},
        "fuel": {"PALIVO", "PALIVONAZEV", "FUEL"},
        "engine_ccm": {"ZDVIHOVYOBJEM", "OBJEMMOTORU", "ENGINECAPACITY"},
        "power_kw": {"MAXIMALNIVYKON", "VYKON", "POWERKW"},
        "color": {"BARVA", "BARVANAZEV", "COLOR"},
        "category": {"KATEGORIE", "KATEGORIEVOZIDLA", "VEHICLECATEGORY"},
    }
    result = {"vin": vin}
    for target, aliases in fields.items():
        value = _find_value(data, aliases)
        result[target] = str(value or "").strip()
    result["spz"] = re.sub(r"\s+", "", result["spz"]).upper()
    result["stk_until"] = _date(result["stk_until"])
    result["first_registration"] = _date(result["first_registration"])
    return result


def _kostka_fetch(vin: str) -> dict[str, Any]:
    keys = _kostka_keys()
    if not keys:
        raise RuntimeError("Na serveru není nastaven API klíč Datové kostky.")
    last_error = None
    for key in keys:
        try:
            response = requests.get(KOSTKA_URL, params={"vin": vin}, headers={"api_key": key}, timeout=15)
            if response.status_code in (401, 403):
                continue
            response.raise_for_status()
            payload = response.json()
            data = payload.get("Data") if isinstance(payload, dict) else None
            if isinstance(payload, dict) and payload.get("Status") == 1 and isinstance(data, dict) and data:
                return data
            raise RuntimeError("Datová kostka k VIN nevrátila technické údaje.")
        except requests.RequestException as exc:
            last_error = exc
    if last_error:
        raise RuntimeError("Datová kostka momentálně neodpovídá.") from last_error
    raise RuntimeError("API klíč Datové kostky nebyl přijat.")


def _edalnice_credentials() -> tuple[str, str]:
    return (
        _first_env("EDALNICE_CLIENT_ID", "VIGNETTE_CLIENT_ID"),
        _first_env("EDALNICE_CLIENT_SECRET", "VIGNETTE_CLIENT_SECRET"),
    )


def _edalnice_check(spz: str) -> dict[str, Any]:
    client_id, client_secret = _edalnice_credentials()
    if not client_id or not client_secret:
        return {"state": "unavailable", "message": "Na serveru nejsou nastavené přihlašovací údaje eDálnice."}

    token_response = requests.post(
        EDALNICE_TOKEN_URL,
        data={"grant_type": "client_credentials", "client_id": client_id, "client_secret": client_secret},
        timeout=15,
    )
    token_response.raise_for_status()
    token = token_response.json().get("access_token")
    if not token:
        raise RuntimeError("eDálnice nevrátila přístupový token.")

    response = requests.get(
        f"{EDALNICE_CHECK_BASE}/{spz}",
        headers={"Authorization": f"Bearer {token}", "Accept": "application/json"},
        timeout=15,
    )
    if response.status_code == 404:
        return {"state": "missing", "message": "Pro SPZ nebyla nalezena platná dálniční známka."}
    response.raise_for_status()
    payload = response.json()

    charges = _find_value(payload, {"charges"})
    if not isinstance(charges, list):
        charges = payload if isinstance(payload, list) else []

    today = datetime.now(timezone.utc).date()
    parsed = []
    for item in charges:
        if not isinstance(item, dict):
            continue
        since_raw = _find_value(item, {"validSince", "valid_from", "validFrom"})
        until_raw = _find_value(item, {"validUntil", "valid_to", "validTo"})
        try:
            since = datetime.fromisoformat(str(since_raw)[:10]).date() if since_raw else None
            until = datetime.fromisoformat(str(until_raw)[:10]).date() if until_raw else None
        except ValueError:
            continue
        if until:
            parsed.append((since, until))

    if parsed:
        latest = max(parsed, key=lambda x: x[1])
        since, until = latest
        state = "valid" if (since is None or since <= today) and until >= today else ("future" if since and since > today else "missing")
        return {
            "state": state,
            "valid_since": since.strftime("%d.%m.%Y") if since else "",
            "valid_until": until.strftime("%d.%m.%Y"),
            "message": "Dálniční známka je platná." if state == "valid" else ("Dálniční známka začne platit později." if state == "future" else "Dálniční známka není aktuálně platná."),
        }

    exempt = bool(_find_value(payload, {"exempt", "isExempt", "exemption"}))
    if exempt:
        return {"state": "exempt", "message": "Vozidlo je evidováno jako osvobozené."}
    return {"state": "missing", "message": "Pro SPZ nebyla nalezena platná dálniční známka."}


def _spz_from_denni_pov(vin: str) -> str:
    """Find registration plate in the current DENNI POV state by VIN."""
    try:
        import cloud_app
        state = cloud_app._load_state()
        for row in state.get("results") or []:
            if not isinstance(row, dict):
                continue
            row_vin = re.sub(r"\s+", "", str(row.get("vin") or "")).upper()
            if row_vin != vin:
                continue
            for field in ("spz_tir", "spz_uniqa", "spz_allianz", "spz"):
                spz = re.sub(r"\s+", "", str(row.get(field) or "")).upper()
                if spz and SPZ_RE.fullmatch(spz):
                    return spz
    except Exception:
        pass
    return ""


def install_vehicle_card(app) -> None:
    @app.get("/vehicle-card")
    def vehicle_card_page():
        return render_template("vehicle_card.html")

    @app.get("/api/vehicle-card")
    def vehicle_card_api():
        vin = re.sub(r"\s+", "", request.args.get("vin", "")).upper()
        if not VIN_RE.fullmatch(vin):
            return jsonify({"ok": False, "message": "Zadejte platný 17místný VIN."}), 400
        try:
            raw = _kostka_fetch(vin)
            vehicle = _technical_summary(raw, vin)
            spz = vehicle.get("spz", "")
            spz_source = "Datová kostka"
            if not spz or not SPZ_RE.fullmatch(spz):
                spz = _spz_from_denni_pov(vin)
                if spz:
                    vehicle["spz"] = spz
                    spz_source = "DENNÍ POV"
            vehicle["spz_source"] = spz_source if spz else ""
            if not spz or not SPZ_RE.fullmatch(spz):
                vignette = {"state": "unavailable", "message": "SPZ nebyla nalezena ani v Datové kostce, ani v DENNÍ POV; eDálnici proto nelze ověřit."}
            else:
                try:
                    vignette = _edalnice_check(spz)
                except requests.RequestException:
                    vignette = {"state": "unavailable", "message": "eDálnice momentálně neodpovídá."}
                except RuntimeError as exc:
                    vignette = {"state": "unavailable", "message": str(exc)}
            return jsonify({"ok": True, "vehicle": vehicle, "vignette": vignette})
        except RuntimeError as exc:
            return jsonify({"ok": False, "message": str(exc)}), 503
