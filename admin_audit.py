"""Owner-only evidence and carefully scoped repair endpoints. SQL Server is never written."""
import gzip
import hashlib
import json
import os
from flask import jsonify, session

def install(app, cloud):
    def allowed():
        owners = {x.strip().casefold() for x in os.getenv('DENNI_POV_ADMIN_USERS', 'jakubwurm@vanscentre.com').split(',')}
        return str(session.get('denni_pov_username') or '').casefold() in owners

    def latest_source():
        with cloud._db_connect() as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT source_snapshot, snapshot_sha256, run_id FROM denni_pov_run_history WHERE source_snapshot IS NOT NULL AND error IS NULL ORDER BY to_timestamp(finished_at, 'DD.MM.YYYY HH24:MI:SS') DESC, id DESC LIMIT 1")
                row = cur.fetchone()
        if not row:
            return None
        raw = gzip.decompress(bytes(row[0]))
        if hashlib.sha256(raw).hexdigest() != row[1]:
            raise cloud.PersistenceUnavailable('Nesouhlasí otisk archivovaného snímku.')
        return json.loads(raw)

    cloud._latest_source_snapshot = latest_source

    @app.route('/api/admin/sql-diagnostics', methods=['GET', 'POST'])
    def sql_diagnostics():
        if not allowed():
            return jsonify(ok=False), 403
        with cloud._lock, cloud._state_transaction():
            state=cloud._load_state()
            if __import__('flask').request.method == 'GET':
                return jsonify(state.get('_sql_sample') or {})
            if state.get('_command') or state.get('running'):
                return jsonify(ok=False, message='Agent právě pracuje.'), 409
            import uuid
            command_id=uuid.uuid4().hex
            state['_sql_sample']={'id':command_id,'status':'pending'}
            state['_command']={'id':command_id,'action':'run_check','sql_only':True,'requested_at':cloud._now()}
            cloud._save_state(state)
        return jsonify(ok=True,id=command_id,status='pending'),202

    @app.get('/api/admin/audit-snapshot')
    def audit_snapshot():
        if not allowed():
            return jsonify(ok=False), 403
        with cloud._lock:
            state = cloud._load_state()
        with cloud._db_connect() as conn:
            with conn.cursor() as cur:
                cur.execute('SELECT pg_database_size(current_database())')
                size = cur.fetchone()[0]
                cur.execute("SELECT relname,n_live_tup,n_dead_tup FROM pg_stat_user_tables ORDER BY relname")
                tables = [dict(table=x[0], estimated_rows=x[1], dead_rows=x[2]) for x in cur.fetchall()]
                cur.execute("SELECT usename,usesuper FROM pg_user WHERE usename=current_user")
                role = cur.fetchone()
                cur.execute("SELECT tablename,indexname,indexdef FROM pg_indexes WHERE schemaname='public' ORDER BY tablename,indexname")
                indexes = [dict(table=x[0], name=x[1], definition=x[2]) for x in cur.fetchall()]
        return jsonify(ok=True, state=state, snapshot=latest_source(),
            annotations=cloud._annotations_load_strict(),
            annotation_history=cloud._annotation_history_load(5000),
            database=dict(size_bytes=size,tables=tables,indexes=indexes,
                          current_role=role[0] if role else '',superuser=bool(role and role[1])))

    @app.post('/api/admin/repair-outage-workflow')
    def repair_outage_workflow():
        if not allowed():
            return jsonify(ok=False), 403
        restored=[]; skipped=[]
        with cloud._lock, cloud._state_transaction():
            state=cloud._load_state()
            current={cloud._result_key(x):x for x in state.get('results') or []}
            with cloud._db_connect() as conn:
                with conn.cursor() as cur:
                    cur.execute("""SELECT id, vehicle_key, old_workflow_status
                        FROM denni_pov_annotation_history
                        WHERE changed_at_text='2026-11-02T17:31:31+01:00'
                          AND changed_by='SYSTÉM – automatická kontrola'
                          AND new_workflow_status=''
                          AND original_status IN ('NELZE OVĚŘIT','MIMO AKTUÁLNÍ VÝSLEDKY')
                        ORDER BY id""")
                    incidents=cur.fetchall()
                    for event_id,key,status in incidents:
                        cur.execute('SELECT id FROM denni_pov_annotation_history WHERE vehicle_key=%s ORDER BY id DESC LIMIT 1',(key,))
                        if cur.fetchone()[0] != event_id:
                            skipped.append(dict(vin=key,reason='Novější změna má přednost.')); continue
                        cur.execute('SELECT note,workflow_status FROM denni_pov_annotations WHERE vehicle_key=%s',(key,))
                        saved=cur.fetchone()
                        if not saved or saved[1]:
                            skipped.append(dict(vin=key,reason='Aktivní označení již existuje.')); continue
                        cur.execute('SELECT original_status,changed_by,changed_at_text FROM denni_pov_annotation_history WHERE vehicle_key=%s AND id<%s ORDER BY id DESC LIMIT 1',(key,event_id))
                        prior=cur.fetchone()
                        row=current.get(key)
                        if row and prior and row.get('status_raw') not in {prior[0],'NELZE OVĚŘIT'}:
                            skipped.append(dict(vin=key,reason='Změnila se věcná příčina.')); continue
                        meta=cloud._annotation_save(key,saved[0],status,row or dict(vin=key,status_raw=prior[0] if prior else ''),
                            actor='OPRAVA AUDITU – '+session['denni_pov_username'])
                        # Preserve the known original confirmation identity, never invent it.
                        cur.execute('UPDATE denni_pov_annotations SET workflow_updated_by=%s,workflow_updated_at=%s WHERE vehicle_key=%s',
                            ((prior[1] if prior else ''),(prior[2] if prior else ''),key))
                        restored.append(key)
        return jsonify(ok=True,restored=restored,skipped=skipped)
