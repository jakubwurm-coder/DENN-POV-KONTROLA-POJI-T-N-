from __future__ import annotations

import importlib.util
import os
import socket
from pathlib import Path

REQUIRED_MODULES = [
    "allianz",
    "compare",
    "config",
    "report",
    "tirbazar",
    "uniqa",
]


def check_modules() -> dict[str, bool]:
    return {name: importlib.util.find_spec(name) is not None for name in REQUIRED_MODULES}


def check_tirbazar_host(host: str = "192.168.1.100", port: int = 1433, timeout: float = 2.0) -> tuple[bool, str]:
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True, f"{host}:{port} je dostupné"
    except Exception as exc:
        return False, f"{host}:{port} není dostupné: {exc}"


def main() -> int:
    print("=" * 66)
    print("DENNÍ POV – PREFLIGHT")
    print("=" * 66)
    print()

    modules = check_modules()
    for name, ok in modules.items():
        print(f"{'OK' if ok else 'CHYBÍ':6} {name}.py")

    print()
    host = os.environ.get("TIRBAZAR_HOST", "192.168.1.100")
    port = int(os.environ.get("TIRBAZAR_PORT", "1433"))
    ok_sql, detail = check_tirbazar_host(host, port)
    print(f"{'OK' if ok_sql else 'CHYBA':6} TIRBazar síť: {detail}")

    print()
    freetds = os.environ.get("FREETDSCONF")
    if freetds:
        print(f"INFO   FREETDSCONF={freetds} ({'existuje' if Path(freetds).exists() else 'soubor nenalezen'})")
    else:
        print("INFO   FREETDSCONF není nastavené")

    print(f"INFO   TDSVER={os.environ.get('TDSVER', 'nenastaveno')}")
    print()

    if not all(modules.values()):
        print("Webová vrstva je připravená, ale pro ostrou kontrolu musí být ve stejné složce původní moduly UNIQA_CHECKER.")
        return 2
    if not ok_sql:
        print("Aplikace může běžet, ale TIRBazar nebude dostupný, dokud nebude server dosažitelný ze stroje, kde web běží.")
        return 3

    print("PREFLIGHT OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
