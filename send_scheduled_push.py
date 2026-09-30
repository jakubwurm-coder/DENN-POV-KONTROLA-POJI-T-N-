import os
from datetime import datetime
from zoneinfo import ZoneInfo
import requests

now = datetime.now(ZoneInfo("Europe/Prague"))
if now.hour not in (8, 15):
    print(f"DENNI POV push: {now:%Y-%m-%d %H:%M} Europe/Prague - mimo plán 08:00/15:00.")
    raise SystemExit(0)

url = os.getenv("PUSH_URL", "https://denni-pov-kontrola.onrender.com/api/push/send-scheduled")
secret = os.environ["PUSH_CRON_SECRET"]
response = requests.post(url, headers={"X-Push-Secret": secret}, timeout=60)
print(response.status_code, response.text)
response.raise_for_status()
