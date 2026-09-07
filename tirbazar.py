from __future__ import annotations

import os
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


def _is_commission_state(value: str) -> bool:
    return " ".join(str(value or "").strip().upper().split()) == "V KOMISI"


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
        raise RuntimeError(
            "SQL heslo nebylo nalezeno v macOS Klíčence."
        )

    value = result.stdout.strip()

    if not value:
        raise RuntimeError(
            "SQL heslo v macOS Klíčence je prázdné."
        )

    return value


def validate_read_only(sql: str) -> None:
    upper = sql.upper()

    for command in FORBIDDEN_SQL:
        if command in upper:
            raise RuntimeError(
                f"Bezpečnostní blokace SQL: {command.strip()}"
            )


def build_sql() -> str:
    return r"""
USE TIRBazar;
GO

SET NOCOUNT ON;
GO

SELECT
    '__TOTAL__|' +
    CAST(COUNT(*) AS VARCHAR(20))
FROM dbo.Vozidlo
WHERE GCRecord IS NULL;
GO

SELECT
    '__ROW__|' +

    CAST(v.OID AS VARCHAR(20)) + '|' +

    ISNULL(
        REPLACE(
            REPLACE(
                LTRIM(RTRIM(v.VIN)),
                CHAR(13),
                ''
            ),
            CHAR(10),
            ''
        ),
        ''
    ) + '|' +

    ISNULL(
        REPLACE(
            REPLACE(
                LTRIM(
                    RTRIM(
                        CASE
                            WHEN v.NovaRegistracniZnacka IS NOT NULL
                                 AND LTRIM(RTRIM(v.NovaRegistracniZnacka)) <> ''
                            THEN v.NovaRegistracniZnacka
                            ELSE v.RegistracniZnacka
                        END
                    )
                ),
                CHAR(13),
                ''
            ),
            CHAR(10),
            ''
        ),
        ''
    ) + '|' +

    ISNULL(
        REPLACE(
            REPLACE(
                REPLACE(
                    LTRIM(RTRIM(v.Stav)),
                    CHAR(13),
                    ' '
                ),
                CHAR(10),
                ' '
            ),
            '|',
            '/'
        ),
        ''
    ) + '|' +

    ISNULL(
        CONVERT(VARCHAR(19), normalni_vykup.DatumVykupu, 120),
        ''
    ) + '|' +

    ISNULL(
        CONVERT(VARCHAR(19), komise_vykup.DatumVykupu, 120),
        ''
    ) + '|' +

    ISNULL(
        CONVERT(VARCHAR(19), prodej.DatumProdeje, 120),
        ''
    ) + '|' +

    ISNULL(
        REPLACE(
            REPLACE(
                LTRIM(RTRIM(v.ZemePuvodu)),
                CHAR(13),
                ''
            ),
            CHAR(10),
            ''
        ),
        ''
    ) + '|' +

    ISNULL(
        REPLACE(
            REPLACE(
                REPLACE(
                    LTRIM(RTRIM(v.Poznamky)),
                    CHAR(13),
                    ' '
                ),
                CHAR(10),
                ' '
            ),
            '|',
            '/'
        ),
        ''
    )

FROM dbo.Vozidlo v

OUTER APPLY (
    SELECT
        MAX(vv.DatumVykupu) AS DatumVykupu
    FROM dbo.VykupVozidla vv
    WHERE
        vv.Vozidlo = v.OID
        AND vv.DatumVykupu IS NOT NULL
        AND vv.GCRecord IS NULL
) normalni_vykup

OUTER APPLY (
    SELECT
        MAX(vk.DatumVykupu) AS DatumVykupu
    FROM dbo.VykoupeniZKomise vk
    WHERE
        vk.Vozidlo = v.OID
        AND vk.DatumVykupu IS NOT NULL
        AND vk.GCRecord IS NULL
) komise_vykup

OUTER APPLY (
    SELECT
        MAX(p.DatumProdeje) AS DatumProdeje
    FROM dbo.Prodej p
    WHERE
        p.Vozidlo = v.OID
        AND p.DatumProdeje IS NOT NULL
        AND p.GCRecord IS NULL
) prodej

WHERE
    v.GCRecord IS NULL

ORDER BY
    v.OID;
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
        raise RuntimeError(
            f"Chybí {freetds_conf}"
        )

    if not tsql.exists():
        raise RuntimeError(
            f"Chybí {tsql}"
        )

    env = os.environ.copy()
    env["FREETDSCONF"] = str(freetds_conf)
    env["TDSVER"] = "7.2"

    print()
    print("Připojuji se READ-ONLY k TIRBazar...")
    print("Načítám všechna vozidla z dbo.Vozidlo.")
    print("Zařazení: DatumVykupu NEBO Vykoupení z komise.")
    print("Stav vozidla se používá pouze k vyřazení vozidel 'V komisi'.")
    print("VIN = hlavní identifikátor.")
    print("SPZ = sekundární kontrola.")
    print()

    try:
        result = subprocess.run(
            [
                str(tsql),
                "-S",
                "tirbazar",
                "-U",
                config.username,
                "-P",
                password,
            ],
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
        raise RuntimeError(
            stderr.strip() or stdout.strip()
        )

    total = 0
    raw_rows: list[TirVehicle] = []

    for original in stdout.splitlines():
        line = original.strip()

        if "__TOTAL__|" in line:
            value = line[line.find("__TOTAL__|"):]

            try:
                total = int(
                    value.split("|", 1)[1].strip()
                )
            except Exception:
                pass

        if "__ROW__|" not in line:
            continue

        value = line[line.find("__ROW__|"):]
        parts = value.split("|", 9)

        if len(parts) != 10:
            continue

        # POZOR: pořadí musí přesně odpovídat build_sql().
        # __ROW__ | OID | VIN | SPZ | stav | výkup | výkup z komise |
        # prodej | země původu | poznámky
        (
            _,
            oid_text,
            vin,
            spz,
            stav,
            datum_vykupu,
            datum_vykupu_komise,
            datum_prodeje,
            zeme_puvodu,
            poznamky,
        ) = parts

        try:
            oid = int(oid_text.strip())
        except ValueError:
            continue

        normal_purchase = datum_vykupu.strip()
        commission_purchase = datum_vykupu_komise.strip()

        # Hlavní datum výkupu:
        # pokud existuje normální výkup, použijeme ho;
        # jinak použijeme výkup z komise.
        effective_purchase = (
            normal_purchase
            or commission_purchase
        )

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
        raise RuntimeError(
            "Z TIRBazar nebyla načtena žádná vozidla."
        )

    # ========================================================
    # ZAŘAZENÍ DO KONTROLY
    #
    # Standardně musí mít DatumVykupu nebo Vykoupení z komise.
    # Vozidla se stavem "V komisi" si ale necháváme v pomocném
    # seznamu, aby jejich VIN nebyl později omylem označen jako
    # "NAVÍC V UNIQA". Samotná kontrola pojištění je ignoruje.
    # ========================================================

    commission = [
        v
        for v in raw_rows
        if _is_commission_state(v.stav)
    ]

    excluded = [
        v
        for v in raw_rows
        if (
            not v.datum_vykupu
            and not _is_commission_state(v.stav)
        )
    ]

    foreign_without_spz = [
        v
        for v in raw_rows
        if (
            v.datum_vykupu
            and not _is_commission_state(v.stav)
            and v.zeme_puvodu.strip()
            and v.zeme_puvodu.strip().upper()
            not in {
                "CZ",
                "CZE",
                "ČR",
                "CR",
                "ČESKÁ REPUBLIKA",
                "CESKA REPUBLIKA",
            }
            and not v.spz
        )
    ]

    foreign_without_spz_oids = {
        v.oid for v in foreign_without_spz
    }

    included = [
        v
        for v in raw_rows
        if (
            (
                v.datum_vykupu
                or _is_commission_state(v.stav)
            )
            and v.oid not in foreign_without_spz_oids
        )
    ]

    without_vin = [
        v
        for v in included
        if not v.vin
    ]

    comparable = [
        v
        for v in included
        if v.vin
    ]

    groups: dict[str, list[TirVehicle]] = defaultdict(list)

    for vehicle in comparable:
        groups[vehicle.vin].append(vehicle)

    vehicles: list[TirVehicle] = []
    duplicates: list[list[TirVehicle]] = []

    for vin, group in groups.items():
        group = sorted(
            group,
            key=lambda x: x.oid,
            reverse=True,
        )

        vehicles.append(
            group[0]
        )

        if len(group) > 1:
            duplicates.append(
                group
            )

    vehicles.sort(
        key=lambda x: x.oid
    )

    active = sum(
        1
        for v in vehicles
        if (
            not v.datum_prodeje
            and not _is_commission_state(v.stav)
        )
    )

    sold = sum(
        1
        for v in vehicles
        if (
            v.datum_prodeje
            and not _is_commission_state(v.stav)
        )
    )

    commission_unique = sum(
        1
        for v in vehicles
        if _is_commission_state(v.stav)
    )

    print("=" * 68)
    print("TIRBAZAR - VÝBĚR")
    print("=" * 68)
    print()
    print("Všechna nesmazaná vozidla:", total or len(raw_rows))
    print("Bez výkupu / výkupu z komise - VYŘAZENO:", len(excluded))
    print(
        f"V komisi - IGNOROVÁNO PŘI KONTROLE: "
        f"{commission_unique}"
    )
    print(
        f"Cizina bez registrační značky - VYŘAZENO: "
        f"{len(foreign_without_spz)}"
    )
    print("Načteno pro porovnání:", len(included))
    print("Načtené bez VIN:", len(without_vin))
    print("Unikátních VIN po deduplikaci:", len(vehicles))
    print()
    print("Aktivní ke kontrole - bez DatumProdeje:", active)
    print("Prodaná - mají DatumProdeje:", sold)
    print("Duplicitních VIN skupin:", len(duplicates))
    print()

    return vehicles, duplicates
