from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

from pypdf import PdfReader

from normalize import normalize_spz, normalize_vin


BASE_DIR = Path(__file__).resolve().parent

ALLIANZ_PDF = BASE_DIR / "Pojisteni_898405561_210928898.pdf"


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
    return " ".join(
        str(value or "")
        .replace("\xa0", " ")
        .split()
    )


def parse_period(text: str) -> tuple[str, str]:

    match = re.search(
        r"Období\s+"
        r"(\d{1,2}\.\s*\d{1,2}\.\s*\d{4})"
        r"\s*-\s*"
        r"(\d{1,2}\.\s*\d{1,2}\.\s*\d{4})",
        text,
        flags=re.IGNORECASE,
    )

    if not match:
        return "", ""

    return (
        clean_text(match.group(1)),
        clean_text(match.group(2)),
    )


def parse_vehicle_line(line: str) -> AllianzVehicle | None:

    line = clean_text(line)

    if not line:
        return None

    # Každý skutečný řádek vozidla začíná 9místným číslem pojistky.
    policy_match = re.match(
        r"^(\d{9})\b",
        line,
    )

    if not policy_match:
        return None

    pojistka = policy_match.group(1)

    # Musíme mít minimálně dvě data:
    # první = Od
    # poslední = Do
    dates = list(
        re.finditer(
            r"\d{1,2}\.\s*\d{1,2}\.\s*\d{4}",
            line,
        )
    )

    if len(dates) < 2:
        return None

    poj_od = clean_text(
        dates[0].group(0)
    )

    poj_do = clean_text(
        dates[-1].group(0)
    )

    # --------------------------------------------------------
    # KLÍČOVÁ OPRAVA
    #
    # PDF extrakce vrací například:
    #
    # 98 Kč1AAA171 8. 10. 2026
    #
    # místo:
    #
    # 98 Kč 1AAA171 8. 10. 2026
    #
    # Proto nehledáme "poslední token", ale přímo SPZ/VIN
    # stojící bezprostředně před posledním datem.
    # --------------------------------------------------------

    identifier_match = re.search(
        r"(?:Kč)?"
        r"([A-Z0-9]{5,17})"
        r"\s+"
        r"\d{1,2}\.\s*\d{1,2}\.\s*\d{4}"
        r"\s*$",
        line,
        flags=re.IGNORECASE,
    )

    if not identifier_match:
        return None

    identifier = (
        identifier_match
        .group(1)
        .strip()
        .upper()
    )

    # 17 znaků = VIN.
    # Kratší identifikátor = SPZ/RZ.
    if len(identifier) == 17:

        vin = normalize_vin(
            identifier
        )

        spz = ""

    else:

        vin = ""

        spz = normalize_spz(
            identifier
        )

    return AllianzVehicle(
        identifier=identifier,
        vin=vin,
        spz=spz,
        pojistka=pojistka,
        poj_od=poj_od,
        poj_do=poj_do,
    )


def load_allianz_vehicles() -> AllianzLoadResult:

    try:

        if not ALLIANZ_PDF.exists():
            raise RuntimeError(
                "Allianz PDF nebylo nalezeno:\n"
                f"{ALLIANZ_PDF}"
            )

        reader = PdfReader(
            str(ALLIANZ_PDF)
        )

        all_text_parts: list[str] = []
        vehicles: list[AllianzVehicle] = []

        seen_rows: set[
            tuple[str, str]
        ] = set()

        for page in reader.pages:

            text = page.extract_text() or ""

            all_text_parts.append(
                text
            )

            for raw_line in text.splitlines():

                vehicle = parse_vehicle_line(
                    raw_line
                )

                if vehicle is None:
                    continue

                key = (
                    vehicle.pojistka,
                    vehicle.identifier,
                )

                if key in seen_rows:
                    continue

                seen_rows.add(
                    key
                )

                vehicles.append(
                    vehicle
                )

        full_text = "\n".join(
            all_text_parts
        )

        period_od, period_do = parse_period(
            full_text
        )

        vehicles.sort(
            key=lambda v: (
                v.vin or v.spz
            )
        )

        if not vehicles:
            raise RuntimeError(
                "PDF bylo otevřeno, ale nebyla "
                "rozpoznána žádná vozidla."
            )

        return AllianzLoadResult(
            vehicles=vehicles,
            available=True,
            error="",
            period_od=period_od,
            period_do=period_do,
        )

    except Exception as exc:

        return AllianzLoadResult(
            vehicles=[],
            available=False,
            error=str(exc),
            period_od="",
            period_do="",
        )


def print_report(
    result: AllianzLoadResult,
) -> None:

    print()
    print("=" * 72)
    print("ALLIANZ - NAČTENÍ PDF")
    print("=" * 72)
    print()

    if not result.available:

        print("ALLIANZ NELZE NAČÍST:")
        print(result.error)

        return

    print(
        "Soubor:",
        ALLIANZ_PDF.name,
    )

    print(
        "Období:",
        (
            f"{result.period_od} - {result.period_do}"
            if result.period_od
            else "nezjištěno"
        ),
    )

    print(
        "Načtených vozidel:",
        len(result.vehicles),
    )

    count_vin = sum(
        1
        for vehicle in result.vehicles
        if vehicle.vin
    )

    count_spz = sum(
        1
        for vehicle in result.vehicles
        if vehicle.spz
    )

    print(
        "Záznamů vedených VIN:",
        count_vin,
    )

    print(
        "Záznamů vedených SPZ:",
        count_spz,
    )

    print()
    print("-" * 72)

    print(
        f"{'POJISTKA':<12}"
        f"{'SPZ / VIN':<22}"
        f"{'OD':<15}"
        f"{'DO':<15}"
    )

    print("-" * 72)

    for vehicle in result.vehicles:

        print(
            f"{vehicle.pojistka:<12}"
            f"{vehicle.identifier:<22}"
            f"{vehicle.poj_od:<15}"
            f"{vehicle.poj_do:<15}"
        )

    print("-" * 72)
    print()


if __name__ == "__main__":

    result = load_allianz_vehicles()

    print_report(
        result
    )

    print()

    if result.available:

        if len(result.vehicles) == 71:

            print(
                "OK - Allianz PDF obsahuje očekávaných 71 vozidel."
            )

        else:

            print(
                "POZOR - dokument uvádí 71 vozidel, "
                f"parser rozpoznal {len(result.vehicles)}."
            )
