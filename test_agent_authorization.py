import os
import unittest
from unittest.mock import patch

import cloud_app


class AgentAuthorizationTests(unittest.TestCase):
    def setUp(self):
        self.old_token = os.environ.get("SYNC_TOKEN")
        self.old_agent = os.environ.get("DENNI_POV_ALLOWED_AGENT_ID")
        os.environ["SYNC_TOKEN"] = "sync-test-token"
        os.environ["DENNI_POV_ALLOWED_AGENT_ID"] = "VCSERVER"
        self.client = cloud_app.app.test_client()

    def tearDown(self):
        if self.old_token is None:
            os.environ.pop("SYNC_TOKEN", None)
        else:
            os.environ["SYNC_TOKEN"] = self.old_token
        if self.old_agent is None:
            os.environ.pop("DENNI_POV_ALLOWED_AGENT_ID", None)
        else:
            os.environ["DENNI_POV_ALLOWED_AGENT_ID"] = self.old_agent

    def test_server_agent_can_read_command(self):
        state = cloud_app._default_state()
        state["agent"] = {"id": "VCSERVER"}
        with patch.object(cloud_app, "_load_state", return_value=state):
            response = self.client.get(
                "/api/agent/command",
                headers={
                    "Authorization": "Bearer sync-test-token",
                    "X-Denni-Pov-Agent": "VCSERVER",
                },
            )
        self.assertEqual(response.status_code, 200)

    def test_other_computer_is_rejected(self):
        state = cloud_app._default_state()
        state["agent"] = {"id": "VCSERVER"}
        with patch.object(cloud_app, "_load_state", return_value=state):
            response = self.client.get(
                "/api/agent/command",
                headers={
                    "Authorization": "Bearer sync-test-token",
                    "X-Denni-Pov-Agent": "KANCELAR-PC",
                },
            )
        self.assertEqual(response.status_code, 403)

    def test_old_agent_without_identity_is_rejected_after_server_verified(self):
        state = cloud_app._default_state()
        state["agent"] = {"id": "VCSERVER"}
        with patch.object(cloud_app, "_load_state", return_value=state):
            response = self.client.get(
                "/api/agent/command",
                headers={"Authorization": "Bearer sync-test-token"},
            )
        self.assertEqual(response.status_code, 403)

    def test_sync_from_other_computer_is_rejected(self):
        response = self.client.post(
            "/api/sync",
            headers={
                "Authorization": "Bearer sync-test-token",
                "X-Denni-Pov-Agent": "KANCELAR-PC",
            },
            json={"sources": {}, "summary": {}, "results": []},
        )
        self.assertEqual(response.status_code, 401)


if __name__ == "__main__":
    unittest.main()
