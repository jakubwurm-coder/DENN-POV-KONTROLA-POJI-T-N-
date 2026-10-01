from __future__ import annotations

POV_RULES_VERSION = "2026-10-01.1"

CANONICAL_RAW_STATUSES = (
    "OK",
    "CHYBÍ V UNIQA",
    "NEPŘÍTOMNÉ, ALE POJIŠTĚNÉ",
    "NEPŘÍTOMNÉ, ALE NEPOJIŠTĚNÉ",
    "NEPOJIŠTĚNO, ALE DEPOZIT",
    "PRODANÉ, ALE POJIŠTĚNÉ",
    "NAVÍC V UNIQA",
    "SPZ NESOUHLASÍ",
    "NELZE OVĚŘIT",
)

DISPLAY_LABELS = {
    "OK": "Pojištění v pořádku",
    "CHYBÍ V UNIQA": "Chybí pojištění",
    "NEPŘÍTOMNÉ, ALE POJIŠTĚNÉ": "Nepřítomné · pojištěno",
    "NEPŘÍTOMNÉ, ALE NEPOJIŠTĚNÉ": "Nepřítomné · nepojištěno",
    "NEPOJIŠTĚNO, ALE DEPOZIT": "Depozit",
    "PRODANÉ, ALE POJIŠTĚNÉ": "Prodané · pojištěno",
    "NAVÍC V UNIQA": "Pojištění navíc",
    "SPZ NESOUHLASÍ": "SPZ nesouhlasí",
    "NELZE OVĚŘIT": "Nelze ověřit",
}

PROBLEM_STATUSES = {
    "CHYBÍ V UNIQA",
    "NEPŘÍTOMNÉ, ALE POJIŠTĚNÉ",
    "PRODANÉ, ALE POJIŠTĚNÉ",
    "NAVÍC V UNIQA",
    "SPZ NESOUHLASÍ",
    "NELZE OVĚŘIT",
}

ACTIVE_STATUSES = {
    "OK",
    "CHYBÍ V UNIQA",
    "NEPŘÍTOMNÉ, ALE POJIŠTĚNÉ",
    "NEPŘÍTOMNÉ, ALE NEPOJIŠTĚNÉ",
    "SPZ NESOUHLASÍ",
    "NELZE OVĚŘIT",
}

RULES_PUBLIC = {
    "version": POV_RULES_VERSION,
    "authority": "web",
    "current_state_is_authoritative": True,
    "sold_is_based_on_current_tirbazar_state_only": True,
    "purchased_expected": "POJIŠTĚNO",
    "sold_expected": "NEPOJIŠTĚNO",
    "absent_with_purchase_expected": "NEPOJIŠTĚNO",
    "vin_is_primary_identifier": True,
    "statuses": list(CANONICAL_RAW_STATUSES),
    "labels": DISPLAY_LABELS,
}
