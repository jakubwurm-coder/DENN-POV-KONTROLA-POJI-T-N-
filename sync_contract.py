"""Full-source, versioned completeness contract. Contains no network operations."""
import hashlib
import json
from audit_validation import validate_complete_audit

def digest(value):
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True,
        separators=(',', ':')).encode('utf-8')).hexdigest()

def make_manifest(snapshot):
    audit = snapshot.get('audit') or {}
    validate_complete_audit(audit)
    rows = snapshot.get('results') or []
    return {'version': 1, 'sql_total': len(audit['sql']),
            'sql_oids_sha256': digest(sorted(str(x['oid']) for x in audit['sql'])),
            'results_count': len(rows), 'results_sha256': digest(rows),
            'inputs_sha256': digest(audit),
            'uniqa_rows': len(audit.get('uniqa') or []),
            'allianz_rows': len(audit.get('allianz') or [])}

def validate_snapshot(snapshot):
    supplied = snapshot.get('manifest')
    if not isinstance(supplied, dict) or supplied != make_manifest(snapshot):
        raise ValueError('Neúplná nebo poškozená synchronizace: nesouhlasí kontrolní otisky a počty.')
    keys = [(x.get('oid'), x.get('vin')) for x in snapshot.get('results') or []]
    if len(keys) != len(set(keys)):
        raise ValueError('Synchronizace obsahuje duplicitní výsledné klíče.')
