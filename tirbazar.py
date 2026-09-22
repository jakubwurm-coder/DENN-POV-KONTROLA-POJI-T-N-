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
    "V KOMISI",
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
}

# Krajské písmeno v běžné české registrační značce.
# Příklady: 6ST9595, 9AK7158, 7AC6140, 1TV1811.
CZECH_REGION_LETTERS = "ABCEHJKLM PSTUZ".replace(" ", "")
CZECH_STANDARD_SPZ_RE = re.compile(
    rf"^[0-9][{CZECH_REGION_LETTERS}][A-Z0-9][0-9]{{4}}$"
)


def _normalize_state(value: str) -> str:
    return " ".join(str(value or "").strip().upper().split())


def _clean_vehicle_brand(value: str) -> str:
    text = " ".join(str(value or "").strip().split())
    if not text or text.isdigit():
        return ""

    aliases = {
        "IVECO": "Iveco",
        "RENAULT": "Renault",
        "FORD": "Ford",
        "FIAT": "Fiat",
        "PEUGEOT": "Peugeot",
        "CITROEN": "Citroën",
        "CITROËN": "Citroën",
        "MERCEDES": "Mercedes-Benz",
        "MERCEDES-BENZ": "Mercedes-Benz",
        "VOLKSWAGEN": "Volkswagen",
        "VW": "Volkswagen",
        "OPEL": "Opel",
        "MAN": "MAN",
        "DAF": "DAF",
        "SKODA": "Škoda",
        "ŠKODA": "Škoda",
    }
    return aliases.get(text.upper(), text.title())


def _simple_vehicle_model(brand: str, value: str) -> str:
    text = " ".join(str(value or "").strip().split())
    if not text or text.isdigit():
        return ""

    if brand:
        text = re.sub(
            rf"^{re.escape(brand)}(?:[-\s_/]+|$)",
            "",
            text,
            flags=re.IGNORECASE,
        ).strip()

    tokens = [token.strip(".,;:()[]{}_/\\-") for token in text.split()]
    tokens = [token for token in tokens if token]

    for index, token in enumerate(tokens):
        letters = sum(ch.isalpha() for ch in token)
        digits = sum(ch.isdigit() for ch in token)
        if letters >= 3 and letters >= digits:
            first = token.title() if token.isupper() else token[0].upper() + token[1:]
            if first.lower() == "transit" and index + 1 < len(tokens):
                second = tokens[index + 1]
                if second.upper() in {"CUSTOM", "CONNECT"}:
                    return first + " " + second.title()
            return first
    return ""


def _is_czech_country(value: str) -> bool:
    return _normalize_state(value) in {"CZ", "CZE", "ČR"}


def _is_czech_spz(value: str) -> bool:
    spz = normalize_spz(value)
    return bool(CZECH_STANDARD_SPZ_RE.fullmatch(spz))


def _is_czech_for_pov(vehicle: TirVehicle) -> bool:
    country = _normalize_state(vehicle.zeme_puvodu)
    spz = normalize_spz(vehicle.spz)

    # Česká země původu: kontrolujeme i bez registrační značky, podle VIN.
    if _is_czech_country(country):
        return True

    # Jiná vyplněná země: pokud má vozidlo SPZ, také kontrolujeme.
    if country and spz:
        return True

    # Prázdná země: kontrolujeme, pokud SPZ odpovídá českému formátu.
    if not country and _is_czech_spz(spz):
        return True

    return False


def _is_control_pov_state(value: str) -> bool:
    return _normalize_state(value) in CONTROL_POV_STATE_VALUES


def _is_ignored_pov_state(value: str) -> bool:
    # POV se kontroluje podle stavu a u rezervace/komise také podle existence výkupu.
    return not _is_control_pov_state(value)


def _requires_pov_check(vehicle: TirVehicle) -> bool:
    if not _is_czech_for_pov(vehicle):
        return False
    if not vehicle.vin:
        return False
    if vehicle.datum_prodeje:
        return False

    state = _normalize_state(vehicle.stav)

    # Vykoupené vozidlo má být pojištěné vždy.
    if state in {"VYKOUPENÉ", "VYKOUPENE"}:
        return True

    # Nepřítomné vozidlo s evidovaným výkupem zůstává aktivní pro kontrolu.
    # Očekávaný správný stav je ale opačný než u běžného výkupu:
    # NEPŘÍTOMNÉ má být nepojištěné a kontrola hlídá, zda pojištění nezůstalo aktivní.
    if state in {"NEPŘÍTOMNÉ", "NEPRITOMNE"}:
        return bool(vehicle.datum_vykupu)

    # Samotná rezervace ani komise ještě neznamená povinnost POV.
    # Do kontroly vstoupí až tehdy, když je v TIRBazar evidovaný výkup
    # (běžný výkup nebo vykoupení z komise).
    if state in {"REZERVOVANÉ", "REZERVOVANE", "V KOMISI"}:
        return bool(vehicle.datum_vykupu)

    return False


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
    # Interně načítáme VŠECHNA nesmazaná vozidla.
    # Země původu se nepřebírá z interního kódu A/B/C..., ale překládá se
    # přes číselník dbo.CL_StatPuvodu (např. A -> CZ, B -> SK).
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
    ISNULL(
        REPLACE(
            REPLACE(
                LTRIM(RTRIM(
                    COALESCE(
                        NULLIF(stat_puvodu.PopisStatu COLLATE DATABASE_DEFAULT, ''),
                        NULLIF(v.ZemePuvodu COLLATE DATABASE_DEFAULT, ''),
                        v.ZemePuvoduKod COLLATE DATABASE_DEFAULT,
                        ''
                    )
                )),
                CHAR(13),
                ''
            ),
            CHAR(10),
            ''
        ),
        ''
    ) + '|' +
    ISNULL(REPLACE(REPLACE(REPLACE(LTRIM(RTRIM(v.Poznamky)), CHAR(13), ' '), CHAR(10), ' '), '|', '/'), '')
FROM dbo.Vozidlo v
OUTER APPLY (
    SELECT TOP 1 LTRIM(RTRIM(s.PopisStatu)) COLLATE DATABASE_DEFAULT AS PopisStatu
    FROM dbo.CL_StatPuvodu s
    WHERE LTRIM(RTRIM(s.KodStatu)) COLLATE DATABASE_DEFAULT
        = LTRIM(RTRIM(v.ZemePuvoduKod)) COLLATE DATABASE_DEFAULT
) stat_puvodu
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

-- Základní značka a model vozidla pro detail na webu.
-- Pole se hledají dynamicky, aby dotaz zůstal funkční mezi verzemi TIRBazar.
DECLARE @brandExpr NVARCHAR(4000) = N'CONVERT(NVARCHAR(200), NULL)';
DECLARE @modelExpr NVARCHAR(4000) = N'CONVERT(NVARCHAR(300), NULL)';

IF EXISTS (SELECT 1 FROM sys.columns WHERE object_id = OBJECT_ID('dbo.Vozidlo') AND name = 'TovarniZnacka' AND TYPE_NAME(system_type_id) IN ('varchar','nvarchar','char','nchar'))
    SET @brandExpr = N'CONVERT(NVARCHAR(200), v.TovarniZnacka)';
ELSE IF EXISTS (SELECT 1 FROM sys.columns WHERE object_id = OBJECT_ID('dbo.Vozidlo') AND name = 'Znacka' AND TYPE_NAME(system_type_id) IN ('varchar','nvarchar','char','nchar'))
    SET @brandExpr = N'CONVERT(NVARCHAR(200), v.Znacka)';
ELSE IF EXISTS (SELECT 1 FROM sys.columns WHERE object_id = OBJECT_ID('dbo.Vozidlo') AND name = 'Vyrobce' AND TYPE_NAME(system_type_id) IN ('varchar','nvarchar','char','nchar'))
    SET @brandExpr = N'CONVERT(NVARCHAR(200), v.Vyrobce)';
ELSE IF EXISTS (SELECT 1 FROM sys.columns WHERE object_id = OBJECT_ID('dbo.Vozidlo') AND name = 'VyrobceVozidla' AND TYPE_NAME(system_type_id) IN ('varchar','nvarchar','char','nchar'))
    SET @brandExpr = N'CONVERT(NVARCHAR(200), v.VyrobceVozidla)';

IF EXISTS (SELECT 1 FROM sys.columns WHERE object_id = OBJECT_ID('dbo.Vozidlo') AND name = 'ObchodniOznaceni' AND TYPE_NAME(system_type_id) IN ('varchar','nvarchar','char','nchar'))
    SET @modelExpr = N'CONVERT(NVARCHAR(300), v.ObchodniOznaceni)';
ELSE IF EXISTS (SELECT 1 FROM sys.columns WHERE object_id = OBJECT_ID('dbo.Vozidlo') AND name = 'Model' AND TYPE_NAME(system_type_id) IN ('varchar','nvarchar','char','nchar'))
    SET @modelExpr = N'CONVERT(NVARCHAR(300), v.Model)';
ELSE IF EXISTS (SELECT 1 FROM sys.columns WHERE object_id = OBJECT_ID('dbo.Vozidlo') AND name = 'ModelVozidla' AND TYPE_NAME(system_type_id) IN ('varchar','nvarchar','char','nchar'))
    SET @modelExpr = N'CONVERT(NVARCHAR(300), v.ModelVozidla)';
ELSE IF EXISTS (SELECT 1 FROM sys.columns WHERE object_id = OBJECT_ID('dbo.Vozidlo') AND name = 'TypVozidla' AND TYPE_NAME(system_type_id) IN ('varchar','nvarchar','char','nchar'))
    SET @modelExpr = N'CONVERT(NVARCHAR(300), v.TypVozidla)';
ELSE IF EXISTS (SELECT 1 FROM sys.columns WHERE object_id = OBJECT_ID('dbo.Vozidlo') AND name = 'NazevVozidla' AND TYPE_NAME(system_type_id) IN ('varchar','nvarchar','char','nchar'))
    SET @modelExpr = N'CONVERT(NVARCHAR(300), v.NazevVozidla)';
ELSE IF EXISTS (SELECT 1 FROM sys.columns WHERE object_id = OBJECT_ID('dbo.Vozidlo') AND name = 'Nazev' AND TYPE_NAME(system_type_id) IN ('varchar','nvarchar','char','nchar'))
    SET @modelExpr = N'CONVERT(NVARCHAR(300), v.Nazev)';

DECLARE @metaSql NVARCHAR(MAX) = N'
SELECT
    ''__VEHICLE_META__|'' + CAST(v.OID AS VARCHAR(20)) + ''|'' +
    ISNULL(REPLACE(REPLACE(REPLACE(LTRIM(RTRIM(' + @brandExpr + N')), CHAR(13), '' ''), CHAR(10), '' ''), ''|'', ''/''), '''') + ''|'' +
    ISNULL(REPLACE(REPLACE(REPLACE(LTRIM(RTRIM(' + @modelExpr + N')), CHAR(13), '' ''), CHAR(10), '' ''), ''|'', ''/''), '''')
FROM dbo.Vozidlo v
WHERE v.GCRecord IS NULL
ORDER BY v.OID;';

EXEC sp_executesql @metaSql;
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
    print("Země původu: překlad přes CL_StatPuvodu (A -> CZ, B -> SK atd.).")
    print("POV kontrola: Vykoupené vždy; Nepřítomné/Rezervované/V komisi pouze pokud mají evidovaný výkup.")
    print("CZ: kontrola i bez SPZ. Jiná země + SPZ: také kontrola.")
    print("Prázdná země + česká SPZ: také kontrola.")
    print("Nepřítomné s výkupem se kontrolují s očekáváním NEPOJIŠTĚNO.")
    print("Pronajaté, Volné, Parkované, Parkování ukončeno, Prodané, Vrácené z komise")
    print("a ostatní stavy se nekontrolují; Nepřítomné/rezervace/komise bez výkupu také ne.")
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
    vehicle_meta: dict[int, tuple[str, str]] = {}

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

        if "__VEHICLE_META__|" in line:
            value = line[line.find("__VEHICLE_META__|"):]
            parts = value.split("|", 3)
            if len(parts) == 4:
                try:
                    meta_oid = int(parts[1].strip())
                    vehicle_meta[meta_oid] = (parts[2].strip(), parts[3].strip())
                except ValueError:
                    pass
            continue

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

    for vehicle in raw_rows:
        raw_brand, raw_model = vehicle_meta.get(vehicle.oid, ("", ""))
        vehicle.znacka = _clean_vehicle_brand(raw_brand)
        vehicle.model = _simple_vehicle_model(vehicle.znacka, raw_model)

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
    absent = [
        v for v in control
        if _normalize_state(v.stav) in {"NEPŘÍTOMNÉ", "NEPRITOMNE"}
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
    other_country_with_spz = [
        v for v in control
        if _normalize_state(v.zeme_puvodu)
        and not _is_czech_country(v.zeme_puvodu)
        and bool(v.spz)
    ]
    sold = [
        v for v in vehicles
        if bool(v.datum_prodeje) or _normalize_state(v.stav) in {"PRODANÉ", "PRODANE"}
    ]
    ignored = [v for v in vehicles if v not in control]

    print()
    print("TIRBazar LIVE:")
    print("Celkem nesmazaných záznamů:", total)
    print("Záznamů s interním kódem země A (CZ):", code_a_sql)
    print("CZ bez registrační značky:", without_spz_sql)
    print("Bez VIN - nelze porovnat podle VIN:", max(without_vin_sql, len(without_vin)))
    print("Unikátních známých VIN v TIRBazar:", len(vehicles))
    print("Duplicitních VIN skupin:", len(duplicates))
    print("Vykoupené ke kontrole:", len(purchased))
    print("Nepřítomné vykoupené ke kontrole:", len(absent))
    print("Rezervované ke kontrole:", len(reserved))
    print("Prázdná země + česká SPZ ke kontrole:", len(blank_country_czech_spz))
    print("Jiná země + SPZ ke kontrole:", len(other_country_with_spz))
    print("Ke kontrole bez SPZ (CZ, podle VIN):", len(control_without_spz))
    print("Prodané - ignorováno:", len(sold))
    print("Ostatní vozidla mimo pravidla POV - ignorováno:", len(ignored))
    print("Aktivních ke kontrole celkem:", len(control))
    print()

    return vehicles, duplicates