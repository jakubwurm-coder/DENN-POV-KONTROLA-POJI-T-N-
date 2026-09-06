from __future__ import annotations

from collections import Counter

from allianz import load_allianz_vehicles
from compare import compare_vehicles
from config import load_config
from report import (
    prepare_output,
    write_comparison,
    write_duplicates,
    write_tirbazar_snapshot,
)
from tirbazar import load_tirbazar_vehicles
from uniqa import load_uniqa_vehicles


def main() -> None:

    print()
    print("=" * 70)
    print("KONTROLA POJIŠTĚNÍ")
    print("TIRBAZAR -> UNIQA -> ALLIANZ")
    print("=" * 70)
    print()
    print(
        "Databáze TIRBazar je používána pouze pro čtení."
    )
    print(
        "Technická chyba zdroje nikdy neznamená 'nepojištěno'."
    )
    print()

    config = load_config()

    vehicles, duplicates = load_tirbazar_vehicles(
        config
    )

    active_count = sum(
        1
        for vehicle in vehicles
        if not vehicle.datum_prodeje
    )

    print(
        "Aktivních vozidel ke kontrole:",
        active_count,
    )

    uniqa = load_uniqa_vehicles()

    print()
    print("=" * 70)
    print("ALLIANZ")
    print("=" * 70)
    print()

    allianz = load_allianz_vehicles()

    if allianz.available:

        print("Allianz PDF: OK")

        print(
            "Načtených vozidel:",
            len(allianz.vehicles),
        )

        print(
            "Období:",
            f"{allianz.period_od} - {allianz.period_do}",
        )

    else:

        print(
            "Allianz PDF: NELZE NAČÍST"
        )

        print(
            allianz.error
        )

    results = compare_vehicles(
        tir=vehicles,
        uniqa=uniqa.vehicles,
        uniqa_available=uniqa.available,
        uniqa_error=uniqa.error,
        allianz=allianz.vehicles,
        allianz_available=allianz.available,
        allianz_error=allianz.error,
    )

    counts = Counter(
        result.status
        for result in results
    )

    ok_uniqa = sum(
        1
        for result in results
        if (
            result.status == "OK"
            and "UNIQA" in (
                result.detail or ""
            ).upper()
        )
    )

    ok_allianz = sum(
        1
        for result in results
        if (
            result.status == "OK"
            and "ALLIANZ" in (
                result.detail or ""
            ).upper()
        )
    )

    print()
    print("=" * 70)
    print("KONTROLA POJIŠTĚNÍ - SOUHRN")
    print("=" * 70)
    print()

    print(
        "AKTIVNÍ KE KONTROLE:",
        active_count,
    )

    print(
        "OK CELKEM:",
        counts.get("OK", 0),
    )

    print(
        "  OK - UNIQA:",
        ok_uniqa,
    )

    print(
        "  OK - ALLIANZ:",
        ok_allianz,
    )

    print(
        "CHYBÍ POJIŠTĚNÍ:",
        counts.get(
            "CHYBÍ V UNIQA",
            0,
        ),
    )

    print(
        "NEPOJIŠTĚNO, ALE DEPOZIT:",
        counts.get(
            "NEPOJIŠTĚNO, ALE DEPOZIT",
            0,
        ),
    )

    print(
        "PRODANÉ, ALE V UNIQA:",
        counts.get(
            "PRODANÉ, ALE V UNIQA",
            0,
        ),
    )

    print(
        "SPZ NESOUHLASÍ:",
        counts.get(
            "SPZ NESOUHLASÍ",
            0,
        ),
    )

    print(
        "NAVÍC V UNIQA:",
        counts.get(
            "NAVÍC V UNIQA",
            0,
        ),
    )

    print(
        "NELZE OVĚŘIT:",
        counts.get(
            "NELZE OVĚŘIT",
            0,
        ),
    )

    base = prepare_output()

    try:

        write_tirbazar_snapshot(
            vehicles,
            base,
        )

    except TypeError:

        active = [
            vehicle
            for vehicle in vehicles
            if not vehicle.datum_prodeje
        ]

        sold = [
            vehicle
            for vehicle in vehicles
            if vehicle.datum_prodeje
        ]

        write_tirbazar_snapshot(
            active,
            sold,
            base,
        )

    write_duplicates(
        duplicates,
        base,
    )

    comparison_path = write_comparison(
        results,
        base,
    )

    print()
    print(
        "Výstup kontroly:",
        comparison_path,
    )
    print()


if __name__ == "__main__":
    main()
