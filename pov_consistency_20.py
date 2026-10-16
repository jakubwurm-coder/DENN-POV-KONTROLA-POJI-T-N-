"""Twenty sequential DENNI POV consistency checks, three-minute spacing.

Run in a separate worker (not a Gunicorn request). Requires POV_BASE_URL and
POV_MCP_TOKEN in the worker environment. Never connects directly to SQL.
"""
import csv
import json
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import requests

BASE = os.environ["POV_BASE_URL"].rstrip("/")
TOKEN = os.environ["POV_MCP_TOKEN"]
COUNT = int(os.getenv("POV_TEST_COUNT", "20"))
PAUSE = int(os.getenv("POV_TEST_PAUSE_SECONDS", "180"))
TIMEOUT = int(os.getenv("POV_TEST_TIMEOUT_SECONDS", "600"))
OUT = Path(os.getenv("POV_TEST_OUTPUT", "pov_consistency_results"))
OUT.mkdir(parents=True, exist_ok=True)
session = requests.Session()
endpoint = f"{BASE}/mcp/{TOKEN}"
fields = ["active", "ok_total", "missing", "problems", "extra_allianz",
          "extra_uniqa", "double_insured", "deposit_insured", "sold_uniqa",
          "unverified", "absent_insured", "absent_uninsured", "resolved_active"]

def call(name, arguments=None):
    response = session.post(endpoint, json={"jsonrpc": "2.0", "id": 1,
        "method": "tools/call", "params": {"name": name, "arguments": arguments or {}}},
        timeout=20)
    response.raise_for_status()
    payload = response.json()
    if "error" in payload:
        raise RuntimeError(str(payload["error"]))
    result = payload["result"]
    data = result.get("structuredContent")
    if data is None:
        data = json.loads(result["content"][0]["text"])
    return data

rows = []
baseline = None
for index in range(1, COUNT + 1):
    started = datetime.now(timezone.utc).isoformat()
    record = {"run": index, "requested_at_utc": started}
    try:
        # If a different check is running, wait for it instead of claiming its result.
        deadline = time.monotonic() + TIMEOUT
        while True:
            try:
                result = call("get_insurance_status")
                if result.get("ok") and result.get("request_id"):
                    break
                if not result.get("busy"):
                    raise RuntimeError(str(result))
            except Exception as exc:
                if "Kontrola už probíhá" not in str(exc):
                    raise
            if time.monotonic() > deadline:
                raise TimeoutError("Timed out waiting for available agent")
            time.sleep(10)
        request_id = result["request_id"]
        record["request_id"] = request_id
        deadline = time.monotonic() + TIMEOUT
        while time.monotonic() < deadline:
            status = call("get_check_result", {"request_id": request_id})
            if status.get("fresh_check_completed"):
                break
            if status.get("error"):
                raise RuntimeError(status["error"])
            time.sleep(5)
        else:
            raise TimeoutError("Check did not finish within timeout")
        summary = status.get("summary") or {}
        record.update({field: summary.get(field) for field in fields})
        record["finished_at"] = status.get("generated_at")
        record["status"] = "OK"
        problems = sorted((str(p.get("vin")), str(p.get("status_raw")))
                          for p in status.get("problems") or [])
        record["problem_vins"] = json.dumps(problems, ensure_ascii=False)
        fingerprint = json.dumps({"summary": {field: summary.get(field) for field in fields},
                                  "problems": problems}, sort_keys=True, ensure_ascii=False)
        if baseline is None:
            baseline = fingerprint
        record["same_as_first"] = fingerprint == baseline
        with (OUT / f"run_{index:02d}.json").open("w", encoding="utf-8") as file:
            json.dump(status, file, ensure_ascii=False, indent=2)
    except Exception as exc:
        record["status"] = "ERROR"
        record["error"] = str(exc)
        record["same_as_first"] = False
    rows.append(record)
    with (OUT / "summary.csv").open("w", encoding="utf-8-sig", newline="") as file:
        writer = csv.DictWriter(file, fieldnames=["run", "requested_at_utc",
            "request_id", "finished_at", "status", *fields, "same_as_first",
            "problem_vins", "error"], extrasaction="ignore", delimiter=";")
        writer.writeheader()
        writer.writerows(rows)
    print(json.dumps(record, ensure_ascii=False), flush=True)
    if index < COUNT:
        time.sleep(PAUSE)
sys.exit(0 if all(r["status"] == "OK" for r in rows) else 1)
