"""Completeness contract for the immutable SQL/provider comparison export."""
from collections import Counter


def validate_complete_audit(audit):
    rows = audit.get("sql") or []
    results = audit.get("results")
    counts = audit.get("counts") or {}
    if audit.get("schema_version") != 2 or not isinstance(results, list):
        raise ValueError("Agent nemá úplné porovnání všech SQL stavů. Aktualizujte agenta a spusťte novou kontrolu.")
    oids = [str(row.get("oid")) for row in rows if row.get("oid") is not None]
    result_oids = [str(row.get("oid")) for row in results if row.get("oid") is not None]
    if (not rows or len(rows) != counts.get("sql_total")
            or len(rows) != counts.get("physical_audit_rows")
            or len(oids) != len(rows) or len(set(oids)) != len(oids)
            or Counter(oids) != Counter(result_oids)):
        raise ValueError("Audit není úplný: každý fyzický SQL OID musí mít právě jeden výsledek porovnání.")
    if any(not row.get("status_raw") for row in results):
        raise ValueError("Audit obsahuje výsledek bez pojistného stavu.")
