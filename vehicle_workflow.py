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


ISSUE_STATUSES = frozenset({
    "CHYBÍ V UNIQA", "NEPŘÍTOMNÉ, ALE POJIŠTĚNÉ",
    "PRODANÉ, ALE POJIŠTĚNÉ", "DEPOZIT, ALE POJIŠTĚNÉ",
    "NAVÍC V UNIQA", "NAVÍC V ALLIANZ", "DVOJÍ POJIŠTĚNÍ",
    "SPZ NESOUHLASÍ", "NELZE OVĚŘIT",
})


def current_workflow_status(row, annotation=None):
    """Manual handling applies only to the currently observed problem."""
    annotation = row if annotation is None else annotation
    raw = str(row.get("status_raw") or row.get("status") or "").strip().upper()
    previous = str(annotation.get("automatic_problem_status") or "").strip().upper()
    if raw not in ISSUE_STATUSES or (previous in ISSUE_STATUSES and previous != raw):
        return ""
    return workflow_status(annotation)
