import os
import unittest
from unittest.mock import patch

import cloud_app


class SyncResilienceTests(unittest.TestCase):
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

    def test_failed_empty_sync_preserves_last_valid_results(self):
        previous = cloud_app._default_state()
        previous.update({
            "finished_at": "04.10.2026 23:19:21",
            "summary": {"active": 1, "ok_total": 1, "missing": 0},
            "results": [{"vin": "TESTVIN1234567890", "status_raw": "OK"}],
            "changes": {"count": 2, "items": [{"type": "NEW"}]},
            "csv_available": True,
        })
        payload = {
            "running": False,
            "finished_at": "04.10.2026 23:38:39",
            "error": "Read timed out. (read timeout=20)",
            "agent": {"id": "VCSERVER", "computer": "VCSERVER", "system": "Windows"},
            "sources": {"tirbazar": {"state": "error"}},
            "summary": {"active": 0, "ok_total": 0, "missing": 0},
            "results": [],
            "progress": {"percent": 100, "phase": "Kontrola skončila chybou"},
        }
        saved = {}

        def capture(data):
            saved.update(data)

        with (
            patch.object(cloud_app, "_load_state", return_value=previous),
            patch.object(cloud_app, "_annotations_load", return_value={}),
            patch.object(cloud_app, "_save_state", side_effect=capture),
            patch.object(cloud_app, "_history_save_daily") as daily,
            patch.object(cloud_app, "_run_history_save") as run_history,
            patch.object(cloud_app, "_run_history_last_successful") as last_success,
        ):
            response = self.client.post(
                "/api/sync",
                headers={
                    "Authorization": "Bearer sync-test-token",
                    "X-Denni-Pov-Agent": "VCSERVER",
                },
                json=payload,
            )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(saved["results"], previous["results"])
        self.assertEqual(saved["summary"], previous["summary"])
        self.assertEqual(saved["changes"], previous["changes"])
        self.assertEqual(saved["error"], payload["error"])
        self.assertEqual(saved["last_successful_at"], previous["finished_at"])
        self.assertTrue(saved["csv_available"])
        daily.assert_not_called()
        run_history.assert_not_called()
        last_success.assert_not_called()


if __name__ == "__main__":
    unittest.main()
