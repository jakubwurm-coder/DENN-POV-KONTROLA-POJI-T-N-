from __future__ import annotations

import os
import re
import subprocess
from collections import defaultdict
from pathlib import Path

from config import Config
from models import TirVehicle
from normalize import normalize_spz, normalize_vin


KEYCHAIN_SERVICE = "UNIQA_CHECKER_TIRBAZAR"
KEYCHAIN_ACCOUNT = "TB"

FORBIDDEN_SQL = (
    "INSERT ",
    "UPDATE ",
    "DELETE ",
    "ALTER ",
    "DROP ",
    "TRUNCATE ",
    "MERGE ",
    "CREATE ",
)

CONTROL_POV_STATE_VALUES = {
    "VYKOUPENÉ",
    "VYKOUPENE",
    "REZERVOVANÉ",
    "REZERVOVANE",
}

EXCLUDED_POV_STATE_VALUES = {
    "PRONAJATÉ",
    "PRONAJATE",
    "NEPŘÍTOMNÉ",
    "NEPRITOMNE",
    "VOLNÉ",
    "VOLNE",
    "PARKOVANÉ",
    "PARKOVANE",
    "PARKOVÁNÍ UKONČENO",
    "PARKOVANI UKONCENO",
    "PRODANÉ",
    "PRODANE",
    "VRÁCENÉ Z KOMISE",
    "VRACENE Z KOMISE",
    "V KOMISI",
}

# Krajské písmeno v běžné české registrační značce.
# Příklady: 6ST9595, 9AK7158, 7AC6140, 1TV1811.
CZECH_REGION_LETTERS = "ABCEHJKLM PSTUZ".replace(" ", "")
CZECH_STANDARD_SPZ_RE = re.compile(
    rf"^[0-9][{CZECH_REGION_LETTERS}][A-Z0-9][0-9]{{4}}$"
)


def _normalize_state(value: str) -> str:
    return " ".join(str(value or "").strip().upper().split())


def _is_czech_country(value: str) -> bool:
    return _normalize_state(value) == "A"


def _is_czech_spz(value: str) -> bool:
    spz = normalize_spz(value)
    return bool(CZECH_STANDARD_SPZ_RE.fullmatch(spz))


def _is_czech_for_pov(vehicle: TirVehicle) -> bool:
    country = _normalize_state(vehicle.zeme_puvodu)

    # Primární pravidlo: kód země původu A.
    if country == "A":
        return True

    # Výjimka: země původu není vyplněná, ale vozidlo má českou SPZ.
    # Pokud je vyplněn jiný kód země, SPZ tuto podmínku nepřebíjí.
    if not country and _is_czech_spz(vehicle.spz):
        return True

    return False


def _is_control_pov_state(value: str) -> bool:
    return _normalize_state(value) in CONTROL_POV_STATE_VALUES


def _is_ignored_pov_state(value: str) -> bool:
    # POV se kontroluje pouze u Vykoupené / Rezervované.
    return not _is_control_pov_state(value)


def _requires_pov_check(vehicle: TirVehicle) -> bool:
    return (
        _is_czech_for_pov(vehicle)
        and bool(vehicle.vin)
        and _is_control_pov_state(vehicle.stav)
        and not bool(vehicle.datum_prodeje)
    )


def get_password() -> str:
    result = subprocess.run(
        [
            "/usr/bin/security",
            "find-generic-password",
            "-a",
            KEYCHAIN_ACCOUNT,
            "-s",
            KEYCHAIN_SERVICE,
            "-w",
        ],
        capture_output=True,
        text=True,
        timeout=10,
    )

    if result.returncode != 0:
        raise RuntimeError("SQL heslo nebylo nalezeno v macOS Klíčence.")

    value = result.stdout.strip()
    if not value:
        raise RuntimeError("SQL heslo v macOS Klíčence je prázdné.")

    return value


def validate_read_only(sql: str) -> None:
    upper = sql.upper()
    for command in FORBIDDEN_SQL:
        if command in upper:
            raise RuntimeError(f"Bezpečnostní blokace SQL: {command.strip()}")


def build_sql() -> str:
    # DŮLEŽITÉ:
    # Interně načítáme VŠECHNA nesmazaná vozidla, ne jen kód A.
    # Je to nutné, aby VIN existující v TIRBazar (např. V komisi, cizina,
    # Pronajaté apod.) nikdy nevytvořil falešné "NAVÍC V UNIQA".
    # Samotný POV filtr se aplikuje až v Pythonu přes _requires_pov_check().
    return r"""
USE TIRBazar;
GO

SET NOCOUNT ON;
GO

SELECT
    '__TOTAL__|' + CAST(COUNT(*) AS VARCHAR(20))
FROM dbo.Vozidlo
WHERE GCRecord IS NULL;
GO

SELECT
    '__CODE_A__|' + CAST(COUNT(*) AS VARCHAR(20))
FROM dbo.Vozidlo v
WHERE
    v.GCRecord IS NULL
    AND UPPER(LTRIM(RTRIM(ISNULL(v.ZemePuvoduKod, '')))) = 'A';
GO

SELECT
    '__WITHOUT_RZ__|' + CAST(COUNT(*) AS VARCHAR(20))
FROM dbo.Vozidlo v
WHERE
    v.GCRecord IS NULL
    AND UPPER(LTRIM(RTRIM(ISNULL(v.ZemePuvoduKod, '')))) = 'A'
    AND LTRIM(RTRIM(ISNULL(
        CASE
            WHEN v.NovaRegistracniZnacka IS NOT NULL
                 AND LTRIM(RTRIM(v.NovaRegistracniZnacka)) <> ''
            THEN v.NovaRegistracniZnacka
            ELSE v.RegistracniZnacka
        END,
        ''
    ))) = '';
GO

SELECT
    '__WITHOUT_VIN__|' + CAST(COUNT(*) AS VARCHAR(20))
FROM dbo.Vozidlo v
WHERE
    v.GCRecord IS NULL
    AND LTRIM(RTRIM(ISNULL(v.VIN, ''))) = '';
GO

SELECT
    '__ROW__|' +
    CAST(v.OID AS VARCHAR(20)) + '|' +
    ISNULL(REPLACE(REPLACE(LTRIM(RTRIM(v.VIN)), CHAR(13), ''), CHAR(10), ''), '') + '|' +
    ISNULL(
        REPLACE(
            REPLACE(
                LTRIM(RTRIM(
                    CASE
                        WHEN v.NovaRegistracniZnacka IS NOT NULL
                             AND LTRIM(RTRIM(v.NovaRegistracniZnacka)) <> ''
                        THEN v.NovaRegistracniZnacka
                        ELSE v.RegistracniZnacka
                    END
                )),
                CHAR(13),
                ''
            ),
            CHAR(10),
            ''
        ),
        ''
    ) + '|' +
    ISNULL(REPLACE(REPLACE(REPLACE(LTRIM(RTRIM(v.Stav)), CHAR(13), ' '), CHAR(10), ' '), '|', '/'), '') + '|' +
    ISNULL(CONVERT(VARCHAR(19), normalni_vykup.DatumVykupu, 120), '') + '|' +
    ISNULL(CONVERT(VARCHAR(19), komise_vykup.DatumVykupu, 120), '') + '|' +
    ISNULL(CONVERT(VARCHAR(19), prodej.DatumProdeje, 120), '') + '|' +
    ISNULL(REPLACE(REPLACE(LTRIM(RTRIM(v.ZemePuvoduKod)), CHAR(13), ''), CHAR(10), ''), '') + '|' +
    ISNULL(REPLACE(REPLACE(REPLACE(LTRIM(RTRIM(v.Poznamky)), CHAR(13), ' '), CHAR(10), ' '), '|', '/'), '')
FROM dbo.Vozidlo v
OUTER APPLY (
    SELECT MAX(vv.DatumVykupu) AS DatumVykupu
    FROM dbo.VykupVozidla vv
    WHERE vv.Vozidlo = v.OID
      AND vv.DatumVykupu IS NOT NULL
      AND vv.GCRecord IS NULL
) normalni_vykup
OUTER APPLY (
    SELECT MAX(vk.DatumVykupu) AS DatumVykupu
    FROM dbo.VykoupeniZKomise vk
    WHERE vk.Vozidlo = v.OID
      AND vk.DatumVykupu IS NOT NULL
      AND vk.GCRecord IS NULL
) komise_vykup
OUTER APPLY (
    SELECT MAX(p.DatumProdeje) AS DatumProdeje
    FROM dbo.Prodej p
    WHERE p.Vozidlo = v.OID
      AND p.DatumProdeje IS NOT NULL
      AND p.GCRecord IS NULL
) prodej
WHERE
    v.GCRecord IS NULL
ORDER BY v.OID;
GO

SELECT '__FINISHED__';
GO

exit
"""


def load_tirbazar_vehicles(
    config: Config,
) -> tuple[list[TirVehicle], list[list[TirVehicle]]]:
    sql = build_sql()
    validate_read_only(sql)

    password = get_password()

    base_dir = Path(__file__).resolve().parent
    freetds_conf = base_dir / "freetds.conf"
    tsql = Path("/opt/homebrew/bin/tsql")

    if not freetds_conf.exists():
        raise RuntimeError(f"Chybí {freetds_conf}")
    if not tsql.exists():
        raise RuntimeError(f"Chybí {tsql}")

    env = os.environ.copy()
    env["FREETDSCONF"] = str(freetds_conf)
    env["TDSVER"] = "7.2"

    print()
    print("Připojuji se READ-ONLY k TIRBazar...")
    print("Interně načítám všechna nesmazaná vozidla kvůli kontrole VIN v UNIQA.")
    print("POV kontrola: Vykoupené/Rezervované + VIN + (kód A NEBO prázdný kód a česká SPZ).")
    print("U kódu A není SPZ povinná - bez SPZ se kontroluje podle VIN.")
    print("Pronajaté, Nepřítomné, Volné, Parkované, Parkování ukončeno,")
    print("Prodané, Vrácené z komise, V komisi a všechny ostatní stavy se nekontrolují.")
    print()

    try:
        result = subprocess.run(
            [str(tsql), "-S", "tirbazar", "-U", config.username, "-P", password],
            input=sql,
            capture_output=True,
            text=True,
            env=env,
            timeout=120,
        )
    finally:
        password = ""

    stdout = result.stdout or ""
    stderr = result.stderr or ""

    (base_dir / "tsql_last_output.txt").write_text(
        stdout + "\n\n--- STDERR ---\n" + stderr,
        encoding="utf-8",
    )

    if result.returncode != 0:
        raise RuntimeError(stderr.strip() or stdout.strip())

    total = 0
    code_a_sql = 0
    without_spz_sql = 0
    without_vin_sql = 0
    raw_rows: list[TirVehicle] = []

    for original in stdout.splitlines():
        line = original.strip()

        if "__TOTAL__|" in line:
            try:
                total = int(line[line.find("__TOTAL__|"):].split("|", 1)[1].strip())
            except Exception:
                pass

        if "__CODE_A__|" in line:
            try:
                code_a_sql = int(line[line.find("__CODE_A__|"):].split("|", 1)[1].strip())
            except Exception:
                pass

        if "__WITHOUT_RZ__|" in line:
            try:
                without_spz_sql = int(line[line.find("__WITHOUT_RZ__|"):].split("|", 1)[1].strip())
            except Exception:
                pass

        if "__WITHOUT_VIN__|" in line:
            try:
                without_vin_sql = int(line[line.find("__WITHOUT_VIN__|"):].split("|", 1)[1].strip())
            except Exception:
                pass

        if "__ROW__|" not in line:
            continue

        value = line[line.find("__ROW__|"):]
        parts = value.split("|", 9)
        if len(parts) != 10:
            continue

        (
            _, oid_text, vin, spz, stav, datum_vykupu,
            datum_vykupu_komise, datum_prodeje, zeme_puvodu, poznamky,
        ) = parts

        try:
            oid = int(oid_text.strip())
        except ValueError:
            continue

        normal_purchase = datum_vykupu.strip()
        commission_purchase = datum_vykupu_komise.strip()
        effective_purchase = normal_purchase or commission_purchase

        raw_rows.append(
            TirVehicle(
                oid=oid,
                vin=normalize_vin(vin),
                spz=normalize_spz(spz),
                zeme_puvodu=zeme_puvodu.strip(),
                stav=stav.strip(),
                datum_vykupu=effective_purchase,
                datum_prodeje=datum_prodeje.strip(),
                poznamky=poznamky.strip(),
            )
        )

    if not raw_rows:
        raise RuntimeError("Z TIRBazar nebyla načtena žádná vozidla.")

    without_vin = [v for v in raw_rows if not v.vin]
    comparable = [v for v in raw_rows if v.vin]

    groups: dict[str, list[TirVehicle]] = defaultdict(list)
    for vehicle in comparable:
        groups[vehicle.vin].append(vehicle)

    vehicles: list[TirVehicle] = []
    duplicates: list[list[TirVehicle]] = []

    for _, group in groups.items():
        group = sorted(group, key=lambda x: x.oid, reverse=True)
        vehicles.append(group[0])
        if len(group) > 1:
            duplicates.append(group)

    vehicles.sort(key=lambda x: x.oid)

    control = [v for v in vehicles if _requires_pov_check(v)]
    purchased = [
        v for v in control
        if _normalize_state(v.stav) in {"VYKOUPENÉ", "VYKOUPENE"}
    ]
    reserved = [
        v for v in control
        if _normalize_state(v.stav) in {"REZERVOVANÉ", "REZERVOVANE"}
    ]
    control_without_spz = [v for v in control if not v.spz]
    blank_country_czech_spz = [
        v for v in control
        if not _normalize_state(v.zeme_puvodu) and _is_czech_spz(v.spz)
    ]
    sold = [
        v for v in vehicles
        if bool(v.datum_prodeje) or _normalize_state(v.stav) in {"PRODANÉ", "PRODANE"}
    ]
    ignored = [v for v in vehicles if v not in control]

    print()
    print("TIRBazar LIVE:")
    print("Celkem nesmazaných záznamů:", total)
    print("Záznamů s kódem země A:", code_a_sql)
    print("Kód A bez registrační značky:", without_spz_sql)
    print("Bez VIN - nelze porovnat podle VIN:", max(without_vin_sql, len(without_vin)))
    print("Unikátních známých VIN v TIRBazar:", len(vehicles))
    print("Duplicitních VIN skupin:", len(duplicates))
    print("Vykoupené ke kontrole:", len(purchased))
    print("Rezervované ke kontrole:", len(reserved))
    print("Prázdný kód země + česká SPZ ke kontrole:", len(blank_country_czech_spz))
    print("Ke kontrole bez SPZ (kód A, podle VIN):", len(control_without_spz))
    print("Prodané - ignorováno:", len(sold))
    print("Ostatní stavy / jiné země - ignorováno:", len(ignored))
    print("Aktivních ke kontrole celkem:", len(control))
    print()

    return vehicles, duplicates
