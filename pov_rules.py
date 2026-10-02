from __future__ import annotations

POV_RULES_VERSION = "2026-10-02.1"

CANONICAL_RAW_STATUSES = (
    "OK",
    "CHYBÍ V UNIQA",
    "NEPŘÍTOMNÉ, ALE POJIŠTĚNÉ",
    "NEPŘÍTOMNÉ, ALE NEPOJIŠTĚNÉ",
    "NEPOJIŠTĚNO, ALE DEPOZIT",
    "DEPOZIT, ALE POJIŠTĚNÉ",
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
    "NEPOJIŠTĚNO, ALE DEPOZIT": "Depozit · nepojištěno",
    "DEPOZIT, ALE POJIŠTĚNÉ": "Depozit · pojištěno",
    "PRODANÉ, ALE POJIŠTĚNÉ": "Prodané · pojištěno",
    "NAVÍC V UNIQA": "Pojištění navíc",
    "SPZ NESOUHLASÍ": "SPZ nesouhlasí",
    "NELZE OVĚŘIT": "Nelze ověřit",
}

PROBLEM_STATUSES = {
    "CHYBÍ V UNIQA",
    "NEPŘÍTOMNÉ, ALE POJIŠTĚNÉ",
    "DEPOZIT, ALE POJIŠTĚNÉ",
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
    "current_state_is_authoritative": False,
    "sale_date_is_primary": True,
    "sold_state_is_fallback": True,
    "purchased_expected": "POJIŠTĚNO",
    "sold_expected": "NEPOJIŠTĚNO",
    "absent_with_purchase_expected": "NEPOJIŠTĚNO",
    "purchased_deposit_expected": "NEPOJIŠTĚNO",
    "vin_is_primary_identifier": True,
    "statuses": list(CANONICAL_RAW_STATUSES),
    "labels": DISPLAY_LABELS,
}
