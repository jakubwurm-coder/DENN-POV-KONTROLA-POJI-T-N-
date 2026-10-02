from __future__ import annotations

import csv
import io
from dataclasses import dataclass

import requests

from normalize import normalize_spz, normalize_vin, vin_looks_standard


ALLIANZ_GITHUB_URL = (
    "https://raw.githubusercontent.com/"
    "jakubwurm-coder/DENN-POV-KONTROLA-POJI-T-N-/main/aktual_ALLIANZ.csv"
)


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
        response = requests.get(
            ALLIANZ_GITHUB_URL,
            headers={
                "Accept": "text/csv,text/plain;q=0.9,*/*;q=0.8",
                "User-Agent": "DENNI-POV-Agent/Allianz",
            },
            timeout=20,
        )
        response.raise_for_status()

        text = response.content.decode("utf-8-sig")
        if not text.strip():
            raise RuntimeError("Allianz CSV na GitHubu je prázdný.")

        vehicles: list[AllianzVehicle] = []
        seen: set[str] = set()

        # Allianz data mají jediný autoritativní zdroj: GitHub.
        # Standardní 17znakové hodnoty bereme jako VIN, ostatní jako SPZ.
        with io.StringIO(text, newline="") as handle:
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

    print("Zdroj:", ALLIANZ_GITHUB_URL)
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
