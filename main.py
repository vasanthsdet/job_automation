"""
QA Job Application Workflow — backend only, no browser
=======================================================
Portals searched every run:
  1  Dice        → public REST API (Dallas + Remote, Contract)
  2  Indeed      → public RSS feed (Dallas + Remote, Contract)
  3  RemoteOK    → public JSON API (Remote QA/SDET roles)
  4  ZipRecruiter→ Jobs API (optional key, Dallas + Remote, Contract)
  5  LinkedIn    → Voyager REST API → Easy Apply → AI-tailored resume

After all searches:
  6  Email report → revathibathina11@gmail.com, dama.vasanth@gmail.com

Usage:
    python main.py                    # full workflow
    python main.py --collect-only     # search all portals, skip LinkedIn apply
    python main.py --linkedin-only    # only LinkedIn Easy Apply
    python main.py --dry-run          # search only, no apply, no email
    python main.py --portal dice      # run a single portal (dice/indeed/remoteok/ziprecruiter)

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

from config import LINKEDIN_EMAIL, ANTHROPIC_API_KEY, BASE_RESUME_PATH, ZIPRECRUITER_API_KEY
from job_tracker import JobTracker
from linkedin_bot import LinkedInBot
from adzuna_bot import AdzunaBot
from remoteok_bot import RemoteOKBot
from ziprecruiter_bot import ZipRecruiterBot
from email_reporter import send_report


def _validate():
    errors = []
    if not ANTHROPIC_API_KEY:
        errors.append("ANTHROPIC_API_KEY not set — add to GitHub Secrets or pass as env var")
    if not LINKEDIN_EMAIL:
        errors.append("LINKEDIN_EMAIL not set — pass --linkedin-email or set env var LINKEDIN_EMAIL")
    if not Path(BASE_RESUME_PATH).exists():
        errors.append(f"Resume not found at '{BASE_RESUME_PATH}' — add RESUME_BASE64 to GitHub Secrets")
    if errors:
        print("\n[ERROR] Fix before running:\n")
        for e in errors:
            print(f"  • {e}")
        sys.exit(1)


# Maps CLI name → bot class (collection-only portals)
COLLECTION_BOTS = {
    "adzuna":       AdzunaBot,
    "remoteok":     RemoteOKBot,
    "ziprecruiter": ZipRecruiterBot,
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

    collect_only  = "--collect-only" in args
    linkedin_only = "--linkedin-only" in args
    dry_run       = "--dry-run" in args
    skip_tailor   = "--skip-tailor" in args
    portal_filter = None
    if "--portal" in args:
        idx = args.index("--portal")
        if idx + 1 < len(args):
            portal_filter = args[idx + 1].lower()
            if portal_filter not in COLLECTION_BOTS:
                print(f"Unknown portal '{portal_filter}'. Choose: {', '.join(COLLECTION_BOTS)}")
                sys.exit(1)

    print("=" * 60)
    print("  QA Job Application Workflow  (HTTP/API only)")
    print(f"  Portals: Adzuna · RemoteOK · ZipRecruiter · LinkedIn")
    print(f"  Started: {run_start.strftime('%Y-%m-%d %H:%M')}")
    print("=" * 60)
    _validate()

    if dry_run:
        print("\n[DRY RUN] Searching all portals — no applications submitted\n")

    tracker = JobTracker()

    # ── Collection portals ────────────────────────────────────
    if not linkedin_only:
        run_collection(tracker, portal_filter)

    # ── LinkedIn Easy Apply ───────────────────────────────────
    next_step = len(COLLECTION_BOTS) + 1 if not portal_filter else 2
    if not collect_only and not dry_run and not portal_filter:
        print(f"\n── Step {next_step}: LinkedIn Easy Apply ───────────────────────")
        try:
            LinkedInBot(tracker, skip_tailor=skip_tailor).run()
        except Exception as e:
            print(f"[LinkedIn] ERROR: {e}")
    elif linkedin_only and not dry_run:
        print(f"\n── LinkedIn Easy Apply (only) ────────────────────────────")
        try:
            LinkedInBot(tracker, skip_tailor=skip_tailor).run()
        except Exception as e:
            print(f"[LinkedIn] ERROR: {e}")
    elif dry_run:
        print("\n[DRY RUN] Skipping LinkedIn applications")

    # ── Email report ──────────────────────────────────────────
    if not dry_run:
        print(f"\n── Email Report ──────────────────────────────────────────")
        send_report(run_start=run_start)

    print("\n" + "=" * 60)
    print("  Done! Check applied_jobs.csv and your email inbox.")
    print("=" * 60)


if __name__ == "__main__":
    main()
