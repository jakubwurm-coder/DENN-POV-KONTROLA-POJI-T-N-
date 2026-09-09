from __future__ import annotations

import csv
from datetime import datetime
from pathlib import Path
from typing import Iterable

from models import ComparisonResult, TirVehicle


OUTPUT_ROOT = Path(__file__).resolve().parent / "output"


def prepare_output() -> Path:
    """Create one timestamped output directory for a single check run."""
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    base = OUTPUT_ROOT / stamp
    base.mkdir(parents=True, exist_ok=True)
    return base


def _write_csv(path: Path, rows: Iterable[dict[str, object]], fieldnames: list[str]) -> Path:
    """Write an Excel-friendly CSV for Czech Windows/Excel.

    Czech Excel normally expects a semicolon as the list separator. UTF-8 BOM
    keeps Czech characters readable when the file is opened by double-click.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=fieldnames,
            extrasaction="ignore",
            delimiter=";",
            quoting=csv.QUOTE_MINIMAL,
        )
        writer.writeheader()
        for row in rows:
            writer.writerow(row)
    return path


def _vehicle_row(vehicle: TirVehicle) -> dict[str, object]:
    return {
        "oid": vehicle.oid,
        "vin": vehicle.vin,
        "spz": vehicle.spz,
        "stav": getattr(vehicle, "stav", "") or "",
        "zeme_puvodu": getattr(vehicle, "zeme_puvodu", "") or "",
        "datum_vykupu": vehicle.datum_vykupu,
        "datum_prodeje": vehicle.datum_prodeje,
        "poznamky": getattr(vehicle, "poznamky", "") or "",
    }


def write_tirbazar_snapshot(
    vehicles_or_active: list[TirVehicle],
    sold_or_base: list[TirVehicle] | Path,
    base: Path | None = None,
) -> Path:
    """Write TIRBazar snapshot.

    Supports both the current two-argument call ``(vehicles, base)`` and the
    older three-argument call ``(active, sold, base)`` used by previous builds.
    """
    if base is None:
        vehicles = list(vehicles_or_active)
        target_base = Path(sold_or_base)
    else:
        vehicles = list(vehicles_or_active) + list(sold_or_base)  # type: ignore[arg-type]
        target_base = Path(base)

    rows = [_vehicle_row(vehicle) for vehicle in vehicles]
    return _write_csv(
        target_base / "tirbazar_snapshot.csv",
        rows,
        [
            "oid",
            "vin",
            "spz",
            "stav",
            "zeme_puvodu",
            "datum_vykupu",
            "datum_prodeje",
            "poznamky",
        ],
    )


def write_duplicates(duplicates: list[list[TirVehicle]], base: Path) -> Path:
    rows: list[dict[str, object]] = []

    for group_no, group in enumerate(duplicates, start=1):
        for vehicle in group:
            row = _vehicle_row(vehicle)
            row["skupina"] = group_no
            rows.append(row)

    return _write_csv(
        Path(base) / "tirbazar_duplicate_vin.csv",
        rows,
        [
            "skupina",
            "oid",
            "vin",
            "spz",
            "stav",
            "zeme_puvodu",
            "datum_vykupu",
            "datum_prodeje",
            "poznamky",
        ],
    )


def write_comparison(results: list[ComparisonResult], base: Path) -> Path:
    rows = [
        {
            "status": result.status,
            "oid": "" if result.oid is None else result.oid,
            "vin": result.vin,
            "spz_tirbazar": result.tir_spz,
            "spz_pojistovna": result.uniqa_spz,
            "datum_vykupu": result.datum_vykupu,
            "datum_prodeje": result.datum_prodeje,
            "detail": result.detail,
        }
        for result in results
    ]

    return _write_csv(
        Path(base) / "kontrola_pojisteni.csv",
        rows,
        [
            "status",
            "oid",
            "vin",
            "spz_tirbazar",
            "spz_pojistovna",
            "datum_vykupu",
            "datum_prodeje",
            "detail",
        ],
    )
