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


def _remote_size(url: str) -> int:
    headers = {
        "Accept": "text/csv,*/*",
        "User-Agent": "DENNI-POV/1.0 (+vehicle-card)",
    }
    try:
        head = requests.head(url, allow_redirects=True, timeout=(10, 20), headers=headers)
        if head.ok:
            size = int(head.headers.get("Content-Length") or 0)
            if size > 0:
                return size
    except Exception:
        pass
    try:
        range_headers = dict(headers)
        range_headers["Range"] = "bytes=0-0"
        probe = requests.get(url, stream=True, timeout=(10, 20), headers=range_headers)
        try:
            content_range = str(probe.headers.get("Content-Range") or "")
            match = re.search(r"/(\\d+)\\s*$", content_range)
            if match:
                return int(match.group(1))
            size = int(probe.headers.get("Content-Length") or 0)
            if probe.status_code == 206 and size > 1:
                return size
        finally:
            probe.close()
    except Exception:
        pass
    return 0


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
    total_bytes = int(response.headers.get("Content-Length") or 0) or _remote_size(url)
    response.raw.decode_content = True
    wrapper = io.TextIOWrapper(response.raw, encoding="utf-8-sig", newline="")
    try:
        reader = csv.DictReader(wrapper)
        for row in reader:
            try:
                bytes_read = int(response.raw.tell() or 0)
            except Exception:
                bytes_read = 0
            yield row, bytes_read, total_bytes
    finally:
        try:
            wrapper.detach()
        except Exception:
            pass
        response.close()


def _set_progress(
    vin: str,
    phase: str,
    rows: int,
    detail: str = "",
    bytes_read: int = 0,
    total_bytes: int = 0,
) -> None:
    with _lock:
        job = _jobs.setdefault(vin, {"state": "loading", "started": time.time()})
        job["state"] = "loading"
        job["phase"] = phase
        job["rows_scanned"] = rows
        job["detail"] = detail
        job["bytes_read"] = max(0, int(bytes_read or 0))
        job["total_bytes"] = max(0, int(total_bytes or 0))
        if total_bytes > 0:
            job["percent"] = min(99, max(0, round((bytes_read / total_bytes) * 100)))
        else:
            job["percent"] = None
        job["updated"] = time.time()


def _pcv_for_vin(vin: str) -> str:
    target = _norm(vin)
    rows = 0
    _set_progress(vin, "pcv", 0, "1/2 · Hledám PČV ve výpisu vozidel")
    for row, bytes_read, total_bytes in _csv_rows(VEHICLES_CSV_URL):
        rows += 1
        if rows % 10000 == 0:
            _set_progress(vin, "pcv", rows, "1/2 · Hledám PČV ve výpisu vozidel", bytes_read, total_bytes)
        row_vin = _norm(_field(row, "VIN"))
        if row_vin == target:
            pcv = _field(row, "PČV", "PCV")
            _set_progress(vin, "pcv_found", rows, f"1/2 · PČV nalezeno: {pcv}", bytes_read, total_bytes)
            return pcv
    _set_progress(vin, "pcv_not_found", rows, "1/2 · PČV nebylo nalezeno")
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


def _ownership_for_pcv(vin: str, pcv: str) -> list[dict[str, Any]]:
    current: list[dict[str, Any]] = []
    historical: list[dict[str, Any]] = []
    found_target = False
    rows = 0
    _set_progress(vin, "owner", 0, "2/2 · Hledám vlastníka a provozovatele podle PČV")
    for row, bytes_read, total_bytes in _csv_rows(OWNERS_CSV_URL):
        rows += 1
        if rows % 10000 == 0:
            _set_progress(vin, "owner", rows, "2/2 · Hledám vlastníka a provozovatele podle PČV", bytes_read, total_bytes)
        row_pcv = _field(row, "PČV", "PCV")
        if row_pcv != pcv:
            # Exporty RSV bývají seskupené podle PČV. Po nalezení cílového bloku už nemusíme číst zbytek.
            if found_target:
                _set_progress(vin, "owner_found", rows, "2/2 · Záznam vlastníka/provozovatele nalezen", bytes_read, total_bytes)
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
    subjects = _ownership_for_pcv(vin, pcv)
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


def _api_ownership(vin: str) -> dict[str, Any] | None:
    base = os.getenv("RSV_API_URL", "").strip().rstrip("/")
    if not base:
        return None
    headers = {}
    api_key = os.getenv("RSV_API_KEY", "").strip()
    if api_key:
        headers["X-API-Key"] = api_key
    try:
        response = requests.get(
            f"{base}/api/rsv/vin/{vin}",
            headers=headers,
            timeout=(5, 15),
        )
        if response.status_code == 404:
            return {
                "state": "not_found",
                "message": "VIN nebyl v aktuálním indexu RSV nalezen.",
                "pcv": "",
                "subjects": [],
            }
        response.raise_for_status()
        data = response.json()
        subjects = []
        relation_labels = {
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
        for item in data.get("subjects") or []:
            code = str(item.get("relation_code") or "")
            typ = str(item.get("subject_type_code") or "")
            is_company = typ == "2"
            subjects.append({
                "relation_code": code,
                "relation": relation_labels.get(code, "Vztah k vozidlu"),
                "subject_type_code": typ,
                "subject_type": subject_labels.get(typ, "Subjekt"),
                "current": True,
                "date_from": "",
                "date_to": "",
                "name": str(item.get("name") or "") if is_company else "",
                "ico": str(item.get("ico") or "") if is_company else "",
                "address": "",
            })
        return {
            "state": "ready",
            "message": "Aktuální údaje vlastníka a provozovatele načteny z RSV.",
            "pcv": str(data.get("pcv") or ""),
            "subjects": subjects,
        }
    except Exception as exc:
        print(f"RSV API lookup {vin} failed: {exc.__class__.__name__}: {exc}")
        return {
            "state": "unavailable",
            "message": "Lokální RSV API je momentálně nedostupné.",
            "pcv": "",
            "subjects": [],
        }


def get_ownership(vin: str, start: bool = True) -> dict[str, Any]:
    vin = _norm(vin)
    if len(vin) != 17:
        return {"state": "unavailable", "message": "Neplatné VIN.", "pcv": "", "subjects": []}

    api_payload = _api_ownership(vin)
    if api_payload is not None:
        return api_payload

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
            rows = int(job.get("rows_scanned") or 0)
            phase = str(job.get("phase") or "loading")
            detail = str(job.get("detail") or "Načítám data z RSV…")
            if rows:
                detail += f" · prohledáno {rows:,} záznamů".replace(",", " ")
            return {
                "state": "loading",
                "message": detail,
                "phase": phase,
                "rows_scanned": rows,
                "elapsed_seconds": max(0, int(time.time() - float(job.get("started") or time.time()))),
                "bytes_read": int(job.get("bytes_read") or 0),
                "total_bytes": int(job.get("total_bytes") or 0),
                "percent": job.get("percent"),
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
