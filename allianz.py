from __future__ import annotations

import csv
from dataclasses import dataclass
from pathlib import Path

from normalize import normalize_spz, normalize_vin


BASE_DIR = Path(__file__).resolve().parent
ALLIANZ_FILE = BASE_DIR / "aktual_ALLIANZ.txt"


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
            raise RuntimeError(f"Allianz tabulka nebyla nalezena:\n{ALLIANZ_FILE}")

        vehicles: list[AllianzVehicle] = []
        seen: set[tuple[str, str]] = set()

        with ALLIANZ_FILE.open("r", encoding="utf-8-sig", newline="") as handle:
            reader = csv.DictReader(handle, delimiter="\t")

            required = {"cislo_smlouvy", "datum_pocatku_pojisteni", "stav", "SPZ", "vin"}
            missing = required - set(reader.fieldnames or [])
            if missing:
                raise RuntimeError(
                    "Allianz tabulka nemá očekávané sloupce: " + ", ".join(sorted(missing))
                )

            for row in reader:
                # Aktuální Allianz export: AK = aktivní smlouva.
                if clean_text(row.get("stav", "")).upper() != "AK":
                    continue

                pojistka = clean_text(row.get("cislo_smlouvy", ""))
                poj_od = clean_text(row.get("datum_pocatku_pojisteni", ""))
                poj_do = clean_text(row.get("datum_storna", "")) or clean_text(
                    row.get("datum_konce_leasingu", "")
                )
                vin = normalize_vin(clean_text(row.get("vin", "")).upper())
                spz = normalize_spz(clean_text(row.get("SPZ", "")).upper())

                # Pro porovnání preferujeme VIN; pokud není validní/dostupný, zůstává SPZ.
                identifier = vin or spz
                if not identifier:
                    continue

                key = (pojistka, identifier)
                if key in seen:
                    continue
                seen.add(key)

                vehicles.append(
                    AllianzVehicle(
                        identifier=identifier,
                        vin=vin,
                        spz=spz,
                        pojistka=pojistka,
                        poj_od=poj_od,
                        poj_do=poj_do,
                    )
                )

        vehicles.sort(key=lambda v: (v.vin or v.spz))

        if not vehicles:
            raise RuntimeError("Allianz tabulka byla otevřena, ale nebyla rozpoznána žádná aktivní vozidla.")

        starts = sorted(v.poj_od for v in vehicles if v.poj_od)
        return AllianzLoadResult(
            vehicles=vehicles,
            available=True,
            error="",
            period_od=starts[0] if starts else "",
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
    print("ALLIANZ - NAČTENÍ AKTUÁLNÍ TABULKY")
    print("=" * 72)
    print()

    if not result.available:
        print("ALLIANZ NELZE NAČÍST:")
        print(result.error)
        return

    print("Soubor:", ALLIANZ_FILE.name)
    print("Načtených aktivních vozidel:", len(result.vehicles))
    print()
    print("-" * 72)
    print(f"{'POJISTKA':<12}{'SPZ':<12}{'VIN':<20}{'OD':<12}")
    print("-" * 72)

    for vehicle in result.vehicles:
        print(
            f"{vehicle.pojistka:<12}"
            f"{vehicle.spz:<12}"
            f"{vehicle.vin:<20}"
            f"{vehicle.poj_od:<12}"
        )

    print("-" * 72)


if __name__ == "__main__":
    print_report(load_allianz_vehicles())
