from __future__ import annotations

from dataclasses import dataclass


@dataclass
class TirVehicle:
    oid: int
    vin: str
    spz: str
    zeme_puvodu: str = ""
    datum_vykupu: str = ""
    datum_prodeje: str = ""
    poznamky: str = ""


@dataclass
class UniqaVehicle:
    vin: str
    spz: str
    cps: str = ""
    poj_od: str = ""
    poj_do: str = ""


@dataclass
class ComparisonResult:
    oid: int | None
    vin: str
    tir_spz: str
    uniqa_spz: str
    status: str
    detail: str
    datum_vykupu: str = ""
    datum_prodeje: str = ""
