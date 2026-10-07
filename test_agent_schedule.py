import unittest
import sys
import types
from datetime import datetime
from zoneinfo import ZoneInfo

# The scheduler is pure stdlib logic; keep this focused unit test runnable even
# in a minimal environment where the agent's HTTP dependency is not installed.
try:
    import requests  # noqa: F401
except ModuleNotFoundError:
    requests_stub = types.ModuleType("requests")
    requests_stub.RequestException = RuntimeError
    sys.modules["requests"] = requests_stub

from cloud_agent import _next_scheduled_run


PRAGUE = ZoneInfo("Europe/Prague")


class AgentScheduleTests(unittest.TestCase):
    def test_before_morning_run(self):
        now = datetime(2026, 10, 7, 9, 15, tzinfo=PRAGUE)
        self.assertEqual(
            _next_scheduled_run(now),
            datetime(2026, 10, 7, 10, 0, tzinfo=PRAGUE),
        )

    def test_between_daily_runs(self):
        now = datetime(2026, 10, 7, 10, 1, tzinfo=PRAGUE)
        self.assertEqual(
            _next_scheduled_run(now),
            datetime(2026, 10, 7, 17, 0, tzinfo=PRAGUE),
        )

    def test_after_evening_run(self):
        now = datetime(2026, 10, 7, 17, 1, tzinfo=PRAGUE)
        self.assertEqual(
            _next_scheduled_run(now),
            datetime(2026, 10, 8, 10, 0, tzinfo=PRAGUE),
        )

    def test_converts_utc_to_prague(self):
        utc = ZoneInfo("UTC")
        now = datetime(2026, 10, 7, 7, 30, tzinfo=utc)  # 09:30 Prague
        self.assertEqual(
            _next_scheduled_run(now),
            datetime(2026, 10, 7, 10, 0, tzinfo=PRAGUE),
        )


if __name__ == "__main__":
    unittest.main()
