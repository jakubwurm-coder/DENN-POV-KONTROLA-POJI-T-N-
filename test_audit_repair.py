import copy
from datetime import datetime, timezone
import io
import json
import os
from pathlib import Path
import tempfile
import unittest
from types import SimpleNamespace as N
from unittest.mock import patch
import requests

import allianz
import uniqa
import cloud_app as c
import agent_outbox
from models import TirVehicle, UniqaVehicle
from compare import compare_vehicles
from sync_contract import make_manifest, validate_snapshot

VIN='WVWZZZ1JZXW000001'
def vehicle():return TirVehicle(1,VIN,'1AA1111','CZ','VYKOUPENÉ','2026-01-01')
def compare(u=(),a=(),**kw):
    return compare_vehicles([vehicle()],list(u),True,allianz=list(a),allianz_available=True,
        complete=True,as_of=datetime(2026,11,7,12,tzinfo=timezone.utc),**kw)
def payload(run=None):
    row=dict(oid=1,vin=VIN,status_raw='OK',status='OK',pov_active=True)
    value=dict(running=False,finished_at='07.11.2026 17:00:00',started_at='07.11.2026 16:59:00',
        agent={'id':'VCSERVER'},sources={key:{'state':'ok'} for key in ('tirbazar','uniqa','allianz')},
        summary={'active':1},results=[row],comparison_version=3,run_id=run or 'a'*32,message_seq=2,
        audit={'schema_version':2,'sql':[{'oid':1}], 'results':[row],
            'counts':{'sql_total':1,'physical_audit_rows':1},'uniqa':[],'allianz':[]})
    value['manifest']=make_manifest(value)
    return value

class InsuranceRepairTests(unittest.TestCase):
    def test_expired_and_future_policies_are_not_active(self):
        for start,end in [('2020-01-01','2020-01-02'),('2099-01-01','')]:
            result=compare([UniqaVehicle(VIN,'1AA1111','p',start,end)])[0]
            self.assertEqual(result.status,'CHYBÍ V UNIQA')
            self.assertEqual(result.insurer,'')
    def test_date_end_is_inclusive_in_prague(self):
        result=compare([UniqaVehicle(VIN,'1AA1111','p','2026-11-07','2026-11-07')])[0]
        self.assertEqual(result.status,'OK')
    def test_invalid_interval_is_unknown(self):
        self.assertEqual(compare([UniqaVehicle(VIN,'1AA1111','p','bad-date','')])[0].status,'NELZE OVĚŘIT')
    def test_plate_fallback_only_when_provider_has_no_vin(self):
        policy=N(vin='',spz='1AA1111',poj_od='',poj_do='')
        self.assertEqual(compare(a=[policy])[0].status,'OK')
        policy.vin='WVWZZZ1JZXW999999'
        self.assertEqual(next(r for r in compare(a=[policy]) if r.oid==1).status,'CHYBÍ V UNIQA')
    def test_duplicate_order_does_not_change_verdict(self):
        policies=[UniqaVehicle(VIN,'1AA1111','same'),UniqaVehicle(VIN,'2BB2222','same')]
        self.assertEqual(compare(policies),compare(list(reversed(policies))))
        self.assertEqual(compare(policies)[0].status,'SPZ NESOUHLASÍ')
    def test_partial_vin_failure_is_unknown(self):
        self.assertEqual(compare(uncertain_uniqa_vins={VIN})[0].status,'NELZE OVĚŘIT')
    def test_allianz_rejects_maintenance_html(self):
        response=requests.Response();response.status_code=200;response._content=b'<html>maintenance</html>'
        with patch.object(allianz.requests,'get',return_value=response):
            self.assertFalse(allianz.load_allianz_vehicles().available)
    def test_uniqa_maintenance_is_not_empty_result(self):
        response=requests.Response();response.status_code=200;response._content=b'<html>maintenance</html>'
        with patch.object(uniqa,'load_active_list',return_value=response):
            with self.assertRaises(RuntimeError):uniqa._lookup_active_vin(N(),VIN)
    def test_integrity_contract_rejects_missing_or_modified_rows(self):
        value=payload();validate_snapshot(value)
        value['results'][0]['status_raw']='CHYBÍ V UNIQA'
        with self.assertRaises(ValueError):validate_snapshot(value)
    def test_durable_outbox_keeps_failed_message_and_retries_once(self):
        with tempfile.TemporaryDirectory() as root,patch.dict(os.environ,DENNI_POV_OUTBOX=root):
            agent_outbox.enqueue(payload())
            with self.assertRaises(requests.Timeout):agent_outbox.flush(lambda s: (_ for _ in ()).throw(requests.Timeout()))
            self.assertEqual(len(agent_outbox.pending()),1)
            received=[];agent_outbox.flush(received.append)
            self.assertEqual(len(received),1);self.assertEqual(agent_outbox.pending(),[])
    def test_csv_auth_and_expired_old_token(self):
        client=c.app.test_client()
        self.assertEqual(client.get('/dmsdata').status_code,401)
        with patch.dict(os.environ,{'SYNC_TOKEN':'new','SYNC_TOKEN_PREVIOUS':'old','SYNC_TOKEN_PREVIOUS_UNTIL':'1'}):
            with c.app.test_request_context(headers={'Authorization':'Bearer old'}):self.assertFalse(c._token_authorized())
    def test_credential_challenge_is_bound_to_secret_and_single_use(self):
        import hashlib,hmac,time
        key=b'private-test-bootstrap-key'
        env={'SYNC_TOKEN':'new-test-credential','DENNI_POV_BOOTSTRAP_KEY':key.hex(),
             'DENNI_POV_BOOTSTRAP_SALT':'00'*16,'DENNI_POV_BOOTSTRAP_UNTIL':str(time.time()+60)}
        with patch.dict(os.environ,env):
            client=c.app.test_client();challenge=client.get('/api/agent/credential-challenge?agent=VCSERVER').json
            nonce=challenge['nonce'];proof=hmac.new(key,(nonce+':VCSERVER').encode(),hashlib.sha256).hexdigest()
            claim={'agent':'VCSERVER','nonce':nonce,'proof':proof}
            response=client.post('/api/agent/credential-claim',json=claim)
            self.assertEqual(response.status_code,200)
            self.assertEqual(response.json['token'],'new-test-credential')
            self.assertEqual(client.post('/api/agent/credential-claim',json=claim).status_code,403)

@unittest.skipUnless(os.getenv('POV_TEST_DATABASE_URL'),'Disposable PostgreSQL required')
class PublicationDatabaseTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        import psycopg,uuid
        cls.pg=psycopg;cls.dsn=os.environ['POV_TEST_DATABASE_URL'];cls.schema='publication_'+uuid.uuid4().hex
        with psycopg.connect(cls.dsn,autocommit=True) as con:con.execute('CREATE SCHEMA '+cls.schema)
        cls.patches=[patch.object(c,'_db_connect',cls.connect),patch.object(c,'_DATABASE_URL',cls.dsn),patch.object(c,'_db_schema_ready',False)]
        for p in cls.patches:p.start()
        with cls.connect() as con:c._db_init(con.cursor())
    @classmethod
    def connect(cls):
        active=c._transaction_connection.get()
        if active is not None:return c._BorrowedConnection(active)
        return cls.pg.connect(cls.dsn,options='-c search_path='+cls.schema)
    @classmethod
    def tearDownClass(cls):
        for p in reversed(cls.patches):p.stop()
        with cls.pg.connect(cls.dsn,autocommit=True) as con:con.execute('DROP SCHEMA '+cls.schema+' CASCADE')
    def setUp(self):
        old=c._default_state();old.update(results=[{'vin':'PREVIOUS','status_raw':'OK'}],summary={'active':1},finished_at='07.11.2026 10:00:00')
        c._save_state(old)
    def post(self,value):
        with patch.object(c,'_authorized',return_value=True),patch.object(c,'_kostka_start'):
            return c.app.test_client().post('/api/sync',json=value)
    def test_progress_then_error_keeps_last_good(self):
        value=payload('b'*32);value.update(running=True,results=[],message_seq=1)
        self.assertEqual(self.post(value).status_code,200)
        value.update(running=False,error='fixture outage',message_seq=2)
        self.assertEqual(self.post(value).status_code,200)
        self.assertEqual(c._load_state()['results'][0]['vin'],'PREVIOUS')
    def test_duplicate_final_ack_does_not_duplicate_history(self):
        value=payload('c'*32)
        self.assertEqual(self.post(value).status_code,200)
        self.assertTrue(self.post(value).json['already_received'])
        with self.connect() as con:
            self.assertEqual(con.execute('SELECT count(*) FROM denni_pov_run_history WHERE run_id=%s',(value['run_id'],)).fetchone()[0],1)
    def test_history_failure_rolls_back_publication(self):
        with self.connect() as con:
            con.execute("ALTER TABLE denni_pov_run_history ADD CONSTRAINT audit_fail CHECK (run_id <> 'dddddddddddddddddddddddddddddddd')")
        try:
            response=self.post(payload('d'*32))
            self.assertGreaterEqual(response.status_code,500)
            self.assertEqual(c._load_state()['results'][0]['vin'],'PREVIOUS')
        finally:
            with self.connect() as con:con.execute('ALTER TABLE denni_pov_run_history DROP CONSTRAINT audit_fail')
    def test_delayed_message_is_durable_without_replacing_newer_result(self):
        newest=payload('e'*32)
        self.assertEqual(self.post(newest).status_code,200)
        current=c._load_state();current['_command']={'action':'run_check','id':'new-request'}
        c._save_state(current)
        late=payload('f'*32);late['check_id']='previous-request';late['finished_at']='07.11.2026 09:00:00'
        response=self.post(late)
        self.assertTrue(response.json['archived_only'])
        self.assertEqual(c._load_state()['run_id'],newest['run_id'])
        self.assertEqual(c._load_state()['_command']['id'],'new-request')
        self.assertTrue(self.post(late).json['already_received'])
        with self.connect() as con:
            self.assertEqual(con.execute('SELECT count(*) FROM denni_pov_run_history WHERE run_id=%s',(late['run_id'],)).fetchone()[0],1)
    def test_unknown_and_absent_rows_do_not_clear_manual_handling(self):
        row=dict(oid=1,vin='UNCERTAIN',status_raw='CHYBÍ V UNIQA')
        c._annotation_save('UNCERTAIN','keep','K DOŘEŠENÍ',row,'alice')
        c._reconcile_current_workflow([dict(row,status_raw='NELZE OVĚŘIT')])
        c._reconcile_current_workflow([])
        self.assertEqual(c._annotations_load_strict()['UNCERTAIN']['workflow_status'],'K DOŘEŠENÍ')
