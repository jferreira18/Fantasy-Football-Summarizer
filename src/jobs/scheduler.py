"""Persistent Tuesday scheduler, supervised by systemd or Windows Task Scheduler."""
from datetime import datetime, timedelta
import subprocess
import sys
import time
from zoneinfo import ZoneInfo
from src.config import Config

def next_run(now, hour):
    target = now.replace(hour=hour, minute=0, second=0, microsecond=0)
    target += timedelta(days=(1 - now.weekday()) % 7)
    if target <= now:
        target += timedelta(days=7)
    return target

def main():
    config = Config.load()
    zone = ZoneInfo(config.timezone)
    # Catch up on restart; completed-period detection and delivery state prevent duplicates.
    retry_at = 0.0
    while True:
        now = datetime.now(zone)
        if time.monotonic() >= retry_at:
            subprocess.run([sys.executable, '-m', 'src.jobs.weekly_job'], cwd=config.root, check=False)
            target = next_run(datetime.now(zone), config.report_hour)
            # Retry failed runs hourly; unchanged delivered weeks exit without fetching data again beyond status.
            retry_at = time.monotonic() + min(3600, max(1, target.timestamp() - now.timestamp()))
        time.sleep(30)

if __name__ == '__main__':
    main()
