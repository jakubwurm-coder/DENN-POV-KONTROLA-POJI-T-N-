"""Presentation-only technical data; never participates in insurance decisions."""
from __future__ import annotations

import re

# Only explicit scalar columns. Never interpret a numeric dictionary/FK as text.
SQL_FIELDS = {
    "Palivo": (("PalivoNazev", "Palivo"), False),
    "MotorZdvihObjem": (("ZdvihovyObjem", "ObjemMotoru", "MotorZdvihObjem"), True),
    "MotorMaxVykon": (("VykonMotoru", "Vykon", "MotorMaxVykon"), True),
    "VozidloKaroserieBarva": (("BarvaNazev", "Barva"), False),
    "DatumPrvniRegistrace": (("DatumPrvniRegistrace", "PrvniRegistrace"), True),
    "PravidelnaTechnickaProhlidkaDo": (("STKDo", "PlatnostSTK"), True),
    "Kategorie": (("KategorieNazev", "Kategorie"), False),
}


def normalize_vin(value):
    return re.sub(r"\s+", "", str(value or "")).upper()


def technical_sql():
    batches = []
    for field, (aliases, scalar) in SQL_FIELDS.items():
        types = "'varchar','nvarchar','char','nchar'"
        if scalar:
            types += ",'int','smallint','decimal','numeric','float','real','date','datetime','datetime2','smalldatetime'"
        choices = "\n".join(
            ("IF" if i == 0 else "ELSE IF") +
            f" EXISTS (SELECT 1 FROM sys.columns WHERE object_id = OBJECT_ID('dbo.Vozidlo') AND name = '{col}' AND TYPE_NAME(system_type_id) IN ({types}))\n"
            f"    SET @expr = N'CONVERT(NVARCHAR(200), v.[{col}], 126)';"
            for i, col in enumerate(aliases)
        )
        batches.append(f"""
BEGIN TRY
DECLARE @expr NVARCHAR(1000) = N'CONVERT(NVARCHAR(200), NULL)';
{choices}
DECLARE @technicalSql NVARCHAR(MAX) = N'
SELECT ''__TECHNICAL__|'' + CAST(v.OID AS VARCHAR(20)) + ''|{field}|'' +
ISNULL(REPLACE(REPLACE(REPLACE(' + @expr + N', CHAR(13), '' ''), CHAR(10), '' ''), ''|'', ''/''), '''')
FROM dbo.Vozidlo v WHERE v.GCRecord IS NULL ORDER BY v.OID;';
EXEC sp_executesql @technicalSql;
END TRY
BEGIN CATCH
    PRINT 'Technicke udaje: nepovinne pole neni dostupne.';
END CATCH
GO
""")
    return "".join(batches)


def sql_record(vehicle):
    return {
        "oid": vehicle.oid,
        "data": {
            **(getattr(vehicle, "technical", None) or {}),
            "TovarniZnacka": vehicle.znacka,
            "ObchodniOznaceni": vehicle.model,
            "StatusNazev": vehicle.stav,
            "RegistracniZnacka": vehicle.spz,
            "ZemePuvodu": vehicle.zeme_puvodu,
        },
    }


def source_record(state, vin):
    """None means unknown; an empty record means confirmed absent in SQL."""
    mapping = state.get("sql_technical")
    if isinstance(mapping, dict) and mapping.get("complete") is True:
        return (mapping.get("vehicles") or {}).get(vin, {})
    # Compatibility with snapshots from agents predating the technical index.
    for row in state.get("results") or []:
        if normalize_vin(row.get("vin")) == vin and (row.get("oid") is not None or row.get("spz_tir") or row.get("vykup")):
            return {"oid": row.get("oid"), "data": {
                "TovarniZnacka": row.get("znacka", ""),
                "ObchodniOznaceni": row.get("model", ""),
                "RegistracniZnacka": row.get("spz_tir", ""),
            }}
    return None


def kostka_candidates(state):
    return list(dict.fromkeys(
        vin for row in state.get("results") or []
        if isinstance(row, dict)
        and re.fullmatch(r"[A-HJ-NPR-Z0-9]{17}", vin := normalize_vin(row.get("vin")))
        and source_record(state, vin) == {}
    ))
