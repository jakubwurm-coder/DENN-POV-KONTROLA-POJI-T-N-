from __future__ import annotations

from typing import Any

from models import ComparisonResult, TirVehicle, UniqaVehicle
from normalize import normalize_spz, normalize_vin
from tirbazar import _is_effectively_sold, _is_sold_to_vans_renting


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


def _normalize_state(value: str) -> str:
    return " ".join(str(value or "").strip().upper().split())


def _is_absent_purchased(vehicle: TirVehicle) -> bool:
    return (
        _normalize_state(getattr(vehicle, "stav", ""))
        in {"NEPŘÍTOMNÉ", "NEPRITOMNE"}
        and bool(getattr(vehicle, "datum_vykupu", ""))
    )


def compare_vehicles(
    tir: list[TirVehicle],
    uniqa: list[UniqaVehicle],
    uniqa_available: bool,
    uniqa_error: str = "",
    allianz: list[Any] | None = None,
    allianz_available: bool = False,
    allianz_error: str = "",
    known_tir_vins: set[str] | None = None,
) -> list[ComparisonResult]:

    allianz = allianz or []
    known_tir_vins = {normalize_vin(x) for x in known_tir_vins} if known_tir_vins is not None else None

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

        # Prodej má vždy přednost před textem DEPOZIT. Kromě aktuálního stavu
        # PRODANÉ respektujeme i prodej novější než poslední výkup; tím
        # odfiltrujeme staré prodané karty se zapomenutou poznámkou DEPOZIT.
        sold = _is_effectively_sold(vehicle)

        # ====================================================
        # DEPOZIT
        #
        # SQL/TIRBazar říká, že vozidlo NEMÁ BÝT POJIŠTĚNO.
        # Teprve UNIQA + Allianz potvrdí skutečný stav.
        # ====================================================
        if (
            not sold
            and _normalize_state(getattr(vehicle, "stav", "")) in {
                "VYKOUPENÉ", "VYKOUPENE",
                "REZERVOVANÉ", "REZERVOVANE",
            }
            and _is_deposit_note(vehicle.poznamky)
        ):
            allianz_vehicle = None
            if allianz_available:
                allianz_vehicle = allianz_by_vin.get(vin)

            if uniqa_available and uniqa_vehicle:
                results.append(ComparisonResult(
                    oid=vehicle.oid, vin=vin, tir_spz=tir_spz,
                    uniqa_spz=normalize_spz(uniqa_vehicle.spz),
                    status="DEPOZIT, ALE POJIŠTĚNÉ",
                    detail=("Depozit je pojištěn současně v UNIQA a ALLIANZ, správně má být NEPOJIŠTĚNO." if allianz_vehicle is not None else "Vozidlo je v depozitu, ale je stále pojištěné v UNIQA – správný stav je NEPOJIŠTĚNO."),
                    datum_vykupu=vehicle.datum_vykupu, datum_prodeje="",
                ))
                continue

            if allianz_vehicle is not None:
                results.append(ComparisonResult(
                    oid=vehicle.oid, vin=vin, tir_spz=tir_spz, uniqa_spz="",
                    status="DEPOZIT, ALE POJIŠTĚNÉ",
                    detail="Vozidlo je v depozitu, ale je stále pojištěné v ALLIANZ – správný stav je NEPOJIŠTĚNO.",
                    datum_vykupu=vehicle.datum_vykupu, datum_prodeje="",
                ))
                continue

            if not uniqa_available or not allianz_available:
                results.append(ComparisonResult(
                    oid=vehicle.oid, vin=vin, tir_spz=tir_spz, uniqa_spz="",
                    status="NELZE OVĚŘIT",
                    detail="Vozidlo je v depozitu a má být NEPOJIŠTĚNO, ale nelze ověřit oba zdroje pojištění.",
                    datum_vykupu=vehicle.datum_vykupu, datum_prodeje="",
                ))
                continue

            results.append(ComparisonResult(
                oid=vehicle.oid, vin=vin, tir_spz=tir_spz, uniqa_spz="",
                status="NEPOJIŠTĚNO, ALE DEPOZIT",
                detail="Vozidlo je v depozitu a nebylo nalezeno v UNIQA ani ALLIANZ – správně NEPOJIŠTĚNO.",
                datum_vykupu=vehicle.datum_vykupu, datum_prodeje="",
            ))
            continue

        # ====================================================
        # NEPŘÍTOMNÉ + VYKOUPENÉ
        #
        # Vozidlo zůstává v aktivním počtu, ale správný stav
        # je NEPOJIŠTĚNO. Pokud je nalezené v UNIQA nebo Allianz,
        # jde o stav vyžadující kontrolu.
        # ====================================================

        if _is_absent_purchased(vehicle):
            allianz_vehicle = None
            allianz_match = ""

            if allianz_available:
                allianz_vehicle = allianz_by_vin.get(vin)
                if allianz_vehicle is not None:
                    allianz_match = "VIN"

            if uniqa_available and uniqa_vehicle:
                results.append(
                    ComparisonResult(
                        oid=vehicle.oid,
                        vin=vin,
                        tir_spz=tir_spz,
                        uniqa_spz=normalize_spz(uniqa_vehicle.spz),
                        status="NEPŘÍTOMNÉ, ALE POJIŠTĚNÉ",
                        detail=("Nepřítomné pojištěné současně v UNIQA a ALLIANZ, správně NEPOJIŠTĚNO." if allianz_vehicle is not None else "Vykoupené, nepřítomné, ale pojištěné – správný stav je NEPOJIŠTĚNO."),
                        datum_vykupu=vehicle.datum_vykupu,
                        datum_prodeje="",
                    )
                )
                continue

            if allianz_vehicle is not None:
                results.append(
                    ComparisonResult(
                        oid=vehicle.oid,
                        vin=vin,
                        tir_spz=tir_spz,
                        uniqa_spz="",
                        status="NEPŘÍTOMNÉ, ALE POJIŠTĚNÉ",
                        detail=("Nepřítomné pojištěné současně v UNIQA a ALLIANZ, správně NEPOJIŠTĚNO." if allianz_vehicle is not None else "Vykoupené, nepřítomné, ale pojištěné – správný stav je NEPOJIŠTĚNO."),
                        datum_vykupu=vehicle.datum_vykupu,
                        datum_prodeje="",
                    )
                )
                continue

            if not uniqa_available or not allianz_available:
                detail = (
                    "Vozidlo má evidovaný výkup a stav NEPŘÍTOMNÉ. "
                    "Správný stav je NEPOJIŠTĚNO, ale nelze bezpečně potvrdit, "
                    "že není pojištěné, protože některý zdroj pojištění není dostupný."
                )
                if uniqa_error:
                    detail += f" UNIQA chyba: {uniqa_error}"
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

            results.append(
                ComparisonResult(
                    oid=vehicle.oid,
                    vin=vin,
                    tir_spz=tir_spz,
                    uniqa_spz="",
                    status="NEPŘÍTOMNÉ, ALE NEPOJIŠTĚNÉ",
                    detail="Vozidlo NEPŘÍTOMNÉ - NEMÁ POJIŠTĚNÍ",
                    datum_vykupu=vehicle.datum_vykupu,
                    datum_prodeje="",
                )
            )
            continue

        # ====================================================
        # PRODANÉ
        # ====================================================

        if sold and not _is_sold_to_vans_renting(vehicle):
            allianz_vehicle = allianz_by_vin.get(vin) if allianz_available else None

            # Prodané vozidlo už nemá být pojištěné. Nezahazujeme ho ale
            # před porovnáním: pokud zůstalo v UNIQA nebo Allianz, jde o
            # pojištění navíc a musí se zobrazit jako případ ke kontrole.
            if uniqa_available and uniqa_vehicle:
                results.append(
                    ComparisonResult(
                        oid=vehicle.oid,
                        vin=vin,
                        tir_spz=tir_spz,
                        uniqa_spz=normalize_spz(uniqa_vehicle.spz),
                        status="PRODANÉ, ALE POJIŠTĚNÉ",
                        detail=(
                            "Vozidlo má v TIRBazar evidovaný prodej, "
                            "ale VIN je stále veden mezi aktivními vozidly UNIQA. "
                            + ("Pojištění je vedeno navíc v UNIQA i ALLIANZ." if allianz_vehicle is not None else "Pojištění je vedeno navíc.")
                        ),
                        datum_vykupu=vehicle.datum_vykupu,
                        datum_prodeje=vehicle.datum_prodeje,
                    )
                )
                continue

            allianz_vehicle = None
            if allianz_available:
                allianz_vehicle = allianz_by_vin.get(vin)

            if allianz_vehicle is not None:
                results.append(
                    ComparisonResult(
                        oid=vehicle.oid,
                        vin=vin,
                        tir_spz=tir_spz,
                        uniqa_spz="",
                        status="PRODANÉ, ALE POJIŠTĚNÉ",
                        detail=(
                            "Vozidlo má v TIRBazar evidovaný prodej, "
                            "ale je stále vedeno mezi aktivně pojištěnými vozidly ALLIANZ. "
                            "Pojištění je vedeno navíc."
                        ),
                        datum_vykupu=vehicle.datum_vykupu,
                        datum_prodeje=vehicle.datum_prodeje,
                    )
                )
                continue

            # Správné NEPOJIŠTĚNO lze potvrdit jen tehdy, když byly oba
            # zdroje dostupné. Při výpadku jednoho zdroje nesmíme absenci
            # pojištění pouze předpokládat.
            if not uniqa_available or not allianz_available:
                detail = (
                    "Vozidlo je prodané a má být NEPOJIŠTĚNO, ale nelze "
                    "bezpečně potvrdit absenci pojištění, protože některý "
                    "zdroj pojištění není dostupný."
                )
                if uniqa_error:
                    detail += f" UNIQA chyba: {uniqa_error}"
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
                        datum_prodeje=vehicle.datum_prodeje,
                    )
                )
                continue

            # Oba zdroje byly dostupné a vozidlo nebylo nalezeno ani v jednom:
            # prodané vozidlo je tedy správně nepojištěné a nevytváří problém.
            continue

        # ====================================================
        # 1. UNIQA
        # ====================================================

        if uniqa_available and uniqa_vehicle and allianz_available and vin in allianz_by_vin:
            results.append(ComparisonResult(
                oid=vehicle.oid, vin=vin, tir_spz=tir_spz,
                uniqa_spz=normalize_spz(uniqa_vehicle.spz),
                status="DVOJÍ POJIŠTĚNÍ",
                detail="VIN je nalezen v UNIQA i ALLIANZ. Prověřte souběh pojištění.",
                datum_vykupu=vehicle.datum_vykupu, datum_prodeje="",
            ))
            continue

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
                        detail="Pojištění nalezeno UNIQA",
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

            detail = "Pojištění nalezeno ALLIANZ"

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

        tir_vins = known_tir_vins if known_tir_vins is not None else set(tir_by_vin.keys())

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

    if allianz_available:
        tir_vins = known_tir_vins if known_tir_vins is not None else set(tir_by_vin.keys())
        for vin, insured in allianz_by_vin.items():
            if vin not in tir_vins:
                results.append(ComparisonResult(
                    oid=None, vin=vin, tir_spz="", uniqa_spz="",
                    status="NAVÍC V ALLIANZ",
                    detail="VIN je v ALLIANZ, ale není v kompletní evidenci TIRBazar.",
                    datum_vykupu="", datum_prodeje="",
                ))

    order = {
        "DVOJÍ POJIŠTĚNÍ": 1,
        "NAVÍC V ALLIANZ": 5,
        "CHYBÍ V UNIQA": 1,
        "NEPŘÍTOMNÉ, ALE POJIŠTĚNÉ": 2,
        "NEPŘÍTOMNÉ, ALE NEPOJIŠTĚNÉ": 9,
        "NEPOJIŠTĚNO, ALE DEPOZIT": 3,
        "DEPOZIT, ALE POJIŠTĚNÉ": 2,
        "PRODANÉ, ALE POJIŠTĚNÉ": 3,
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
