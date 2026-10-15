"""Browser reauthentication must not interfere with agent authorization."""
import os
import unittest
from unittest.mock import patch

import cloud_app as module


class WebLoginTests(unittest.TestCase):
    def setUp(self):
        self.env = patch.dict(os.environ, {
            'DENNI_POV_WEB_USER': 'test-user',
            'DENNI_POV_WEB_PASSWORD': 'test-password',
        })
        self.env.start()
        self.addCleanup(self.env.stop)
        config = patch.dict(module.app.config, {
            'TESTING': True, 'SECRET_KEY': 'test-only-session-secret',
        })
        config.start()
        self.addCleanup(config.stop)
        self.client = module.app.test_client()
        self.origin = 'https://localhost'

    def get(self, path):
        return self.client.get(path, base_url=self.origin)

    def login(self, password='test-password'):
        return self.client.post('/login', base_url=self.origin,
                                data={'username': 'test-user', 'password': password})

    def test_explicit_login_then_reload_requires_login(self):
        self.assertEqual(self.get('/').location, '/login')
        self.assertEqual(self.login().location, '/')
        self.assertEqual(self.get('/').status_code, 200)
        self.assertEqual(self.get('/sw.js').status_code, 200)
        self.assertEqual(self.get('/').location, '/login')
        self.assertEqual(self.get('/sw.js').location, '/login')
        self.assertEqual(self.get('/api/state').status_code, 401)

    def test_login_page_clears_existing_session(self):
        self.login()
        self.assertEqual(self.get('/login').status_code, 200)
        self.assertEqual(self.get('/').location, '/login')

    def test_invalid_password_never_grants_access(self):
        response = self.login('wrong')
        self.assertIn('Nesprávné jméno nebo heslo.', response.get_data(as_text=True))
        self.assertEqual(self.get('/').location, '/login')

    def test_health_and_bearer_agent_state_do_not_require_browser_login(self):
        self.assertEqual(self.get('/health').status_code, 200)
        with patch.object(module, '_authorized', return_value=True), \
             patch.object(module, '_load_state', return_value={}), \
             patch.object(module, '_public_state', return_value={}):
            response = self.client.get('/api/state', base_url=self.origin,
                                       headers={'Authorization': 'Bearer test-agent'})
        self.assertEqual(response.status_code, 200)

    def test_dmsdata_csv_does_not_require_browser_login(self):
        with patch.object(module, '_load_state', return_value={
            'results': [{'vin': 'TESTVIN1234567890', 'status': 'OK', 'status_raw': 'OK'}],
        }), patch.object(module, '_annotations_load', return_value={}):
            response = self.get('/dmsdata')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.mimetype, 'text/csv')


if __name__ == '__main__':
    unittest.main()
