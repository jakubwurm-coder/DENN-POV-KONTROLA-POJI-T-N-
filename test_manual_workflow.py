"""Integration regressions run only in a fresh disposable PostgreSQL schema."""
import copy
import os
import unittest
import uuid
from concurrent.futures import ThreadPoolExecutor
from unittest.mock import patch
import cloud_app as c
from status_projection import ISSUE_STATUSES, project_status
from vehicle_workflow import FOLLOWUP, MANUAL_OK

class ProjectionTests(unittest.TestCase):
    def test_existing_legacy_manual_ok_is_preserved(self):
        row={'vin':'LEGACY_OK','status_raw':'CHYBÍ V UNIQA','status':'CHYBÍ V UNIQA'}
        with patch.object(c,'_annotations_load',return_value={'LEGACY_OK':{'workflow_status':'V POŘÁDKU'}}):
            public=c._public_state({'results':[row]})
        self.assertEqual(public['summary']['new_problems'],0)
        self.assertEqual(public['summary']['manual_ok'],1)
        self.assertEqual(project_status(public)['problems'],[])
        self.assertEqual(public['results'][0]['workflow_status'],'V POŘÁDKU')
        self.assertEqual(public['results'][0]['workflow_updated_by'],'')

    def test_all_issue_types(self):
        rows = [dict(vin=f'{i}-{st}', status_raw=raw, status=raw, workflow_status=st)
                for i,raw in enumerate(ISSUE_STATUSES) for st in ('',FOLLOWUP,MANUAL_OK,'VYŘEŠENO')]
        annotations = {r['vin'].upper():r for r in rows}
        original = copy.deepcopy(rows)
        with patch.object(c,'_annotations_load',return_value=annotations):
            public = c._public_state({'results':rows})
        self.assertEqual(public['summary']['new_problems'],len(ISSUE_STATUSES))
        self.assertEqual(public['summary']['followup'],len(ISSUE_STATUSES)*2)
        self.assertEqual(public['summary']['manual_ok'],len(ISSUE_STATUSES))
        self.assertEqual(len(project_status(public)['problems']),len(ISSUE_STATUSES))
        self.assertEqual(rows,original)
        self.assertTrue(all(r['status']==r['status_raw'] for r in public['results']))

@unittest.skipUnless(os.getenv('POV_TEST_DATABASE_URL'),'Set POV_TEST_DATABASE_URL for disposable Postgres tests')
class DatabaseTests(unittest.TestCase):
    @classmethod
    def connect(cls):
        return cls.pg.connect(cls.dsn,options=f'-c search_path={cls.schema}')
    @classmethod
    def setUpClass(cls):
        import psycopg
        cls.pg=psycopg
        cls.dsn=os.environ['POV_TEST_DATABASE_URL']
        cls.schema='workflow_test_'+uuid.uuid4().hex
        with cls.pg.connect(cls.dsn,autocommit=True) as conn:
            conn.execute(f'CREATE SCHEMA {cls.schema}')
        cls.patches=[patch.object(c,'_db_connect',cls.connect),patch.object(c,'_DATABASE_URL',cls.dsn),patch.object(c,'_db_schema_ready',False)]
        for p in cls.patches:p.start()
        with cls.connect() as conn:
            conn.execute("CREATE TABLE denni_pov_annotations (vehicle_key TEXT PRIMARY KEY, note TEXT NOT NULL DEFAULT '', workflow_status TEXT NOT NULL DEFAULT '', updated_at TEXT NOT NULL)")
            conn.execute("INSERT INTO denni_pov_annotations VALUES ('LEGACY','old note','VYŘEŠENO','24.10.2026 10:00:00')")
            c._db_init(conn.cursor())
    @classmethod
    def tearDownClass(cls):
        for p in reversed(cls.patches):p.stop()
        with cls.pg.connect(cls.dsn,autocommit=True) as conn:
            conn.execute(f'DROP SCHEMA {cls.schema} CASCADE')
    def row(self,key):return dict(vin=key,status_raw='CHYBÍ V UNIQA',status='Chybí pojištění',detail='automatic finding')
    def test_migration_is_additive_idempotent(self):
        c._annotations_load_strict({'LEGACY_MIGRATION':{'workflow_status':'VYŘEŠENO','note':'old note'}})
        with self.connect() as conn:
            c._db_init_uncached(conn.cursor())
            c._db_init_uncached(conn.cursor())
        legacy=c._annotations_load_strict()['LEGACY_MIGRATION']
        self.assertEqual(legacy['workflow_status'],'VYŘEŠENO')
        self.assertEqual(legacy['note'],'old note')
        self.assertEqual(legacy['workflow_updated_by'],'')
    def test_transitions_authors_notes_reset(self):
        key='TRANSITIONS'; row=self.row(key)
        first=c._annotation_save(key,'investigate',FOLLOWUP,row,'alice')
        approval=c._annotation_save(key,'verified',MANUAL_OK,row,'bob')
        edit=c._annotation_save(key,'extra note',MANUAL_OK,row,'alice')
        self.assertEqual(edit['workflow_updated_at'],approval['workflow_updated_at'])
        self.assertEqual(edit['workflow_updated_by'],'bob')
        self.assertEqual(edit['updated_by'],'alice')
        c._annotation_save(key,'','',row,'alice')
        self.assertEqual(c._annotations_load_strict({key:first})[key]['workflow_status'],'')
        events=[e for e in c._annotation_history_load() if e['vehicle_key']==key]
        self.assertEqual(len(events),4)
        self.assertEqual({e['changed_by'] for e in events},{'alice','bob'})
        self.assertTrue(all(e['original_status']==row['status_raw'] for e in events))
    def test_audit_failure_rolls_back(self):
        row=self.row('ROLLBACK')
        c._annotation_save('ROLLBACK','before',FOLLOWUP,row,'alice')
        with self.connect() as conn:
            conn.execute("ALTER TABLE denni_pov_annotation_history ADD CONSTRAINT reject_test CHECK (new_note <> 'force failure')")
        try:
            with self.assertRaises(c.PersistenceUnavailable):
                c._annotation_save('ROLLBACK','force failure',MANUAL_OK,row,'bob')
            self.assertEqual(c._annotations_load_strict()['ROLLBACK']['workflow_status'],FOLLOWUP)
        finally:
            with self.connect() as conn:conn.execute('ALTER TABLE denni_pov_annotation_history DROP CONSTRAINT reject_test')
    def test_concurrent_first_write_audit_chain(self):
        def save(i):return c._annotation_save('CONCURRENT',str(i),FOLLOWUP,self.row('CONCURRENT'),f'user-{i}')
        with ThreadPoolExecutor(max_workers=4) as pool:list(pool.map(save,range(8)))
        with self.connect() as conn:
            chain=conn.execute("SELECT old_note,new_note FROM denni_pov_annotation_history WHERE vehicle_key='CONCURRENT' ORDER BY id").fetchall()
        self.assertEqual(len(chain),8)
        self.assertEqual(chain[0][0],'')
        self.assertTrue(all(a[1]==b[0] for a,b in zip(chain,chain[1:])))
    def test_endpoint_identity_and_failure(self):
        client=c.app.test_client(); data={'results':[self.row('API')],'summary':{},'annotations':{}}
        with patch.dict(c.app.config,SECRET_KEY='test',TESTING=True),patch.object(c,'_load_state',side_effect=lambda:copy.deepcopy(data)),patch.object(c,'_save_state',side_effect=lambda value:data.update(value)):
            def post(key='API',status=MANUAL_OK):return client.post('/api/result-meta',base_url='https://localhost',json=dict(key=key,workflow_status=status,actor='forged'))
            self.assertEqual(post().status_code,401)
            with client.session_transaction() as sess:
                sess['denni_pov_authenticated']=True; sess['denni_pov_username']='authenticated-user'
            self.assertEqual(post(status='BAD').status_code,400)
            self.assertEqual(post(key='UNKNOWN').status_code,404)
            saved=post();self.assertEqual(saved.status_code,200,saved.json)
            self.assertEqual(c._annotations_load_strict()['API']['workflow_updated_by'],'authenticated-user')
            with patch.object(c,'_annotation_save',side_effect=c.PersistenceUnavailable('offline')):
                failed=post(status=FOLLOWUP)
                self.assertEqual(failed.status_code,503);self.assertFalse(failed.json['persisted'])
    def test_legacy_note_edit_does_not_invent_confirmation_author(self):
        c._annotations_load_strict({'LEGACY_EDIT':{'workflow_status':'VYŘEŠENO','note':'old note'}})
        c._annotation_save('LEGACY_EDIT','edited note',FOLLOWUP,self.row('LEGACY_EDIT'),'alice')
        meta=c._annotations_load_strict()['LEGACY_EDIT']
        self.assertEqual(meta['workflow_updated_by'],'')
        self.assertEqual(meta['workflow_updated_at'],'')
        self.assertEqual(meta['updated_by'],'alice')
    def test_all_historical_issues_disappear_when_current_verdict_is_ok(self):
        for i,old_status in enumerate(ISSUE_STATUSES):
            key='RESOLVED'+str(i)
            with self.connect() as conn:
                conn.execute("INSERT INTO denni_pov_annotations (vehicle_key,note,workflow_status,updated_at,automatic_problem_status) VALUES (%s,'keep note','','old',%s)",(key,old_status))
            row=dict(self.row(key),status_raw='OK',status='OK',open_problem_status=old_status)
            public=c._public_state({'results':[row]})
            self.assertEqual(public['results'][0]['status_raw'],'OK')
            self.assertEqual(public['results'][0]['open_problem_status'],'')
            self.assertEqual(public['results'][0]['note'],'keep note')
            self.assertEqual(public['summary']['new_problems'],0)
            self.assertEqual(project_status(public)['problems'],[])
            # Reading the current verdict does not destroy stored historical data.
            self.assertEqual(c._annotations_load_strict()[key]['automatic_problem_status'],old_status)

    def test_changed_problem_does_not_inherit_old_manual_approval(self):
        row=self.row('CHANGED')
        c._annotation_save('CHANGED','keep note',MANUAL_OK,row,'alice')
        current=dict(row,status_raw='DVOJÍ POJIŠTĚNÍ')
        public=c._public_state({'results':[current]})
        self.assertEqual(public['results'][0]['workflow_status'],'')
        self.assertEqual(public['summary']['new_problems'],1)
        c._reconcile_current_workflow([current])
        meta=c._annotations_load_strict()['CHANGED']
        self.assertEqual(meta['workflow_status'],'')
        self.assertEqual(meta['note'],'keep note')

    def test_successful_check_archives_handling_of_resolved_or_absent_issues(self):
        old_rows=[self.row('INSURED_NOW'),dict(self.row('ONLY_ALLIANZ'),status_raw='DVOJÍ POJIŠTĚNÍ'),dict(self.row('EXTRA_REMOVED'),status_raw='NAVÍC V UNIQA')]
        for row in old_rows:
            c._annotation_save(row['vin'],'keep note',FOLLOWUP,row,'alice')
        c._run_history_save({'results':old_rows,'finished_at':'26.10.2026 22:00:00'})
        current=[dict(old_rows[0],status='OK',status_raw='OK',pojistovna='UNIQA'),dict(old_rows[1],status='OK',status_raw='OK',pojistovna='ALLIANZ')]
        c._reconcile_current_workflow(current)
        public=c._public_state({'results':current})
        self.assertEqual(public['summary']['new_problems'],0)
        self.assertEqual(public['summary']['followup'],0)
        for old in old_rows:
            meta=c._annotations_load_strict()[old['vin']]
            self.assertEqual(meta['workflow_status'],'')
            self.assertEqual(meta['note'],'keep note')
            events=[e for e in c._annotation_history_load() if e['vehicle_key']==old['vin']]
            self.assertTrue(any(e['changed_by']=='alice' for e in events))
            self.assertTrue(any(e['changed_by'].startswith('SYSTÉM') and e['new_workflow_status']=='' for e in events))
        with self.connect() as conn:
            stored=conn.execute("SELECT results FROM denni_pov_run_history ORDER BY id DESC LIMIT 1").fetchone()[0]
        self.assertEqual(stored,old_rows)
        # The same problem appearing later is a new, unhandled case.
        reappeared=c._public_state({'results':[old_rows[2]]})
        self.assertEqual(reappeared['summary']['new_problems'],1)
        self.assertEqual(reappeared['results'][0]['workflow_status'],'')

    def test_legacy_approval_cannot_revive_after_previously_resolved_episode(self):
        row=self.row('LEGACY_EPISODE')
        c._annotation_save(row['vin'],'keep note',MANUAL_OK,row,'alice')
        healthy=dict(row,status_raw='OK',status='OK')
        previous=c._default_state();previous.update(results=[healthy],summary={'active':1},finished_at='26.10.2026 22:00:00')
        c._run_history_save(previous)
        payload=dict(results=[row],summary={'active':1},sources={'tirbazar':{'state':'ok'}},agent={'id':'VCSERVER'},running=False,finished_at='26.10.2026 22:30:00')
        captured={}
        with patch.object(c,'_authorized',return_value=True),patch.object(c,'_load_state',return_value=previous),patch.object(c,'_save_state',side_effect=lambda value:captured.update(value)),patch.object(c,'_kostka_start'),patch.object(c,'_send_push_for_state',return_value={'sent':0}):
            response=c.app.test_client().post('/api/sync',json=payload)
        self.assertEqual(response.status_code,200,response.json)
        public=c._public_state(captured)
        self.assertEqual(public['results'][0]['workflow_status'],'')
        self.assertEqual(public['summary']['new_problems'],1)
        self.assertEqual(c._annotations_load_strict()[row['vin']]['note'],'keep note')

    def test_failed_check_does_not_archive_existing_workflow(self):
        row=self.row('FAILED_CHECK')
        c._annotation_save(row['vin'],'keep note',FOLLOWUP,row,'alice')
        state=c._default_state();state.update(results=[row],summary={'active':1})
        payload=dict(results=[],summary={},sources={},agent={'id':'VCSERVER'},running=False,error='SQL unavailable')
        with patch.object(c,'_authorized',return_value=True),patch.object(c,'_load_state',return_value=state),patch.object(c,'_save_state'):
            response=c.app.test_client().post('/api/sync',json=payload)
        self.assertEqual(response.status_code,200,response.json)
        self.assertEqual(c._annotations_load_strict()[row['vin']]['workflow_status'],FOLLOWUP)

    def test_handled_problems_do_not_send_push(self):
        rows=[dict(self.row('PUSH1'),workflow_status=FOLLOWUP),dict(self.row('PUSH2'),workflow_status=MANUAL_OK)]
        with patch.object(c,'_public_state',return_value={'results':rows,'summary':{}}),patch.object(c,'_db_connect') as db:
            self.assertEqual(c._send_push_for_state({})['sent'],0)
            db.assert_not_called()
    def test_real_sync_keeps_durable_workflow(self):
        row=self.row('SYNC')
        meta=c._annotation_save('SYNC','retained',FOLLOWUP,row,'alice')
        state=c._default_state()
        state.update(results=[row], summary={'active':1}, finished_at='25.10.2026 10:00:00')
        payload=dict(results=[dict(row)],summary={'active':1},
                     sources={'tirbazar':{'state':'ok'}},agent={'id':'VCSERVER'},running=False,
                     finished_at='25.10.2026 12:00:00',annotations={'SYNC':{'workflow_status':''}})
        with patch.object(c,'_authorized',return_value=True),patch.object(c,'_load_state',side_effect=lambda:copy.deepcopy(state)),patch.object(c,'_save_state',side_effect=lambda value:state.update(value)),patch.object(c,'_kostka_start'),patch.object(c,'_send_push_for_state',return_value={'sent':0}):
            response=c.app.test_client().post('/api/sync',json=payload)
        self.assertEqual(response.status_code,200,response.json)
        public=c._public_state(state)
        self.assertEqual(public['results'][0]['workflow_status'],FOLLOWUP)
        self.assertEqual(public['results'][0]['workflow_updated_by'],'alice')
        self.assertEqual(public['results'][0]['workflow_updated_at'],meta['workflow_updated_at'])
        self.assertEqual(public['results'][0]['status_raw'],'CHYBÍ V UNIQA')
    def test_next_check_and_restart_keep_manual_state(self):
        row=self.row('NEXTCHECK')
        meta=c._annotation_save('NEXTCHECK','checked',MANUAL_OK,row,'alice')
        # Projection over entirely new automatic rows after a process restart.
        with patch.object(c,'_db_schema_ready',False):
            public=c._public_state({'results':[dict(row)]})
        result=public['results'][0]
        self.assertEqual(result['status_raw'],'CHYBÍ V UNIQA')
        self.assertEqual(result['workflow_status'],MANUAL_OK)
        self.assertEqual(result['workflow_updated_by'],'alice')
        self.assertEqual(result['workflow_updated_at'],meta['workflow_updated_at'])
        self.assertEqual(public['summary']['new_problems'],0)

if __name__=='__main__':unittest.main()
