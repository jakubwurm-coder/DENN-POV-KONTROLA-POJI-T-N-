from __future__ import annotations

import re


def normalize_vin(value: str | None) -> str:
    if value is None:
        return ""

    return re.sub(
        r"[^A-Z0-9]",
        "",
        str(value).strip().upper(),
    )


def normalize_spz(value: str | None) -> str:
    if value is None:
        return ""

    return re.sub(
        r"[^A-Z0-9]",
        "",
        str(value).strip().upper(),
    )


def vin_looks_standard(vin: str) -> bool:
    return len(vin) == 17
