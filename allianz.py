from __future__ import annotations

import csv
from dataclasses import dataclass
from pathlib import Path

from normalize import normalize_spz, normalize_vin, vin_looks_standard, vin_looks_standard


BASE_DIR = Path(__file__).resolve().parent
ALLIANZ_FILE = BASE_DIR / "aktual_ALLIANZ.csv"


@dataclass
class AllianzVehicle:
    identifier: str
    vin: str
    spz: str
    pojistka: str
    poj_od: str
    poj_do: str


@dataclass
class AllianzLoadResult:
    vehicles: list[AllianzVehicle]
    available: bool
    error: str = ""
    period_od: str = ""
    period_do: str = ""


def clean_text(value: str) -> str:
    return " ".join(str(value or "").replace("\xa0", " ").split())


def load_allianz_vehicles() -> AllianzLoadResult:
    try:
        if not ALLIANZ_FILE.exists():
            raise RuntimeError(f"Allianz CSV nebyl nalezen:\n{ALLIANZ_FILE}")

        vehicles: list[AllianzVehicle] = []
        seen: set[str] = set()

        # Aktuální Allianz CSV je jednoduchý seznam VIN/SPZ, jeden identifikátor na řádek.
        # Standardní 17znakové hodnoty bereme jako VIN, ostatní jako SPZ.
        with ALLIANZ_FILE.open("r", encoding="utf-8-sig", newline="") as handle:
            reader = csv.reader(handle)
            for row in reader:
                if not row:
                    continue
                raw = clean_text(row[0]).upper()
                if not raw:
                    continue

                normalized = normalize_vin(raw)
                if not normalized:
                    continue

                key = normalized
                if key in seen:
                    continue
                seen.add(key)

                if vin_looks_standard(normalized):
                    vin = normalized
                    spz = ""
                    identifier = vin
                else:
                    vin = ""
                    spz = normalize_spz(raw)
                    identifier = spz

                if not identifier:
                    continue

                vehicles.append(
                    AllianzVehicle(
                        identifier=identifier,
                        vin=vin,
                        spz=spz,
                        pojistka="",
                        poj_od="",
                        poj_do="",
                    )
                )

        vehicles.sort(key=lambda v: (v.vin or v.spz))

        if not vehicles:
            raise RuntimeError("Allianz CSV byl otevřen, ale nebylo rozpoznáno žádné vozidlo.")

        return AllianzLoadResult(
            vehicles=vehicles,
            available=True,
            error="",
            period_od="",
            period_do="",
        )

    except Exception as exc:
        return AllianzLoadResult(
            vehicles=[],
            available=False,
            error=str(exc),
            period_od="",
            period_do="",
        )


def print_report(result: AllianzLoadResult) -> None:
    print()
    print("=" * 72)
    print("ALLIANZ - NAČTENÍ AKTUÁLNÍHO CSV")
    print("=" * 72)
    print()

    if not result.available:
        print("ALLIANZ NELZE NAČÍST:")
        print(result.error)
        return

    print("Soubor:", ALLIANZ_FILE.name)
    print("Načtených vozidel:", len(result.vehicles))
    print()
    print("-" * 72)
    print(f"{'SPZ':<16}{'VIN':<20}")
    print("-" * 72)

    for vehicle in result.vehicles:
        print(f"{vehicle.spz:<16}{vehicle.vin:<20}")

    print("-" * 72)


if __name__ == "__main__":
    print_report(load_allianz_vehicles())
