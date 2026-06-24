"""
QA Job Application Workflow — backend only, no browser
=======================================================
Portals searched every run:
  1  Adzuna      → public REST API (Texas + Remote, Contract, 250 calls/day free)
  2  RemoteOK    → public JSON API (Remote QA/SDET roles, no key needed)
  3  ZipRecruiter→ Jobs API (optional key, Texas + Remote, Contract)
  4  Remotive    → public REST API (remote tech jobs, QA/SDET focus, no key needed)
  5  Dice        → public REST API (Texas + Remote, Contract, top tech board)
  6  Indeed      → public RSS feed (Texas + Remote, Contract, no key needed)
  7  Glassdoor   → HTML scraping (Texas + Remote; may return 0 if blocked)
  8  LinkedIn    → Voyager REST API → collect all jobs (Easy Apply flagged in report)

Note: Stack Overflow Jobs shut down in March 2022 and is no longer available.
Note: Wellfound (AngelList) has no public API (requires OAuth) — replaced by Remotive.

After all searches:
  7  Email report → revathibathina11@gmail.com, dama.vasanth@gmail.com

Usage:
    python main.py                    # full workflow
    python main.py --dry-run          # search only, no email
    python main.py --portal dice      # run a single portal (dice/remoteok/ziprecruiter/linkedin)
    python main.py --portal linkedin  # LinkedIn only

Runtime credential overrides (never stored — set env vars before config loads):
    --linkedin-email EMAIL            override LINKEDIN_EMAIL
    --linkedin-password PASSWORD      override LINKEDIN_PASSWORD
    --email-recipients a@b.com,c@d   override EMAIL_RECIPIENTS (default: revathibathina11@gmail.com,dama.vasanth@gmail.com)
    --technologies "QA,SDET"         override JOB_SEARCH_KEYWORDS (default: QA)

Scheduling:
    python scheduler.py               # every 3 hours (keep terminal open)
    setup_windows_scheduler.bat       # Windows background task (recommended)
"""

import sys
import os
import argparse
from datetime import datetime
from pathlib import Path

# Fix Windows console encoding
if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

os.chdir(Path(__file__).parent)

# ── Set runtime credentials as env vars before config reads them ─
def _set_runtime_env():
    p = argparse.ArgumentParser(add_help=False)
    p.add_argument("--linkedin-email")
    p.add_argument("--linkedin-password")
    p.add_argument("--email-recipients")
    p.add_argument("--technologies")
    args, _ = p.parse_known_args()
    if args.linkedin_email:    os.environ["LINKEDIN_EMAIL"]      = args.linkedin_email
    if args.linkedin_password: os.environ["LINKEDIN_PASSWORD"]   = args.linkedin_password
    if args.email_recipients:  os.environ["EMAIL_RECIPIENTS"]    = args.email_recipients
    if args.technologies:      os.environ["JOB_SEARCH_KEYWORDS"] = args.technologies

_set_runtime_env()
# ─────────────────────────────────────────────────────────────────

from config import LINKEDIN_EMAIL, ZIPRECRUITER_API_KEY
from job_tracker import JobTracker
from linkedin_bot import LinkedInBot
from adzuna_bot import AdzunaBot
from remoteok_bot import RemoteOKBot
from ziprecruiter_bot import ZipRecruiterBot
from remotive_bot import RemotiveBot
from dice_bot import DiceBot
from indeed_bot import IndeedBot
from glassdoor_bot import GlassdoorBot
from email_reporter import send_report


def _validate():
    errors = []
    if not LINKEDIN_EMAIL:
        errors.append("LINKEDIN_EMAIL not set — pass --linkedin-email or set env var LINKEDIN_EMAIL")
    if errors:
        print("\n[ERROR] Fix before running:\n")
        for e in errors:
            print(f"  • {e}")
        sys.exit(1)


# Maps CLI name → bot class
COLLECTION_BOTS = {
    "adzuna":       AdzunaBot,
    "remoteok":     RemoteOKBot,
    "ziprecruiter": ZipRecruiterBot,
    "remotive":     RemotiveBot,
    "dice":         DiceBot,
    "indeed":       IndeedBot,
    "glassdoor":    GlassdoorBot,
    "linkedin":     LinkedInBot,
}


def run_collection(tracker: JobTracker, only_portal: str | None = None):
    targets = {only_portal: COLLECTION_BOTS[only_portal]} if only_portal else COLLECTION_BOTS
    for step, (name, BotClass) in enumerate(targets.items(), 1):
        label = name.capitalize()
        print(f"\n── Step {step}: {label} ─────────────────────────────────────")
        try:
            BotClass(tracker).run()
        except Exception as e:
            print(f"[{label}] ERROR: {e}")


def main():
    run_start = datetime.now()
    args      = sys.argv[1:]

    collect_only  = "--collect-only" in args   # run all portals except LinkedIn (for cloud CI)
    dry_run       = "--dry-run" in args
    no_email      = "--no-email" in args
    append_mode   = "--append" in args         # don't reset CSV — append to downloaded artifact
    portal_filter = None
    if "--portal" in args:
        idx = args.index("--portal")
        if idx + 1 < len(args):
            portal_filter = args[idx + 1].lower()
            if portal_filter not in COLLECTION_BOTS:
                print(f"Unknown portal '{portal_filter}'. Choose: {', '.join(COLLECTION_BOTS)}")
                sys.exit(1)

    print("=" * 60)
    print("  QA Job Collection Workflow  (HTTP/API only)")
    print(f"  Portals: Adzuna · RemoteOK · ZipRecruiter · Remotive · Dice · Indeed · Glassdoor · LinkedIn")
    print(f"  Started: {run_start.strftime('%Y-%m-%d %H:%M')}")
    print("=" * 60)
    _validate()

    if dry_run:
        print("\n[DRY RUN] Searching all portals — no email sent\n")

    tracker = JobTracker(append=append_mode)

    # ── Portal collection ─────────────────────────────────────
    if collect_only:
        # Cloud CI: skip LinkedIn (needs self-hosted runner / local IP)
        non_linkedin = {k: v for k, v in COLLECTION_BOTS.items() if k != "linkedin"}
        for step, (name, BotClass) in enumerate(non_linkedin.items(), 1):
            label = name.capitalize()
            print(f"\n── Step {step}: {label} ─────────────────────────────────────")
            try:
                BotClass(tracker).run()
            except Exception as e:
                print(f"[{label}] ERROR: {e}")
    else:
        run_collection(tracker, portal_filter)

    # ── Email report ──────────────────────────────────────────
    if not dry_run and not no_email:
        print(f"\n── Email Report ──────────────────────────────────────────")
        send_report(run_start=run_start)

    print("\n" + "=" * 60)
    print("  Done! Check applied_jobs.csv and your email inbox.")
    print("=" * 60)


if __name__ == "__main__":
    main()
