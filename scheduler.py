"""
Runs the full job workflow at fixed times: 7 AM, 1 PM, 7 PM, 1 AM (local/CST).
Exactly 6-hour intervals, guaranteed run between 7-8 AM CST every day.

Usage:
    python scheduler.py          # foreground (keep terminal open)
    setup_windows_scheduler.bat  # background Windows task (recommended)

For an immediate one-off run:
    python main.py
"""

import os
import time
import schedule
from datetime import datetime
from pathlib import Path

os.chdir(Path(__file__).parent)

from config import LINKEDIN_EMAIL, ANTHROPIC_API_KEY, BASE_RESUME_PATH
from job_tracker import JobTracker
from adzuna_bot import AdzunaBot
from remoteok_bot import RemoteOKBot
from ziprecruiter_bot import ZipRecruiterBot
from linkedin_bot import LinkedInBot
from email_reporter import send_report

LOG_FILE = "scheduler.log"


def _log(msg: str):
    stamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    line  = f"[{stamp}] {msg}"
    print(line)
    with open(LOG_FILE, "a", encoding="utf-8") as f:
        f.write(line + "\n")


def _validate() -> bool:
    missing = []
    if not ANTHROPIC_API_KEY:
        missing.append("ANTHROPIC_API_KEY")
    if not LINKEDIN_EMAIL:
        missing.append("LINKEDIN_EMAIL")
    if not Path(BASE_RESUME_PATH).exists():
        missing.append(f"resume at {BASE_RESUME_PATH}")
    if missing:
        _log(f"ERROR: Missing config — {', '.join(missing)}")
        return False
    return True


COLLECTION_STEPS = [
    ("Adzuna",       AdzunaBot),
    ("RemoteOK",     RemoteOKBot),
    ("ZipRecruiter", ZipRecruiterBot),
]


def run_cycle():
    run_start = datetime.now()
    _log("=" * 56)
    _log(f"  Cycle — {run_start.strftime('%Y-%m-%d %H:%M')}")
    _log("=" * 56)

    if not _validate():
        return

    tracker = JobTracker()

    # ── Collection portals ────────────────────────────────────
    for label, BotClass in COLLECTION_STEPS:
        _log(f"[{label}] Starting search...")
        try:
            BotClass(tracker).run()
            _log(f"[{label}] Done")
        except Exception as e:
            _log(f"[{label}] ERROR: {e}")

    # ── LinkedIn Easy Apply ───────────────────────────────────
    _log("[LinkedIn] Starting Easy Apply workflow...")
    try:
        LinkedInBot(tracker).run()
        _log("[LinkedIn] Done")
    except Exception as e:
        _log(f"[LinkedIn] ERROR: {e}")

    # ── Email report ──────────────────────────────────────────
    _log("[Email] Sending consolidated report...")
    try:
        send_report(run_start=run_start)
        _log("[Email] Sent")
    except Exception as e:
        _log(f"[Email] ERROR: {e}")

    elapsed = (datetime.now() - run_start).seconds // 60
    _log(f"  Cycle complete in {elapsed} min. Next run in 6 hours.")
    _log("")


def main():
    print("=" * 56)
    print("  QA Job Automation Scheduler")
    print("  Portals: Adzuna · RemoteOK · ZipRecruiter · LinkedIn")
    print("  Runs at 7:00 AM / 1:00 PM / 7:00 PM / 1:00 AM (local time)")
    print("  Ctrl+C to stop")
    print("=" * 56)

    # 4 runs between 7 AM and 7 PM CST — every 4 hours
    schedule.every().day.at("07:00").do(run_cycle)
    schedule.every().day.at("11:00").do(run_cycle)
    schedule.every().day.at("15:00").do(run_cycle)
    schedule.every().day.at("19:00").do(run_cycle)

    next_runs = [str(j.next_run) for j in schedule.jobs]
    _log(f"Scheduled run times (today/tomorrow): {', '.join(next_runs)}")
    _log("Waiting for next scheduled run... (run main.py manually for an immediate run)")

    while True:
        schedule.run_pending()
        time.sleep(30)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\nScheduler stopped.")
