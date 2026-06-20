"""
Runs the full job workflow every 2 hours during business hours (local time).
Schedule: 7 AM, 9 AM, 11 AM, 1 PM, 3 PM, 5 PM, 7 PM — 7 runs/day.

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
from remotive_bot import RemotiveBot
from dice_bot import DiceBot
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
    ("Remotive",     RemotiveBot),
    ("Dice",         DiceBot),
]


def run_cycle():
    run_start = datetime.now()
    _log("=" * 60)
    _log(f"  Cycle — {run_start.strftime('%Y-%m-%d %H:%M')}")
    _log("=" * 60)

    if not _validate():
        return

    tracker = JobTracker()

    # ── Collection portals ─────────────────────────────────────
    for label, BotClass in COLLECTION_STEPS:
        _log(f"[{label}] Starting...")
        try:
            BotClass(tracker).run()
            _log(f"[{label}] Done")
        except Exception as e:
            _log(f"[{label}] ERROR: {e}")

    # ── LinkedIn Easy Apply ────────────────────────────────────
    _log("[LinkedIn] Starting Easy Apply...")
    try:
        LinkedInBot(tracker).run()
        _log("[LinkedIn] Done")
    except Exception as e:
        _log(f"[LinkedIn] ERROR: {e}")

    # ── Email report ───────────────────────────────────────────
    _log("[Email] Sending consolidated report...")
    try:
        send_report(run_start=run_start)
        _log("[Email] Sent")
    except Exception as e:
        _log(f"[Email] ERROR: {e}")

    elapsed = (datetime.now() - run_start).seconds // 60
    _log(f"  Cycle complete in {elapsed} min. Next run in ~2 hours.")
    _log("")


def main():
    print("=" * 60)
    print("  QA Job Automation Scheduler")
    print("  Portals: Adzuna · RemoteOK · ZipRecruiter · Remotive · Dice · LinkedIn")
    print("  Runs at 7AM / 9AM / 11AM / 1PM / 3PM / 5PM / 7PM (local time)")
    print("  Ctrl+C to stop")
    print("=" * 60)

    for t in ("07:00", "09:00", "11:00", "13:00", "15:00", "17:00", "19:00"):
        schedule.every().day.at(t).do(run_cycle)

    next_runs = [str(j.next_run) for j in schedule.jobs]
    _log(f"Next scheduled runs: {', '.join(next_runs)}")
    _log("Waiting... (run main.py for an immediate one-off run)")

    while True:
        schedule.run_pending()
        time.sleep(30)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\nScheduler stopped.")
