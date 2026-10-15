import unittest
from unittest.mock import patch

import cloud_app


class DmsDataCsvTests(unittest.TestCase):
    def setUp(self):
        self.client = cloud_app.app.test_client()

    def test_dmsdata_returns_latest_results_as_utf8_csv(self):
        state = cloud_app._default_state()
        state.update({
            "finished_at": "15.10.2026 17:00:00",
            "results": [{
                "status": "CHYBÍ V UNIQA",
                "status_raw": "CHYBÍ V UNIQA",
                "pojistovna": "",
                "vin": "TESTVIN1234567890",
                "spz_tir": "1AB2345",
                "vykup": "15.10.2026",
                "prodej": "",
                "detail": "Chybí pojištění",
                "note": "Prověřit",
            }],
        })

        with (
            patch.object(cloud_app, "_load_state", return_value=state),
            patch.object(cloud_app, "_annotations_load", return_value={}),
        ):
            response = self.client.get("/dmsdata")

        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.data.startswith(b"\xef\xbb\xbf"))
        text = response.data.decode("utf-8-sig")
        self.assertIn("Stav;Pojišťovna;VIN;SPZ", text)
        self.assertIn("TESTVIN1234567890;1AB2345", text)
        self.assertIn("no-store", response.headers["Cache-Control"])
        self.assertIn("inline", response.headers["Content-Disposition"])
        self.assertIn("denni_pov_kontrola.csv", response.headers["Content-Disposition"])

    def test_dmsdata_is_unavailable_before_first_result(self):
        state = cloud_app._default_state()
        with (
            patch.object(cloud_app, "_load_state", return_value=state),
            patch.object(cloud_app, "_annotations_load", return_value={}),
        ):
            response = self.client.get("/dmsdata")

        self.assertEqual(response.status_code, 404)
        self.assertFalse(response.json["ok"])


if __name__ == "__main__":
    unittest.main()
