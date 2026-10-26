"""Personal identities, revocation and audit authorship without production writes."""
import json
import os
import unittest
from unittest.mock import patch

from werkzeug.security import generate_password_hash
import cloud_app as c


class PersonalAccountsTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.passwords={f'user{i}@example.test':f'test-password-{i}' for i in range(4)}
        cls.hashes={email:generate_password_hash(password) for email,password in cls.passwords.items()}
        cls.replacement=generate_password_hash('replacement-test-password')

    def setUp(self):
        self.config=patch.dict(c.app.config,SECRET_KEY='test-only-session-secret',TESTING=True)
        self.config.start();self.addCleanup(self.config.stop)
        self.env=patch.dict(os.environ,{
            'DENNI_POV_WEB_USERS':json.dumps(self.hashes),
            'DENNI_POV_WEB_USER':'shared', 'DENNI_POV_WEB_PASSWORD':'shared-test-password'})
        self.env.start();self.addCleanup(self.env.stop)
        self.client=c.app.test_client()
        self.history_patch=patch.object(c,'_annotation_history_load',return_value=[])
        self.history_patch.start();self.addCleanup(self.history_patch.stop)

    def login(self,email,password,client=None):
        return (client or self.client).post('/login',base_url='https://localhost',
            data={'username':email,'password':password})

    def history(self,client=None):
        return (client or self.client).get('/api/manual-history',base_url='https://localhost')

    def test_each_person_has_distinct_canonical_identity(self):
        for email,password in self.passwords.items():
            with self.subTest(email=email):
                response=self.login('  '+email.upper()+'  ',password)
                self.assertEqual(response.status_code,302)
                page=self.client.get('/',base_url='https://localhost')
                self.assertEqual(page.status_code,200)
                self.assertIn(email,page.get_data(as_text=True))
                with self.client.session_transaction() as session:
                    self.assertEqual(session['denni_pov_username'],email)
                    self.assertNotIn(password,str(dict(session)))
                self.assertEqual(self.history().status_code,200)

    def test_passwords_cannot_be_used_for_other_accounts(self):
        emails=list(self.passwords)
        for i,email in enumerate(emails):
            response=self.login(email,self.passwords[emails[(i+1)%4]])
            self.assertEqual(response.status_code,200)
            self.assertIn('Nesprávné jméno nebo heslo.',response.get_data(as_text=True))
            self.assertEqual(self.history().status_code,401)
        self.login('unknown@example.test',next(iter(self.passwords.values())))
        self.assertEqual(self.history().status_code,401)

    def test_shared_login_is_disabled_and_existing_shared_session_revoked(self):
        self.login('shared','shared-test-password')
        self.assertEqual(self.history().status_code,401)
        with self.client.session_transaction() as session:
            session['denni_pov_authenticated']=True
            session['denni_pov_username']='shared'
        self.assertEqual(self.history().status_code,401)

    def test_invalid_configuration_never_falls_back_to_shared_password(self):
        for value in ('','invalid json','{}','[]',json.dumps({'user@example.test':'plaintext'})):
            with patch.dict(os.environ,DENNI_POV_WEB_USERS=value):
                self.login('shared','shared-test-password')
                self.assertEqual(self.history().status_code,401)

    def test_removed_or_rotated_account_loses_access(self):
        email,password=next(iter(self.passwords.items()))
        for mode in ('removed','rotated'):
            self.login(email,password)
            modified=dict(self.hashes)
            if mode=='removed':del modified[email]
            else:modified[email]=self.replacement
            with patch.dict(os.environ,DENNI_POV_WEB_USERS=json.dumps(modified)):
                self.assertEqual(self.history().status_code,401)

    def test_changing_another_account_does_not_revoke_this_user(self):
        email,password=next(iter(self.passwords.items()))
        self.login(email,password)
        modified=dict(self.hashes)
        modified[list(modified)[1]]=self.replacement
        with patch.dict(os.environ,DENNI_POV_WEB_USERS=json.dumps(modified)):
            self.assertEqual(self.history().status_code,200)

    def test_manual_workflow_uses_actual_person_and_ignores_spoofed_author(self):
        row={'vin':'IDENTITY-TEST','status_raw':'CHYBÍ V UNIQA'}
        for email,password in self.passwords.items():
            client=c.app.test_client()
            self.login(email,password,client)
            with patch.object(c,'_load_state',return_value={'results':[row]}), \
                 patch.object(c,'_save_state'),patch.object(c,'_annotation_save',return_value={}) as save:
                response=client.post('/api/result-meta',base_url='https://localhost',json={
                    'key':row['vin'],'workflow_status':'RUČNĚ OK','actor':'forged@example.test'})
            self.assertEqual(response.status_code,200,response.json)
            self.assertEqual(save.call_args.kwargs['actor'],email)

    def test_logout_and_failed_login_clear_existing_identity(self):
        email,password=next(iter(self.passwords.items()))
        self.login(email,password)
        response=self.client.post('/logout',base_url='https://localhost')
        self.assertEqual(response.status_code,302)
        self.assertEqual(self.history().status_code,401)
        self.login(email,password)
        self.login(email,'wrong-password')
        self.assertEqual(self.history().status_code,401)

    def test_machine_agent_access_remains_separate(self):
        with patch.object(c,'_authorized',return_value=True),patch.object(c,'_load_state',return_value={}),patch.object(c,'_public_state',return_value={}):
            response=self.client.get('/api/state',base_url='https://localhost',headers={'Authorization':'Bearer test-agent'})
        self.assertEqual(response.status_code,200)


if __name__=='__main__':unittest.main()
