from __future__ import annotations

import os
import pathlib
import re
import subprocess

import pymssql

import tirbazar
import uniqa


_ORIGINAL_RUN = tirbazar.subprocess.run


class _FakeTsqlPath:
    def exists(self) -> bool:
        return True

    def __str__(self) -> str:
        return "__WINDOWS_PYMSSQL__"


def _compat_path(value):
    text = str(value).replace("\\", "/")
    if text == "/opt/homebrew/bin/tsql":
        return _FakeTsqlPath()
    return pathlib.Path(value)


def _arg_value(args: list[str], flag: str, default: str = "") -> str:
    try:
        index = args.index(flag)
        return str(args[index + 1])
    except (ValueError, IndexError):
        return default


def _execute_tirbazar_sql(sql: str, args: list[str]) -> str:
    server = os.getenv("TIRBAZAR_SERVER", "192.168.1.100").strip()
    port = int(os.getenv("TIRBAZAR_PORT", "1433"))
    database = os.getenv("TIRBAZAR_DATABASE", "TIRBazar").strip()
    username = _arg_value(args, "-U", os.getenv("TIRBAZAR_USER", "TB").strip())
    password = _arg_value(args, "-P", os.getenv("TIRBAZAR_PASSWORD", ""))

    if not password:
        raise RuntimeError("Chybí TIRBAZAR_PASSWORD. Spusť aplikaci přes START_WEB_WINDOWS.bat.")

    lines: list[str] = []

    connection = pymssql.connect(
        server=server,
        port=port,
        user=username,
        password=password,
        database=database,
        charset="UTF-8",
        login_timeout=15,
        timeout=120,
    )

    try:
        cursor = connection.cursor()
        batches = re.split(r"(?im)^\s*GO\s*$", sql)

        for batch in batches:
            batch = batch.strip()
            if not batch:
                continue

            if batch.lower() == "exit":
                continue

            batch = re.sub(r"(?im)^\s*exit\s*$", "", batch).strip()
            if not batch:
                continue

            cursor.execute(batch)

            if cursor.description:
                for row in cursor.fetchall():
                    if not row or row[0] is None:
                        continue
                    value = row[0]
                    if isinstance(value, bytes):
                        value = value.decode("utf-8", errors="replace")
                    lines.append(str(value))
    finally:
        connection.close()

    return "\n".join(lines) + ("\n" if lines else "")


def _windows_run(args, *pargs, **kwargs):
    argv = [str(item) for item in args] if isinstance(args, (list, tuple)) else [str(args)]
    executable = argv[0].replace("\\", "/") if argv else ""

    if executable == "/usr/bin/security":
        password = os.getenv("TIRBAZAR_PASSWORD", "")
        return subprocess.CompletedProcess(argv, 0 if password else 1, stdout=(password + "\n") if password else "", stderr="" if password else "TIRBAZAR_PASSWORD není nastaveno")

    if executable == "__WINDOWS_PYMSSQL__":
        try:
            stdout = _execute_tirbazar_sql(kwargs.get("input", ""), argv)
            return subprocess.CompletedProcess(argv, 0, stdout=stdout, stderr="")
        except Exception as exc:
            return subprocess.CompletedProcess(argv, 1, stdout="", stderr=str(exc))

    return _ORIGINAL_RUN(args, *pargs, **kwargs)


def _uniqa_secret(service: str) -> str:
    if service == uniqa.USER_SERVICE:
        value = os.getenv("UNIQA_USER", "").strip()
        label = "UNIQA uživatel"
    elif service == uniqa.PASS_SERVICE:
        value = os.getenv("UNIQA_PASSWORD", "")
        label = "UNIQA heslo"
    else:
        value = ""
        label = service

    if not value:
        raise RuntimeError(f"Chybí {label}. Spusť aplikaci přes START_WEB_WINDOWS.bat.")

    return value


def apply_windows_compatibility() -> None:
    tirbazar.Path = _compat_path
    tirbazar.subprocess.run = _windows_run
    uniqa.keychain_read = _uniqa_secret


apply_windows_compatibility()

import app as web_app  # noqa: E402


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "5001"))
    web_app.app.run(
        host="0.0.0.0",
        port=port,
        debug=os.environ.get("FLASK_DEBUG") == "1",
    )
