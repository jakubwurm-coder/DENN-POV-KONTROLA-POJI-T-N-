import ast
import copy
import os
from pathlib import Path
import threading
import unittest
import uuid
from unittest.mock import patch

from flask import Flask, jsonify
from assistant_api import install_assistant_api
from mcp_api import install_mcp_api


class ControlApiTests(unittest.TestCase):
    def setUp(self):
        self.env = patch.dict(os.environ, {
            'ASSISTANT_API_TOKEN': 'reader', 'ASSISTANT_CONTROL_TOKEN': 'controller',
            'MCP_CAPABILITY_TOKEN': 'reader', 'MCP_CONTROL_TOKEN': 'controller',
        })
        self.env.start()
        self.addCleanup(self.env.stop)
        self.state = {'running': False, 'finished_at': 'old', 'results': [], 'summary': {}}
        self.app = Flask(__name__)
        self.lock = threading.Lock()
        # Exercise the actual button handler without importing unrelated providers.
        tree = ast.parse(Path('cloud_app.py').read_text())
        fn = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == 'api_run')
        fn.decorator_list = []
        namespace = {
            '_lock': self.lock, '_load_state': lambda: copy.deepcopy(self.state),
            '_save_state': self.save, '_run_is_stale': lambda s: s.get('stale', False),
            '_now': lambda: '03.10.2026 20:00:00', 'uuid': uuid, 'jsonify': jsonify,
        }
        exec(compile(ast.Module(body=[fn], type_ignores=[]), 'cloud_app.py', 'exec'), namespace)
        handler = namespace['api_run']
        install_assistant_api(self.app, lambda: copy.deepcopy(self.state), lambda s: s, self.lock, handler)
        install_mcp_api(self.app, lambda: copy.deepcopy(self.state), self.save, lambda s: s, self.lock, handler)
        self.client = self.app.test_client()

    def save(self, data):
        self.state = copy.deepcopy(data)

    def rpc(self, token, method, **params):
        return self.client.post('/mcp/' + token, json={'jsonrpc': '2.0', 'id': 1, 'method': method, 'params': params})

    def test_read_token_cannot_start(self):
        for token in ('', 'reader', 'wrong'):
            self.assertEqual(self.client.post('/api/assistant/run', headers={'Authorization': 'Bearer ' + token}).status_code, 401)
        self.assertEqual(self.rpc('reader', 'tools/call', name='start_insurance_check').status_code, 403)
        self.assertFalse(self.state['running'])

    def test_start_and_duplicate(self):
        headers = {'Authorization': 'Bearer controller'}
        first = self.client.post('/api/assistant/run', headers=headers)
        self.assertEqual(first.status_code, 202)
        request_id = first.json['request_id']
        self.assertEqual(self.state['_command']['id'], request_id)
        self.assertEqual(self.state['_command']['action'], 'run_check')
        self.assertEqual(self.client.post('/api/assistant/run', headers=headers).status_code, 409)
        self.assertEqual(self.state['_command']['id'], request_id)
        status = self.client.get('/api/assistant/status', headers=headers).json
        self.assertTrue(status['running'])
        self.assertFalse(status['result_is_current'])

    def test_does_not_overwrite_other_command(self):
        command = {'id': 'lookup', 'action': 'lookup_vehicle'}
        self.state['_command'] = command
        result = self.rpc('controller', 'tools/call', name='start_insurance_check')
        self.assertTrue(result.json['result']['isError'])
        self.assertEqual(self.state['_command'], command)

    def test_mcp_tools_and_trigger(self):
        reader = self.rpc('reader', 'tools/list').json['result']['tools']
        controller = self.rpc('controller', 'tools/list').json['result']['tools']
        self.assertNotIn('start_insurance_check', [t['name'] for t in reader])
        self.assertIn('start_insurance_check', [t['name'] for t in controller])
        result = self.rpc('controller', 'tools/call', name='start_insurance_check').json['result']
        self.assertFalse(result['isError'])
        self.assertEqual(result['structuredContent']['status'], 'pending')
        busy = self.rpc('controller', 'tools/call', name='lookup_vehicle', arguments={'vin': 'W1K2060071R066129'})
        self.assertEqual(busy.status_code, 409)

    def test_disabled_control_and_invalid_arguments(self):
        with patch.dict(os.environ, {'ASSISTANT_CONTROL_TOKEN': '', 'MCP_CONTROL_TOKEN': ''}):
            self.assertEqual(self.client.post('/api/assistant/run', headers={'Authorization': 'Bearer controller'}).status_code, 401)
            self.assertEqual(self.rpc('controller', 'tools/list').status_code, 404)
        response = self.rpc('controller', 'tools/call', name='start_insurance_check', arguments={'force': True})
        self.assertEqual(response.status_code, 400)
        self.assertFalse(self.state['running'])

    def test_read_token_still_works_and_empty_is_denied(self):
        self.assertEqual(self.client.get('/api/assistant/status', headers={'Authorization': 'Bearer reader'}).status_code, 200)
        with patch.dict(os.environ, {'ASSISTANT_API_TOKEN': '', 'ASSISTANT_CONTROL_TOKEN': ''}):
            self.assertEqual(self.client.get('/api/assistant/status', headers={'Authorization': 'Bearer'}).status_code, 401)


if __name__ == '__main__':
    unittest.main()
