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

CZECH_COUNTRY_VALUES = {
    "A",
    "CZ",
    "CZE",
    "ČR",
    "CR",
    "ČESKO",
    "CESKO",
    "ČESKÁ REPUBLIKA",
    "CESKA REPUBLIKA",
    "CZECH REPUBLIC",
}

LOAN_STATE_VALUES = {
    "PŮJČENÉ",
    "PUJCENE",
    "PŮJČENÉ VOZIDLO",
    "PUJCENE VOZIDLO",
    "PŮJČENO",
    "PUJCENO",
}

IGNORED_POV_STATE_VALUES = {
    "NEPŘÍTOMNÉ",
    "NEPRITOMNE",
    "VRÁCENÉ Z KOMISE",
    "VRACENE Z KOMISE",
    "PRONAJATÉ",
    "PRONAJATE",
    "VOLNÉ",
    "VOLNE",
    "V KOMISI",
    "PARKOVANÉ",
    "PARKOVANE",
    "PARKOVÁNÍ UKONČENO",
    "PARKOVANI UKONCENO",
}


def _normalize_state(value: str) -> str:
    return " ".join(str(value or "").strip().upper().split())


def _is_commission_state(value: str) -> bool:
    return _normalize_state(value) == "V KOMISI"


def _is_returned_commission_state(value: str) -> bool:
    normalized = _normalize_state(value)
    return normalized in {
        "VRÁCENÉ Z KOMISE",
        "VRACENE Z KOMISE",
    }


def _is_loan_state(value: str) -> bool:
    normalized = _normalize_state(value)
    return normalized in LOAN_STATE_VALUES or "PŮJČ" in normalized or "PUJC" in normalized


def _is_ignored_pov_state(value: str) -> bool:
    normalized = _normalize_state(value)
    return normalized in IGNORED_POV_STATE_VALUES or _is_loan_state(value)


def _is_czech_country(value: str) -> bool:
    return _normalize_state(value) in CZECH_COUNTRY_VALUES


def _eligible_for_pov_check(vehicle: TirVehicle) -> bool:
    # Stavy bez povinnosti POV se záměrně ponechávají v interním seznamu.
    # Web je následně vyřadí z POV kontroly a jejich VIN odstraní z UNIQA
    # porovnání, aby nevzniklo falešné "NAVÍC V UNIQA".
    return (
        _is_czech_country(vehicle.zeme_puvodu)
        and bool(vehicle.spz)
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
    '__NON_CZECH__|' +
    CAST(COUNT(*) AS VARCHAR(20))
FROM dbo.Vozidlo v
WHERE
    v.GCRecord IS NULL
    AND UPPER(LTRIM(RTRIM(ISNULL(v.ZemePuvoduKod, '')))) <> 'A';
GO

SELECT
    '__WITHOUT_RZ__|' +
    CAST(COUNT(*) AS VARCHAR(20))
FROM dbo.Vozidlo v
WHERE
    v.GCRecord IS NULL
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
    '__RETURNED_COMMISSION__|' +
    CAST(COUNT(*) AS VARCHAR(20))
FROM dbo.Vozidlo v
WHERE
    v.GCRecord IS NULL
    AND UPPER(LTRIM(RTRIM(ISNULL(v.Stav, '')))) IN (
        N'VRÁCENÉ Z KOMISE',
        N'VRACENE Z KOMISE'
    );
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
                LTRIM(
                    RTRIM(
                        CASE
                            WHEN UPPER(LTRIM(RTRIM(ISNULL(v.ZemePuvoduKod, '')))) = 'A'
                            THEN 'CZ'
                            WHEN v.ZemePuvodu IS NOT NULL
                                 AND LTRIM(RTRIM(v.ZemePuvodu)) <> ''
                            THEN v.ZemePuvodu
                            ELSE v.ZemePuvoduKod
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
    AND UPPER(LTRIM(RTRIM(ISNULL(v.ZemePuvoduKod, '')))) = 'A'
    AND LTRIM(RTRIM(ISNULL(
        CASE
            WHEN v.NovaRegistracniZnacka IS NOT NULL
                 AND LTRIM(RTRIM(v.NovaRegistracniZnacka)) <> ''
            THEN v.NovaRegistracniZnacka
            ELSE v.RegistracniZnacka
        END,
        ''
    ))) <> ''

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
    print("Načítám jen vozidla CZ s vyplněnou registrační značkou.")
    print("Zařazení: DatumVykupu NEBO stav, který se z POV kontroly ignoruje.")
    print("Vozidla z jiné země se vyřazují už v SQL.")
    print("Vozidla bez registrační značky se vyřazují už v SQL.")
    print("Stavy bez POV se interně načtou, ale do kontroly se nezařadí.")
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
    non_czech_sql = 0
    without_spz_sql = 0
    returned_commission_sql = 0
    raw_rows: list[TirVehicle] = []

    for original in stdout.splitlines():
        line = original.strip()

        if "__TOTAL__|" in line:
            value = line[line.find("__TOTAL__|"):]
            try:
                total = int(value.split("|", 1)[1].strip())
            except Exception:
                pass

        if "__NON_CZECH__|" in line:
            value = line[line.find("__NON_CZECH__|"):]
            try:
                non_czech_sql = int(value.split("|", 1)[1].strip())
            except Exception:
                pass

        if "__WITHOUT_RZ__|" in line:
            value = line[line.find("__WITHOUT_RZ__|"):]
            try:
                without_spz_sql = int(value.split("|", 1)[1].strip())
            except Exception:
                pass

        if "__RETURNED_COMMISSION__|" in line:
            value = line[line.find("__RETURNED_COMMISSION__|"):]
            try:
                returned_commission_sql = int(value.split("|", 1)[1].strip())
            except Exception:
                pass

        if "__ROW__|" not in line:
            continue

        value = line[line.find("__ROW__|"):]
        parts = value.split("|", 9)

        if len(parts) != 10:
            continue

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
        raise RuntimeError(
            "Z TIRBazar nebyla načtena žádná vozidla."
        )

    pov_filter_excluded = [
        v
        for v in raw_rows
        if not _eligible_for_pov_check(v)
    ]

    candidate_rows = [
        v
        for v in raw_rows
        if _eligible_for_pov_check(v)
    ]

    excluded = [
        v
        for v in candidate_rows
        if (
            not v.datum_vykupu
            and not _is_ignored_pov_state(v.stav)
        )
    ]

    included = [
        v
        for v in candidate_rows
        if (
            v.datum_vykupu
            or _is_ignored_pov_state(v.stav)
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

        vehicles.append(group[0])

        if len(group) > 1:
            duplicates.append(group)

    vehicles.sort(key=lambda x: x.oid)

    active = sum(
        1
        for v in vehicles
        if (
            not v.datum_prodeje
            and not _is_ignored_pov_state(v.stav)
        )
    )

    sold = sum(
        1
        for v in vehicles
        if (
            v.datum_prodeje
            and not _is_ignored_pov_state(v.stav)
        )
    )

    commission = sum(
        1
        for v in vehicles
        if _is_commission_state(v.stav)
    )

    loaned = sum(
        1
        for v in vehicles
        if _is_loan_state(v.stav)
    )

    ignored = sum(
        1
        for v in vehicles
        if _is_ignored_pov_state(v.stav)
    )

    print()
    print("TIRBazar LIVE:")
    print("Celkem záznamů:", total)
    print("Jiná země - vyřazeno:", non_czech_sql)
    print("Bez registrační značky - vyřazeno:", without_spz_sql)
    print("Vrácené z komise - nalezeno:", returned_commission_sql)
    print("Další vyřazené POV filtrem:", len(pov_filter_excluded))
    print("Bez výkupu - vyřazeno:", len(excluded))
    print("Bez VIN - vyřazeno:", len(without_vin))
    print("Duplicitních VIN skupin:", len(duplicates))
    print("Aktivních ke kontrole:", active)
    print("Prodaných:", sold)
    print("V komisi - ignorováno:", commission)
    print("Půjčené - ignorováno:", loaned)
    print("Stavem bez POV ignorováno celkem:", ignored)
    print("Interně načteno celkem:", len(vehicles))
    print()

    return vehicles, duplicates
