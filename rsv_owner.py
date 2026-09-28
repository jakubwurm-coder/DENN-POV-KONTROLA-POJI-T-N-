from __future__ import annotations

import csv
import io
import json
import os
import re
import threading
import time
import unicodedata
from datetime import datetime, timezone
from typing import Any

import requests

VEHICLES_CSV_URL = "https://download.dataovozidlech.cz/vypiszregistru/vypisvozidel"
OWNERS_CSV_URL = "https://download.dataovozidlech.cz/vypiszregistru/vlastnikprovozovatelvozidla"
CACHE_DAYS = 40

_lock = threading.Lock()
_scan_lock = threading.Lock()
_jobs: dict[str, dict[str, Any]] = {}


def _norm(value: Any) -> str:
    text = unicodedata.normalize("NFKD", str(value or ""))
    text = "".join(ch for ch in text if not unicodedata.combining(ch))
    return re.sub(r"[^A-Z0-9]", "", text.upper())


def _field(row: dict[str, Any], *aliases: str) -> str:
    wanted = {_norm(alias) for alias in aliases}
    for key, value in row.items():
        if _norm(key) in wanted:
            return str(value or "").strip()
    return ""


def _date(value: Any) -> str:
    text = str(value or "").strip()
    if not text:
        return ""
    for fmt in ("%Y-%m-%d", "%d.%m.%Y", "%d/%m/%Y"):
        try:
            return datetime.strptime(text[:10], fmt).strftime("%d.%m.%Y")
        except ValueError:
            pass
    return text


def _db_connect():
    url = os.getenv("DATABASE_URL", "").strip()
    if not url:
        return None
    import psycopg
    return psycopg.connect(url, connect_timeout=8)


def _db_init(cur) -> None:
    cur.execute("""
        CREATE TABLE IF NOT EXISTS denni_pov_vehicle_owner_cache (
            vin TEXT PRIMARY KEY,
            pcv TEXT NOT NULL DEFAULT '',
            data JSONB NOT NULL DEFAULT '{}'::jsonb,
            fetched_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
        )
    """)


def _cache_get(vin: str) -> dict[str, Any] | None:
    try:
        conn = _db_connect()
        if conn is None:
            return None
        with conn:
            with conn.cursor() as cur:
                _db_init(cur)
                cur.execute("""
                    SELECT pcv, data, fetched_at
                    FROM denni_pov_vehicle_owner_cache
                    WHERE vin = %s
                      AND fetched_at >= NOW() - (%s * INTERVAL '1 day')
                """, (vin, CACHE_DAYS))
                row = cur.fetchone()
        if not row:
            return None
        data = row[1] if isinstance(row[1], dict) else json.loads(row[1] or "{}")
        data["pcv"] = str(row[0] or data.get("pcv") or "")
        data["cached"] = True
        data["fetched_at"] = row[2].astimezone(timezone.utc).isoformat() if row[2] else ""
        return data
    except Exception as exc:
        print(f"RSV owner cache read failed: {exc.__class__.__name__}")
        return None


def _cache_save(vin: str, payload: dict[str, Any]) -> None:
    try:
        conn = _db_connect()
        if conn is None:
            return
        with conn:
            with conn.cursor() as cur:
                _db_init(cur)
                cur.execute("""
                    INSERT INTO denni_pov_vehicle_owner_cache (vin, pcv, data, fetched_at)
                    VALUES (%s, %s, %s::jsonb, NOW())
                    ON CONFLICT (vin) DO UPDATE
                    SET pcv = EXCLUDED.pcv,
                        data = EXCLUDED.data,
                        fetched_at = NOW()
                """, (
                    vin,
                    str(payload.get("pcv") or ""),
                    json.dumps(payload, ensure_ascii=False),
                ))
    except Exception as exc:
        print(f"RSV owner cache save failed: {exc.__class__.__name__}")


def _csv_rows(url: str):
    response = requests.get(
        url,
        stream=True,
        timeout=(15, 300),
        headers={
            "Accept": "text/csv,*/*",
            "User-Agent": "DENNI-POV/1.0 (+vehicle-card)",
        },
    )
    response.raise_for_status()
    response.raw.decode_content = True
    wrapper = io.TextIOWrapper(response.raw, encoding="utf-8-sig", newline="")
    try:
        yield from csv.DictReader(wrapper)
    finally:
        try:
            wrapper.detach()
        except Exception:
            pass
        response.close()


def _pcv_for_vin(vin: str) -> str:
    target = _norm(vin)
    for row in _csv_rows(VEHICLES_CSV_URL):
        row_vin = _norm(_field(row, "VIN"))
        if row_vin == target:
            return _field(row, "PČV", "PCV")
    return ""


def _subject_public(row: dict[str, Any]) -> dict[str, Any]:
    subject_type = _field(row, "Typ subjektu")
    relation = _field(row, "Vztah k vozidlu")
    is_company = subject_type == "2"
    labels = {
        "1": "Vlastník",
        "2": "Provozovatel",
        "3": "Spoluvlastník",
        "4": "Nabyvatel",
    }
    subject_labels = {
        "1": "Fyzická osoba",
        "2": "Právnická osoba",
        "3": "Neztotožněný subjekt",
    }
    result = {
        "relation_code": relation,
        "relation": labels.get(relation, "Vztah k vozidlu"),
        "subject_type_code": subject_type,
        "subject_type": subject_labels.get(subject_type, "Subjekt"),
        "current": _field(row, "Aktuální").lower() in {"true", "1", "ano", "yes"},
        "date_from": _date(_field(row, "Datum od")),
        "date_to": _date(_field(row, "Datum do")),
        "name": "",
        "ico": "",
        "address": "",
    }
    # Na veřejné kartě zveřejňujeme konkrétní identifikační údaje jen u právnických osob.
    if is_company:
        result["name"] = _field(row, "Název", "Nazev")
        result["ico"] = _field(row, "IČO", "ICO")
        result["address"] = _field(row, "Adresa")
    return result


def _ownership_for_pcv(pcv: str) -> list[dict[str, Any]]:
    current: list[dict[str, Any]] = []
    historical: list[dict[str, Any]] = []
    found_target = False
    for row in _csv_rows(OWNERS_CSV_URL):
        row_pcv = _field(row, "PČV", "PCV")
        if row_pcv != pcv:
            # Exporty RSV bývají seskupené podle PČV. Po nalezení cílového bloku už nemusíme číst zbytek.
            if found_target:
                break
            continue
        found_target = True
        subject = _subject_public(row)
        if subject["current"]:
            current.append(subject)
        else:
            historical.append(subject)

    def relation_order(item: dict[str, Any]) -> tuple[int, str]:
        code = str(item.get("relation_code") or "")
        return ({"1": 1, "2": 2, "3": 3, "4": 4}.get(code, 9), str(item.get("date_from") or ""))

    current.sort(key=relation_order)
    historical.sort(key=relation_order)
    return current + historical


def _build(vin: str) -> dict[str, Any]:
    pcv = _pcv_for_vin(vin)
    if not pcv:
        return {
            "state": "not_found",
            "message": "PČV k tomuto VIN nebylo v aktuálním výpisu RSV nalezeno.",
            "pcv": "",
            "subjects": [],
        }
    subjects = _ownership_for_pcv(pcv)
    current = [item for item in subjects if item.get("current")]
    return {
        "state": "ready",
        "message": "Aktuální údaje vlastníka a provozovatele načteny z RSV." if current else "RSV k vozidlu nevrátil aktuálního vlastníka ani provozovatele.",
        "pcv": pcv,
        "subjects": current,
    }


def _worker(vin: str) -> None:
    try:
        with _scan_lock:
            payload = _build(vin)
        if payload.get("state") in {"ready", "not_found"}:
            _cache_save(vin, payload)
        with _lock:
            _jobs[vin] = {"state": payload.get("state") or "ready", "payload": payload, "finished": time.time()}
    except Exception as exc:
        print(f"RSV owner lookup {vin} failed: {exc.__class__.__name__}: {exc}")
        with _lock:
            _jobs[vin] = {
                "state": "unavailable",
                "payload": {
                    "state": "unavailable",
                    "message": "Údaje vlastníka/provozovatele se teď nepodařilo načíst.",
                    "pcv": "",
                    "subjects": [],
                },
                "finished": time.time(),
            }


def get_ownership(vin: str, start: bool = True) -> dict[str, Any]:
    vin = _norm(vin)
    if len(vin) != 17:
        return {"state": "unavailable", "message": "Neplatné VIN.", "pcv": "", "subjects": []}

    cached = _cache_get(vin)
    if cached:
        cached.setdefault("state", "ready")
        cached.setdefault("subjects", [])
        return cached

    with _lock:
        job = _jobs.get(vin)
        if job:
            if job.get("state") in {"ready", "not_found", "unavailable"}:
                return dict(job.get("payload") or {})
            return {
                "state": "loading",
                "message": "Načítám vlastníka a provozovatele z měsíčního výpisu RSV…",
                "pcv": "",
                "subjects": [],
            }

        if start:
            _jobs[vin] = {"state": "loading", "started": time.time()}
            threading.Thread(target=_worker, args=(vin,), daemon=True, name=f"rsv-owner-{vin[-6:]}").start()

    return {
        "state": "loading" if start else "missing",
        "message": "Načítám vlastníka a provozovatele z měsíčního výpisu RSV…" if start else "Údaje zatím nejsou načtené.",
        "pcv": "",
        "subjects": [],
    }
