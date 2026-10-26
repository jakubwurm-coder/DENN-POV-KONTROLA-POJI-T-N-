"""Manual decisions are independent of the latest insurance verdict.

VYŘEŠENO is the historical orange acknowledgement, never a green approval.
Keep it readable without rewriting existing annotations or audit events.
"""
FOLLOWUP = "K DOŘEŠENÍ"
MANUAL_OK = "RUČNĚ OK"
FOLLOWUP_STATUSES = frozenset({FOLLOWUP, "VYŘEŠENO"})
MANUAL_OK_STATUSES = frozenset({MANUAL_OK, "V POŘÁDKU"})
HANDLED_STATUSES = FOLLOWUP_STATUSES | MANUAL_OK_STATUSES
ALLOWED_STATUSES = HANDLED_STATUSES | {""}


def workflow_status(row):
    return str(row.get("workflow_status") or "").strip().upper()


def is_handled(row):
    return workflow_status(row) in HANDLED_STATUSES


def is_manual_ok(row):
    return workflow_status(row) in MANUAL_OK_STATUSES


def is_followup(row):
    return workflow_status(row) in FOLLOWUP_STATUSES
