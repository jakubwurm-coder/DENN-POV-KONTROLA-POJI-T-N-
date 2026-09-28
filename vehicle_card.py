from __future__ import annotations

import base64
import os
import re
import time
from datetime import datetime, timezone, timedelta
from urllib.parse import urljoin
from typing import Any

import requests
from flask import jsonify, render_template, request

KOSTKA_URL = "https://api.dataovozidlech.cz/api/vehicletechnicaldata/v2"
EDALNICE_INDEX_URL = "https://edalnice.gov.cz/"
EDALNICE_TOKEN_URL = "https://auth.edalnice.gov.cz/auth/connect/token"
EDALNICE_CHECK_BASE = "https://eshop.edalnice.gov.cz/api/v3/charge_registrations/3906ba89-153c-4038-8e36-0ca1deb76076"
_EDALNICE_TOKEN_CACHE = {"token": "", "expires_at": 0.0}
_EDALNICE_CLIENT_CACHE = {"client_id": "", "client_secret": "", "expires_at": 0.0}
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
        "stk_until": {"PRAVIDELNATECHNICKAPROHLIDKADO", "PRAVIDELNATECHNICKAPROHLIDKADO", "STKDO", "TECHNICKAPROHLIDKADO"},
        "first_registration": {"DATUMPRVNIREGISTRACE", "PRVNIREGISTRACE", "FIRSTREGISTRATIONDATE"},
        "fuel": {"PALIVO", "PALIVONAZEV", "FUEL"},
        "engine_ccm": {"MOTORZDVIHOBJEM", "ZDVIHOVYOBJEM", "ZDVIHOVYOBJEMMOTORU", "OBJEMMOTORU", "OBJEM", "ENGINECAPACITY", "ENGINECAPACITYCCM"},
        "power_kw": {"MOTORMAXVYKON", "MAXIMALNIVYKON", "MAXIMALNIVYKONKW", "NEJVYSSIVYKON", "VYKON", "VYKONKW", "POWERKW"},
        "color": {"VOZIDLOKAROSERIEBARVA", "BARVA", "BARVANAZEV", "BARVAVOZIDLA", "BARVAVOZIDLANAZEV", "COLOR"},
        "category": {"KATEGORIE", "KATEGORIEVOZIDLA", "VEHICLECATEGORY"},
    }
    result = {"vin": vin}
    for target, aliases in fields.items():
        value = _find_value(data, aliases)
        result[target] = str(value or "").strip()
    result["spz"] = re.sub(r"\s+", "", result["spz"]).upper()
    result["stk_until"] = _date(result["stk_until"])
    result["inspection_from"] = _date(_find_value(data, {"PREDREGISTRACIPROHLIDKADNE"}))
    result["inspection_until"] = _date(_find_value(data, {"PREDREGISTRACIPROHLIDKADO", "PREDREGISTRACIPROHLIDKAPLATNOSTDO"}))\n    if not result["inspection_until"] and result["inspection_from"]:\n        try:\n            start = datetime.strptime(result["inspection_from"], "%d.%m.%Y")\n            result["inspection_until"] = start.replace(year=start.year + 2).strftime("%d.%m.%Y")\n        except ValueError:\n            pass\n    result["technical_until"] = result["stk_until"] or result["inspection_until"]
    result["fuel"] = {"NM": "Nafta"}.get(result["fuel"].upper(), result["fuel"])
    power = re.match(r"^\s*(\d+(?:[.,]\d+)?)", result["power_kw"])
    result["power_kw"] = power.group(1).replace(",", ".") if power else ""
    if result["engine_ccm"].endswith(".0"):
        result["engine_ccm"] = result["engine_ccm"][:-2]
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


def _edalnice_headers(accept: str = "*/*") -> dict[str, str]:
    return {
        "Accept": accept,
        "Accept-Language": "cs",
        "Referer": EDALNICE_INDEX_URL,
        "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/152.0.0.0 Safari/537.36",
    }


def _edalnice_client_credentials(force: bool = False) -> tuple[str, str]:
    now = time.time()
    if (not force and _EDALNICE_CLIENT_CACHE["client_id"] and
            _EDALNICE_CLIENT_CACHE["client_secret"] and
            _EDALNICE_CLIENT_CACHE["expires_at"] > now):
        return _EDALNICE_CLIENT_CACHE["client_id"], _EDALNICE_CLIENT_CACHE["client_secret"]

    configured = os.environ.get("EDALNICE_CLIENT_BASIC", "").strip()
    if ":" in configured:
        client_id, client_secret = configured.split(":", 1)
        if client_id and client_secret:
            _EDALNICE_CLIENT_CACHE.update({"client_id": client_id, "client_secret": client_secret, "expires_at": now + 86400})
            return client_id, client_secret

    response = requests.get(EDALNICE_INDEX_URL, headers=_edalnice_headers("text/html,application/xhtml+xml"), timeout=20)
    response.raise_for_status()
    script_urls = []
    for src in re.findall(r'<script[^>]+src=["\']([^"\']+)["\']', response.text, flags=re.IGNORECASE):
        url = urljoin(EDALNICE_INDEX_URL, src)
        if url not in script_urls:
            script_urls.append(url)

    patterns = [
        r'["\'](eshop\.client):([^"\']+)["\']',
        r'\b(eshop\.client):([A-Za-z0-9._~!*()\-]+)',
    ]
    for script_url in script_urls[:80]:
        try:
            script = requests.get(script_url, headers=_edalnice_headers(), timeout=20)
            script.raise_for_status()
            if "auth.edalnice.gov.cz/auth/connect/token" not in script.text and "eshop.client" not in script.text:
                continue
            for pattern in patterns:
                match = re.search(pattern, script.text)
                if match:
                    client_id, client_secret = match.group(1), match.group(2)
                    _EDALNICE_CLIENT_CACHE.update({"client_id": client_id, "client_secret": client_secret, "expires_at": now + 21600})
                    return client_id, client_secret
        except requests.RequestException:
            continue
    raise RuntimeError("eDálnice: v aktuálním webu nebyl nalezen veřejný OAuth klient.")


def _edalnice_token(force: bool = False) -> str:
    now = time.time()
    if not force and _EDALNICE_TOKEN_CACHE["token"] and _EDALNICE_TOKEN_CACHE["expires_at"] > now + 60:
        return _EDALNICE_TOKEN_CACHE["token"]
    client_id, client_secret = _edalnice_client_credentials(force=force)
    basic = base64.b64encode(f"{client_id}:{client_secret}".encode()).decode("ascii")
    response = requests.post(
        EDALNICE_TOKEN_URL,
        data={"grant_type": "client_credentials", "scope": "eshop.api"},
        headers={"Authorization": f"Basic {basic}", "Content-Type": "application/x-www-form-urlencoded", "Accept": "application/json", "User-Agent": _edalnice_headers()["User-Agent"]},
        timeout=20,
    )
    response.raise_for_status()
    payload = response.json()
    token = str(payload.get("access_token") or "").strip()
    if not token:
        raise RuntimeError("eDálnice nevrátila přístupový token.")
    _EDALNICE_TOKEN_CACHE.update({"token": token, "expires_at": now + max(60, int(payload.get("expires_in") or 300))})
    return token


def _edalnice_check(spz: str) -> dict[str, Any]:
    plate = re.sub(r"\\s+", "", str(spz or "")).upper()
    def make_request(token: str):
        headers = _edalnice_headers()
        headers.update({"Authorization": f"Bearer {token}", "Origin": EDALNICE_INDEX_URL.rstrip("/")})
        return requests.get(f"{EDALNICE_CHECK_BASE}/{plate}", headers=headers, timeout=20)

    response = make_request(_edalnice_token())
    if response.status_code == 401:
        _EDALNICE_TOKEN_CACHE.update({"token": "", "expires_at": 0.0})
        response = make_request(_edalnice_token(force=True))
    response.raise_for_status()
    payload = response.json()

    now = datetime.now(timezone.utc)
    intervals = []
    def collect(node):
        if isinstance(node, dict):
            if ("validSince" in node or "valid_since" in node) and ("validUntil" in node or "valid_until" in node):
                try:
                    s = datetime.fromisoformat(str(node.get("validSince") or node.get("valid_since")).replace("Z", "+00:00"))
                    e = datetime.fromisoformat(str(node.get("validUntil") or node.get("valid_until")).replace("Z", "+00:00"))
                    if s.tzinfo is None: s = s.replace(tzinfo=timezone.utc)
                    if e.tzinfo is None: e = e.replace(tzinfo=timezone.utc)
                    intervals.append((s, e))
                except Exception:
                    pass
            for value in node.values(): collect(value)
        elif isinstance(node, list):
            for value in node: collect(value)
    collect(payload)

    exempt = bool(payload.get("isGivenExemption") or payload.get("is_given_exemption")) if isinstance(payload, dict) else False
    if exempt:
        return {"state": "exempt", "message": "Vozidlo je evidováno jako osvobozené."}
    current = [(s, e) for s, e in intervals if s <= now <= e]
    future = sorted([(s, e) for s, e in intervals if s > now], key=lambda x: x[0])
    if current:
        effective_end = max(e for _, e in current)
        for s, e in future:
            if s.date() <= effective_end.date() + timedelta(days=1):
                effective_end = max(effective_end, e)
            else:
                break
        return {"state": "valid", "valid_until": effective_end.strftime("%d.%m.%Y"), "message": "Dálniční známka je platná."}
    if future:
        s, e = future[0]
        return {"state": "future", "valid_since": s.strftime("%d.%m.%Y"), "valid_until": e.strftime("%d.%m.%Y"), "message": "Dálniční známka začne platit později."}
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
