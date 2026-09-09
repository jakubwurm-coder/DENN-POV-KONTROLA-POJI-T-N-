from __future__ import annotations

from typing import Any

from models import ComparisonResult, TirVehicle, UniqaVehicle
from normalize import normalize_spz, normalize_vin


def _build_allianz_indexes(
    vehicles: list[Any],
) -> tuple[dict[str, Any], dict[str, Any]]:

    by_vin: dict[str, Any] = {}
    by_spz: dict[str, Any] = {}

    for vehicle in vehicles:

        vin = normalize_vin(
            getattr(vehicle, "vin", "") or ""
        )

        spz = normalize_spz(
            getattr(vehicle, "spz", "") or ""
        )

        if vin:
            by_vin.setdefault(vin, vehicle)

        if spz:
            by_spz.setdefault(spz, vehicle)

    return by_vin, by_spz


def _is_deposit_note(text: str) -> bool:

    value = (
        str(text or "")
        .strip()
        .upper()
    )

    return "DEPOZIT" in value


def _short_note(text: str) -> str:

    value = " ".join(
        str(text or "").split()
    )

    if len(value) <= 180:
        return value

    return value[:177] + "..."


def compare_vehicles(
    tir: list[TirVehicle],
    uniqa: list[UniqaVehicle],
    uniqa_available: bool,
    uniqa_error: str = "",
    allianz: list[Any] | None = None,
    allianz_available: bool = False,
    allianz_error: str = "",
) -> list[ComparisonResult]:

    allianz = allianz or []

    results: list[ComparisonResult] = []

    tir_by_vin: dict[str, TirVehicle] = {}
    uniqa_by_vin: dict[str, UniqaVehicle] = {}

    for vehicle in tir:

        vin = normalize_vin(vehicle.vin)

        if vin:
            tir_by_vin[vin] = vehicle

    for vehicle in uniqa:

        vin = normalize_vin(vehicle.vin)

        if vin:
            uniqa_by_vin[vin] = vehicle

    allianz_by_vin, allianz_by_spz = _build_allianz_indexes(
        allianz
    )

    for vehicle in tir:

        vin = normalize_vin(vehicle.vin)
        tir_spz = normalize_spz(vehicle.spz)

        if not vin:
            continue

        uniqa_vehicle = uniqa_by_vin.get(vin)

        # ====================================================
        # PRODANÉ
        # ====================================================

        if vehicle.datum_prodeje:

            if uniqa_available and uniqa_vehicle:

                results.append(
                    ComparisonResult(
                        oid=vehicle.oid,
                        vin=vin,
                        tir_spz=tir_spz,
                        uniqa_spz=normalize_spz(
                            uniqa_vehicle.spz
                        ),
                        status="PRODANÉ, ALE V UNIQA",
                        detail=(
                            "Vozidlo má v TIRBazar DatumProdeje, "
                            "ale VIN je stále veden mezi aktivními "
                            "vozidly UNIQA."
                        ),
                        datum_vykupu=vehicle.datum_vykupu,
                        datum_prodeje=vehicle.datum_prodeje,
                    )
                )

            continue

        # ====================================================
        # 1. UNIQA
        # ====================================================

        if uniqa_available and uniqa_vehicle:

            uniqa_spz = normalize_spz(
                uniqa_vehicle.spz
            )

            if (
                tir_spz
                and uniqa_spz
                and tir_spz != uniqa_spz
            ):

                results.append(
                    ComparisonResult(
                        oid=vehicle.oid,
                        vin=vin,
                        tir_spz=tir_spz,
                        uniqa_spz=uniqa_spz,
                        status="SPZ NESOUHLASÍ",
                        detail=(
                            "Pojištění bylo nalezeno v UNIQA podle VIN, "
                            "ale SPZ v TIRBazar a UNIQA se liší. "
                            "VIN je hlavní identifikátor."
                        ),
                        datum_vykupu=vehicle.datum_vykupu,
                        datum_prodeje="",
                    )
                )

            else:

                results.append(
                    ComparisonResult(
                        oid=vehicle.oid,
                        vin=vin,
                        tir_spz=tir_spz,
                        uniqa_spz=uniqa_spz,
                        status="OK",
                        detail="Pojištění nalezeno v UNIQA.",
                        datum_vykupu=vehicle.datum_vykupu,
                        datum_prodeje="",
                    )
                )

            continue

        # ====================================================
        # 2. ALLIANZ
        # ====================================================

        allianz_vehicle = None
        allianz_match = ""

        if allianz_available:

            allianz_vehicle = allianz_by_vin.get(
                vin
            )

            if allianz_vehicle is not None:

                allianz_match = "VIN"

            elif tir_spz:

                allianz_vehicle = allianz_by_spz.get(
                    tir_spz
                )

                if allianz_vehicle is not None:
                    allianz_match = "SPZ"

        if allianz_vehicle is not None:

            policy = (
                getattr(
                    allianz_vehicle,
                    "pojistka",
                    "",
                )
                or ""
            )

            identifier = (
                getattr(
                    allianz_vehicle,
                    "identifier",
                    "",
                )
                or ""
            )

            poj_od = (
                getattr(
                    allianz_vehicle,
                    "poj_od",
                    "",
                )
                or ""
            )

            poj_do = (
                getattr(
                    allianz_vehicle,
                    "poj_do",
                    "",
                )
                or ""
            )

            detail = (
                f"Pojištění nalezeno v ALLIANZ podle {allianz_match}."
            )

            if policy:
                detail += f" Pojistka: {policy}."

            if identifier:
                detail += f" Evidence Allianz: {identifier}."

            if poj_od or poj_do:
                detail += (
                    f" Období: {poj_od or '?'} - {poj_do or '?'}."
                )

            results.append(
                ComparisonResult(
                    oid=vehicle.oid,
                    vin=vin,
                    tir_spz=tir_spz,
                    uniqa_spz="",
                    status="OK",
                    detail=detail,
                    datum_vykupu=vehicle.datum_vykupu,
                    datum_prodeje="",
                )
            )

            continue

        # ====================================================
        # TECHNICKÁ NEDOSTUPNOST
        # ====================================================

        if not uniqa_available:

            detail = (
                "UNIQA se nepodařilo technicky ověřit."
            )

            if allianz_available:
                detail += (
                    " Vozidlo nebylo nalezeno v Allianz."
                )
            else:
                detail += (
                    " Allianz také nebylo možné ověřit."
                )

            if uniqa_error:
                detail += f" UNIQA chyba: {uniqa_error}"

            results.append(
                ComparisonResult(
                    oid=vehicle.oid,
                    vin=vin,
                    tir_spz=tir_spz,
                    uniqa_spz="",
                    status="NELZE OVĚŘIT",
                    detail=detail,
                    datum_vykupu=vehicle.datum_vykupu,
                    datum_prodeje="",
                )
            )

            continue

        if not allianz_available:

            detail = (
                "VIN nebyl nalezen v UNIQA, ale Allianz "
                "nebylo možné načíst. Nelze bezpečně rozhodnout."
            )

            if allianz_error:
                detail += f" Allianz chyba: {allianz_error}"

            results.append(
                ComparisonResult(
                    oid=vehicle.oid,
                    vin=vin,
                    tir_spz=tir_spz,
                    uniqa_spz="",
                    status="NELZE OVĚŘIT",
                    detail=detail,
                    datum_vykupu=vehicle.datum_vykupu,
                    datum_prodeje="",
                )
            )

            continue

        # ====================================================
        # 3. DEPOZIT
        #
        # Kontrolujeme až poté, co není v UNIQA ani Allianz.
        # ====================================================

        if _is_deposit_note(
            vehicle.poznamky
        ):

            note = _short_note(
                vehicle.poznamky
            )

            results.append(
                ComparisonResult(
                    oid=vehicle.oid,
                    vin=vin,
                    tir_spz=tir_spz,
                    uniqa_spz="",
                    status="NEPOJIŠTĚNO, ALE DEPOZIT",
                    detail=(
                        "Vozidlo nebylo nalezeno v UNIQA ani Allianz, "
                        "ale v poznámce TIRBazar byl nalezen text DEPOZIT. "
                        f"Poznámka: {note}"
                    ),
                    datum_vykupu=vehicle.datum_vykupu,
                    datum_prodeje="",
                )
            )

            continue

        # ====================================================
        # 4. OPRAVDU CHYBÍ POJIŠTĚNÍ
        # ====================================================

        results.append(
            ComparisonResult(
                oid=vehicle.oid,
                vin=vin,
                tir_spz=tir_spz,
                uniqa_spz="",
                status="CHYBÍ V UNIQA",
                detail=(
                    "Aktivní vozidlo nebylo nalezeno v UNIQA "
                    "ani Allianz a poznámka TIRBazar neobsahuje "
                    "informaci o depozitu."
                ),
                datum_vykupu=vehicle.datum_vykupu,
                datum_prodeje="",
            )
        )

    # ========================================================
    # NAVÍC V UNIQA
    # ========================================================

    if uniqa_available:

        tir_vins = set(
            tir_by_vin.keys()
        )

        for vin, uniqa_vehicle in uniqa_by_vin.items():

            if vin in tir_vins:
                continue

            results.append(
                ComparisonResult(
                    oid=None,
                    vin=vin,
                    tir_spz="",
                    uniqa_spz=normalize_spz(
                        uniqa_vehicle.spz
                    ),
                    status="NAVÍC V UNIQA",
                    detail=(
                        "VIN je mezi aktivními vozidly UNIQA, "
                        "ale není mezi vozidly TIRBazar se stavem "
                        "Vykoupené nebo Rezervované určenými k POV kontrole."
                    ),
                    datum_vykupu="",
                    datum_prodeje="",
                )
            )

    order = {
        "CHYBÍ V UNIQA": 1,
        "NEPOJIŠTĚNO, ALE DEPOZIT": 2,
        "PRODANÉ, ALE V UNIQA": 3,
        "SPZ NESOUHLASÍ": 4,
        "NAVÍC V UNIQA": 5,
        "NELZE OVĚŘIT": 6,
        "OK": 10,
    }

    results.sort(
        key=lambda result: (
            order.get(
                result.status,
                99,
            ),
            result.vin or "",
        )
    )

    return results
