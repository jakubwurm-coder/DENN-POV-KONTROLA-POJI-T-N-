from __future__ import annotations

import os
import pathlib
import re
import subprocess
import tempfile

import tirbazar
import uniqa


_ORIGINAL_RUN = tirbazar.subprocess.run


class _FakeTsqlPath:
    def exists(self) -> bool:
        return True

    def __str__(self) -> str:
        return "__WINDOWS_DOTNET_SQLCLIENT__"


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
    database = os.getenv("TIRBAZAR_DATABASE", "TIRBazar").strip()
    username = _arg_value(args, "-U", os.getenv("TIRBAZAR_USER", "TB").strip())
    password = _arg_value(args, "-P", os.getenv("TIRBAZAR_PASSWORD", ""))

    if not password:
        raise RuntimeError(
            "Chybi TIRBAZAR_PASSWORD. Spust aplikaci pres START_WEB_WINDOWS.bat."
        )

    # Windows version deliberately uses System.Data.SqlClient from .NET,
    # because the original TIRBazar application uses the same provider.
    # This avoids FreeTDS / DB-Lib compatibility differences.
    powershell = r'''
$ErrorActionPreference = "Stop"
[Console]::OutputEncoding = New-Object System.Text.UTF8Encoding($false)

$server = $env:TIRBAZAR_SERVER
if ([string]::IsNullOrWhiteSpace($server)) { $server = "192.168.1.100" }

$database = $env:TIRBAZAR_DATABASE
if ([string]::IsNullOrWhiteSpace($database)) { $database = "TIRBazar" }

$user = $env:TIRBAZAR_USER
if ([string]::IsNullOrWhiteSpace($user)) { $user = "TB" }

$password = $env:TIRBAZAR_PASSWORD
if ([string]::IsNullOrWhiteSpace($password)) { throw "TIRBAZAR_PASSWORD neni nastaveno." }

$builder = New-Object System.Data.SqlClient.SqlConnectionStringBuilder
$builder["Data Source"] = $server
$builder["Initial Catalog"] = $database
$builder["User ID"] = $user
$builder["Password"] = $password
$builder["Connect Timeout"] = 15
$builder["Application Name"] = "DENNI POV KONTROLA"

$conn = New-Object System.Data.SqlClient.SqlConnection($builder.ConnectionString)
$conn.Open()

try {
    $sql = [System.IO.File]::ReadAllText($env:DENNI_POV_SQL_FILE, [System.Text.Encoding]::UTF8)
    $batches = [System.Text.RegularExpressions.Regex]::Split($sql, '(?im)^\s*GO\s*$')

    foreach ($batchRaw in $batches) {
        $batch = [System.Text.RegularExpressions.Regex]::Replace($batchRaw, '(?im)^\s*exit\s*$', '').Trim()
        if ([string]::IsNullOrWhiteSpace($batch)) { continue }

        $cmd = $conn.CreateCommand()
        $cmd.CommandText = $batch
        $cmd.CommandTimeout = 120

        $reader = $cmd.ExecuteReader()
        try {
            while ($reader.Read()) {
                if (-not $reader.IsDBNull(0)) {
                    [Console]::Out.WriteLine($reader.GetValue(0).ToString())
                }
            }
        }
        finally {
            $reader.Close()
        }
    }
}
finally {
    $conn.Close()
}
'''

    env = os.environ.copy()
    env["TIRBAZAR_SERVER"] = server
    env["TIRBAZAR_DATABASE"] = database
    env["TIRBAZAR_USER"] = username
    env["TIRBAZAR_PASSWORD"] = password

    temp_path = ""
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            suffix=".sql",
            delete=False,
        ) as handle:
            handle.write(sql)
            temp_path = handle.name

        env["DENNI_POV_SQL_FILE"] = temp_path

        result = subprocess.run(
            [
                "powershell.exe",
                "-NoProfile",
                "-ExecutionPolicy",
                "Bypass",
                "-Command",
                powershell,
            ],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            env=env,
            timeout=180,
        )
    finally:
        if temp_path:
            try:
                os.remove(temp_path)
            except OSError:
                pass
        password = ""

    if result.returncode != 0:
        detail = (result.stderr or result.stdout or "").strip()
        raise RuntimeError(
            "Windows .NET SqlClient se nepripojil k TIRBazar SQL. " + detail
        )

    return result.stdout or ""


def _windows_run(args, *pargs, **kwargs):
    argv = [str(item) for item in args] if isinstance(args, (list, tuple)) else [str(args)]
    executable = argv[0].replace("\\", "/") if argv else ""

    if executable == "/usr/bin/security":
        password = os.getenv("TIRBAZAR_PASSWORD", "")
        return subprocess.CompletedProcess(
            argv,
            0 if password else 1,
            stdout=(password + "\n") if password else "",
            stderr="" if password else "TIRBAZAR_PASSWORD neni nastaveno",
        )

    if executable == "__WINDOWS_DOTNET_SQLCLIENT__":
        try:
            stdout = _execute_tirbazar_sql(kwargs.get("input", ""), argv)
            return subprocess.CompletedProcess(argv, 0, stdout=stdout, stderr="")
        except Exception as exc:
            return subprocess.CompletedProcess(argv, 1, stdout="", stderr=str(exc))

    return _ORIGINAL_RUN(args, *pargs, **kwargs)


def _uniqa_secret(service: str) -> str:
    if service == uniqa.USER_SERVICE:
        value = os.getenv("UNIQA_USER", "").strip()
        label = "UNIQA uzivatel"
    elif service == uniqa.PASS_SERVICE:
        value = os.getenv("UNIQA_PASSWORD", "")
        label = "UNIQA heslo"
    else:
        value = ""
        label = service

    if not value:
        raise RuntimeError(
            f"Chybi {label}. Spust aplikaci pres START_WEB_WINDOWS.bat."
        )

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
