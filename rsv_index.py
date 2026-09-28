from __future__ import annotations

import csv
import io
import json
import os
import re
import threading
import time
import unicodedata
from typing import Any

import requests

VEHICLES_URL = "https://download.dataovozidlech.cz/vypiszregistru/vypisvozidel"
OWNERS_URL = "https://download.dataovozidlech.cz/vypiszregistru/vlastnikprovozovatelvozidla"

_lock = threading.Lock()
_state: dict[str, Any] = {"state": "idle"}
_worker_lock = threading.Lock()


def _norm(v: Any) -> str:
    text = unicodedata.normalize("NFKD", str(v or ""))
    text = "".join(ch for ch in text if not unicodedata.combining(ch))
    return re.sub(r"[^A-Z0-9]", "", text.upper())


def _field(row: dict[str, Any], *aliases: str) -> str:
    wanted = {_norm(a) for a in aliases}
    for k, v in row.items():
        if _norm(k) in wanted:
            return str(v or "").strip()
    return ""


def _db():
    url = os.getenv("DATABASE_URL", "").strip()
    if not url:
        return None
    import psycopg
    return psycopg.connect(url, connect_timeout=8)


def _init(cur) -> None:
    cur.execute("""
        CREATE TABLE IF NOT EXISTS denni_pov_rsv_index (
            vin TEXT PRIMARY KEY,
            pcv TEXT NOT NULL DEFAULT '',
            subjects JSONB NOT NULL DEFAULT '[]'::jsonb,
            indexed_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
        )
    """)
    cur.execute("CREATE INDEX IF NOT EXISTS denni_pov_rsv_index_pcv_idx ON denni_pov_rsv_index (pcv)")


def _fleet_vins() -> list[str]:
    out: set[str] = set()
    conn = _db()
    if conn is None:
        return []
    with conn:
        with conn.cursor() as cur:
            _init(cur)
            cur.execute("SELECT payload FROM denni_pov_state WHERE id = 1")
            row = cur.fetchone()
    if not row:
        return []
    payload = row[0] if isinstance(row[0], dict) else json.loads(row[0] or "{}")
    for item in payload.get("results") or []:
        vin = _norm((item or {}).get("vin"))
        if len(vin) == 17:
            out.add(vin)
    return sorted(out)


def _rows(url: str):
    r = requests.get(url, stream=True, timeout=(15, 600), headers={
        "Accept": "text/csv,*/*",
        "User-Agent": "DENNI-POV/2.0 (+RSV-index)",
    })
    r.raise_for_status()
    r.raw.decode_content = True
    wrapper = io.TextIOWrapper(r.raw, encoding="utf-8-sig", newline="")
    try:
        yield from csv.DictReader(wrapper)
    finally:
        try:
            wrapper.detach()
        except Exception:
            pass
        r.close()


def _subject(row: dict[str, Any]) -> dict[str, Any] | None:
    if _field(row, "Aktuální").lower() not in {"true", "1", "ano", "yes"}:
        return None
    subject_type = _field(row, "Typ subjektu")
    relation = _field(row, "Vztah k vozidlu")
    result = {
        "relation_code": relation,
        "relation": {"1": "Vlastník", "2": "Provozovatel", "3": "Spoluvlastník", "4": "Nabyvatel"}.get(relation, "Vztah k vozidlu"),
        "subject_type_code": subject_type,
        "subject_type": {"1": "Fyzická osoba", "2": "Právnická osoba", "3": "Neztotožněný subjekt"}.get(subject_type, "Subjekt"),
        "name": "",
        "ico": "",
    }
    if subject_type == "2":
        result["name"] = _field(row, "Název", "Nazev")
        result["ico"] = _field(row, "IČO", "ICO")
    return result


def _progress(phase: str, rows: int, matched: int, total: int, message: str) -> None:
    with _lock:
        _state.update({
            "state": "loading",
            "phase": phase,
            "rows_scanned": rows,
            "matched": matched,
            "target_count": total,
            "message": message,
            "updated": time.time(),
        })


def _save(pcv_by_vin: dict[str, str], subjects_by_pcv: dict[str, list[dict[str, Any]]]) -> None:
    conn = _db()
    if conn is None:
        return
    with conn:
        with conn.cursor() as cur:
            _init(cur)
            for vin, pcv in pcv_by_vin.items():
                cur.execute("""
                    INSERT INTO denni_pov_rsv_index (vin, pcv, subjects, indexed_at)
                    VALUES (%s, %s, %s::jsonb, NOW())
                    ON CONFLICT (vin) DO UPDATE SET
                        pcv = EXCLUDED.pcv,
                        subjects = EXCLUDED.subjects,
                        indexed_at = NOW()
                """, (vin, pcv, json.dumps(subjects_by_pcv.get(pcv, []), ensure_ascii=False)))


def _worker(extra_vin: str = "") -> None:
    if not _worker_lock.acquire(blocking=False):
        return
    started = time.time()
    try:
        targets = set(_fleet_vins())
        extra_vin = _norm(extra_vin)
        if len(extra_vin) == 17:
            targets.add(extra_vin)
        if not targets:
            raise RuntimeError("Nenalezeny VINy pro RSV index.")

        pcv_by_vin: dict[str, str] = {}
        rows = 0
        _progress("vehicles", 0, 0, len(targets), "1/2 · Vytvářím VIN → PČV index")
        for row in _rows(VEHICLES_URL):
            rows += 1
            vin = _norm(_field(row, "VIN"))
            if vin in targets:
                pcv = _field(row, "PČV", "PCV")
                if pcv:
                    pcv_by_vin[vin] = pcv
            if rows % 10000 == 0:
                _progress("vehicles", rows, len(pcv_by_vin), len(targets), "1/2 · Vytvářím VIN → PČV index")
            if len(pcv_by_vin) == len(targets):
                break

        target_pcvs = set(pcv_by_vin.values())
        subjects_by_pcv = {p: [] for p in target_pcvs}
        found_pcvs: set[str] = set()
        rows = 0
        _progress("owners", 0, 0, len(target_pcvs), "2/2 · Načítám vlastníky/provozovatele")
        for row in _rows(OWNERS_URL):
            rows += 1
            pcv = _field(row, "PČV", "PCV")
            if pcv in target_pcvs:
                found_pcvs.add(pcv)
                subject = _subject(row)
                if subject:
                    subjects_by_pcv.setdefault(pcv, []).append(subject)
            if rows % 10000 == 0:
                _progress("owners", rows, len(found_pcvs), len(target_pcvs), "2/2 · Načítám vlastníky/provozovatele")

        _save(pcv_by_vin, subjects_by_pcv)
        elapsed = int(time.time() - started)
        with _lock:
            _state.update({
                "state": "ready",
                "phase": "done",
                "rows_scanned": rows,
                "matched": len(found_pcvs),
                "target_count": len(targets),
                "message": f"RSV index hotov · {len(pcv_by_vin)}/{len(targets)} VIN · {elapsed} s",
                "finished": time.time(),
            })
    except Exception as exc:
        with _lock:
            _state.update({"state": "unavailable", "phase": "error", "message": f"RSV index selhal: {exc.__class__.__name__}: {exc}"})
    finally:
        _worker_lock.release()


def start_refresh(vin: str = "") -> dict[str, Any]:
    with _lock:
        if _state.get("state") == "loading":
            return dict(_state)
        _state.clear()
        _state.update({"state": "loading", "phase": "starting", "rows_scanned": 0, "matched": 0, "target_count": 0, "message": "Připravuji RSV index…", "started": time.time()})
    threading.Thread(target=_worker, args=(vin,), daemon=True, name="rsv-index-refresh").start()
    return status()


def status() -> dict[str, Any]:
    with _lock:
        out = dict(_state)
    if out.get("started"):
        out["elapsed_seconds"] = max(0, int(time.time() - float(out["started"])))
    return out


def lookup(vin: str) -> dict[str, Any] | None:
    vin = _norm(vin)
    if len(vin) != 17:
        return None
    try:
        conn = _db()
        if conn is None:
            return None
        with conn:
            with conn.cursor() as cur:
                _init(cur)
                cur.execute("SELECT pcv, subjects, indexed_at FROM denni_pov_rsv_index WHERE vin = %s", (vin,))
                row = cur.fetchone()
        if not row:
            return None
        subjects = row[1] if isinstance(row[1], list) else json.loads(row[1] or "[]")
        return {
            "state": "ready",
            "message": "Načteno z lokálního RSV indexu na Renderu.",
            "pcv": str(row[0] or ""),
            "subjects": subjects,
            "cached": True,
            "fetched_at": row[2].isoformat() if row[2] else "",
        }
    except Exception:
        return None
