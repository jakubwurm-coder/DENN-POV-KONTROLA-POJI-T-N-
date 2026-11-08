from datetime import datetime
import unittest
from data_freshness import snapshot_freshness, PRAGUE

class FreshnessTests(unittest.TestCase):
    def test_yesterday_is_stale_after_today_schedule(self):
        self.assertTrue(snapshot_freshness({'finished_at':'07.11.2026 22:35:04'},datetime(2026,11,8,21,tzinfo=PRAGUE))['stale'])
    def test_overnight_result_is_valid_before_morning_deadline(self):
        self.assertFalse(snapshot_freshness({'finished_at':'07.11.2026 22:35:04'},datetime(2026,11,8,10,9,tzinfo=PRAGUE))['stale'])
    def test_exact_grace_deadline_and_newer_manual_run(self):
        now=datetime(2026,11,8,10,10,tzinfo=PRAGUE)
        self.assertTrue(snapshot_freshness({'finished_at':'07.11.2026 22:35:04'},now)['stale'])
        self.assertFalse(snapshot_freshness({'finished_at':'08.11.2026 10:01:00'},now)['stale'])
    def test_error_does_not_make_old_data_fresh(self):
        state={'last_successful_at':'08.11.2026 10:01:00','finished_at':'08.11.2026 17:02:00','error':'SQL unavailable'}
        self.assertTrue(snapshot_freshness(state,datetime(2026,11,8,17,11,tzinfo=PRAGUE))['stale'])
