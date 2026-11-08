"""Attach insurance evidence to the exact physical SQL card, never just its VIN."""
def project_lookup_vehicle(vehicle, source):
    vehicle=dict(vehicle)
    source=source or {}
    audit=source.get('audit') or {}
    oid=vehicle.get('oid')
    exact=lambda rows:next((x for x in rows if str(x.get('oid'))==str(oid)),None)
    row=exact(audit.get('results') or [])
    sql=exact(audit.get('sql') or [])
    original=exact((audit.get('inputs') or {}).get('tirbazar') or [])
    if original:
        vehicle.update(znacka=original.get('znacka',''),model=original.get('model',''))
    if sql:
        vehicle['filter']={'decision':sql.get('zarazeni',''), 'expected':sql.get('ocekavani',''),
                           'reason':sql.get('duvod','')}
    vehicle['insurance']={'in_last_check':bool(row),'status':(row or {}).get('status_raw',''),
        'status_raw':(row or {}).get('status_raw',''),'detail':(row or {}).get('detail',''),
        'insurer':(row or {}).get('pojistovna',''),'spz_insurance':(row or {}).get('spz_uniqa',''),
        'last_check':source.get('finished_at','')}
    if not sql and any(x.startswith('__DELETED_ROW__|'+str(oid)+'|') for x in (audit.get('sql_diagnostics') or {}).get('lines') or []):
        vehicle['filter']={'decision':'SMAZANÁ SQL KARTA','expected':'MIMO POV',
                           'reason':'Karta má v TIRBazar vyplněný GCRecord a nevstupuje do aktuální kontroly.'}
    return vehicle
