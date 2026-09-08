from __future__ import annotations

import argparse
import os
import platform
import sys
import time
from typing import Any

import requests

CLOUD_URL = os.getenv("DENNI_POV_CLOUD_URL", "https://denni-pov-kontrola.onrender.com").rstrip("/")
SYNC_TOKEN = os.getenv(
    "DENNI_POV_SYNC_TOKEN",
    "OPYnDYQG4X5oVQPsKPE7qB25pw1YV9KUZWzFXcFrygfSvx1aKhkH_-MunoSx7Zof",
)
POLL_SECONDS = int(os.getenv("DENNI_POV_POLL_SECONDS", "15"))
AUTO_SYNC_SECONDS = int(os.getenv("DENNI_POV_AUTO_SYNC_SECONDS", "900"))


def _load_local_app():
    if os.name == "nt":
        import windows_bootstrap

        return windows_bootstrap.web_app

    import local_app

    return local_app


def _headers() -> dict[str, str]:
    return {
        "Authorization": f"Bearer {SYNC_TOKEN}",
        "Content-Type": "application/json",
        "User-Agent": f"DENNI-POV-Agent/{platform.system()}",
    }


def _reset_for_run(local_app) -> None:
    with local_app._lock:
        local_app._state["running"] = True
        local_app._state["started_at"] = local_app._now()
        local_app._state["finished_at"] = None
        local_app._state["error"] = None
        local_app._state["results"] = []
        local_app._state["last_csv"] = None
        local_app._state["sources"] = {
            "tirbazar": {
                "state": "loading",
                "status": "Čekám…",
                "detail": "SQL Server / pouze čtení",
            },
            "uniqa": {
                "state": "idle",
                "status": "Čekám…",
                "detail": "AIV / Denní POV / Aktivní",
            },
            "allianz": {
                "state": "idle",
                "status": "Čekám…",
                "detail": "Flotilové PDF",
            },
        }


def run_local_check() -> dict[str, Any]:
    local_app = _load_local_app()
    _reset_for_run(local_app)
    local_app._run_check_worker()
    snapshot = local_app._snapshot()
    snapshot["agent"] = {
        "computer": platform.node(),
        "system": platform.system(),
    }
    return snapshot


def push_snapshot(snapshot: dict[str, Any]) -> None:
    response = requests.post(
        f"{CLOUD_URL}/api/sync",
        headers=_headers(),
        json=snapshot,
        timeout=45,
    )
    response.raise_for_status()


def get_command() -> dict[str, Any] | None:
    response = requests.get(
        f"{CLOUD_URL}/api/agent/command",
        headers=_headers(),
        timeout=20,
    )
    response.raise_for_status()
    payload = response.json()
    command = payload.get("command")
    return command if isinstance(command, dict) else None


def run_and_sync(reason: str) -> None:
    print()
    print("==============================================")
    print(" DENNI POV - ONLINE SYNCHRONIZACE")
    print("==============================================")
    print(f"Důvod kontroly: {reason}")
    print("Načítám TIRBazar → UNIQA → Allianz → depozit...")
    snapshot = run_local_check()
    if snapshot.get("error"):
        print("Kontrola skončila chybou:", snapshot.get("error"))
    else:
        print("Kontrola dokončena. Odesílám výsledek na Render...")
    push_snapshot(snapshot)
    print("✅ Online web byl aktualizován:", CLOUD_URL)


def main() -> int:
    parser = argparse.ArgumentParser(description="DENNI POV kancelářský agent pro Render")
    parser.add_argument("--once", action="store_true", help="Provede jednu kontrolu, synchronizuje a skončí.")
    parser.add_argument("--no-initial", action="store_true", help="Po startu neprovádí okamžitou kontrolu.")
    args = parser.parse_args()

    print("DENNI POV - kancelářský agent")
    print("Online web:", CLOUD_URL)
    print("Tento proces musí běžet na počítači, který vidí TIRBazar SQL a má přístup do UNIQA.")

    if args.once:
        run_and_sync("ruční jednorázová synchronizace")
        return 0

    last_command_id = ""
    next_auto = time.monotonic()
    if args.no_initial:
        next_auto += AUTO_SYNC_SECONDS

    while True:
        try:
            command = get_command()
            command_id = str((command or {}).get("id", ""))
            if command_id and command_id != last_command_id:
                last_command_id = command_id
                run_and_sync("požadavek z online webu")
                next_auto = time.monotonic() + AUTO_SYNC_SECONDS
            elif time.monotonic() >= next_auto:
                run_and_sync("automatická pravidelná aktualizace")
                next_auto = time.monotonic() + AUTO_SYNC_SECONDS
        except KeyboardInterrupt:
            print("\nAgent ukončen.")
            return 0
        except Exception as exc:
            print("⚠️ Synchronizace se nepodařila:", exc)

        time.sleep(max(5, POLL_SECONDS))


if __name__ == "__main__":
    sys.exit(main())
