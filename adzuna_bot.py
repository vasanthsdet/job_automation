"""
Adzuna job search — free public REST API.

Free API key: https://developer.adzuna.com  (2-min signup, 250 calls/day free)
Set ADZUNA_APP_ID and ADZUNA_APP_KEY in .env — bot is skipped if missing.

Covers jobs from Dice, Indeed, and 100+ other boards aggregated by Adzuna.

Search strategy:
  - Texas (state-level) + Remote — both filtered to Contract/Contractor type
  - Keywords: QA, SDET (one search per keyword)
  - Date filter: last LISTED_AT_DAYS
  - Rate filter: >= MIN_HOURLY_RATE
"""

import ssl
import time
import random
import urllib3
from datetime import datetime, timezone, timedelta

import requests

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
ssl._create_default_https_context = ssl._create_unverified_context

from config import (
    JOB_SEARCH_KEYWORDS, PRIMARY_LOCATION,
    INCLUDE_REMOTE, MIN_HOURLY_RATE, LISTED_AT_SECONDS,
)
from job_tracker import JobTracker
from utils import meets_rate

try:
    from config import ADZUNA_APP_ID, ADZUNA_APP_KEY
except ImportError:
    ADZUNA_APP_ID = ADZUNA_APP_KEY = ""

ADZUNA_API = "https://api.adzuna.com/v1/api/jobs/us/search"

_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
    "Accept": "application/json",
}

_MAX_DAYS  = max(1, LISTED_AT_SECONDS // 86400)
_STATE     = PRIMARY_LOCATION.split(",")[0].strip()   # "Texas"
_QA_WORDS  = {"qa", "qe", "quality", "test", "sdet", "automation", "tester", "uat"}


def _is_qa_title(title: str) -> bool:
    t = title.lower()
    return any(w in t for w in _QA_WORDS)


class AdzunaBot:
    def __init__(self, tracker: JobTracker):
        self.tracker = tracker

    def _fetch(self, keyword: str, location: str) -> list[dict]:
        if not ADZUNA_APP_ID or not ADZUNA_APP_KEY:
            return []

        jobs: list[dict] = []
        for page in range(1, 4):
            params = {
                "app_id":           ADZUNA_APP_ID,
                "app_key":          ADZUNA_APP_KEY,
                "what":             f"{keyword} contract",
                "where":            location,
                "results_per_page": 50,
                "max_days_old":     _MAX_DAYS,
                "sort_by":          "date",
                "content-type":     "application/json",
            }
            # Retry once on connection errors
            for attempt in range(2):
                try:
                    resp = requests.get(
                        f"{ADZUNA_API}/{page}",
                        params=params,
                        headers=_HEADERS,
                        timeout=20,
                        verify=False,
                    )
                    resp.raise_for_status()
                    data = resp.json()
                    hits = data.get("results", [])
                    jobs.extend(hits)
                    if len(hits) < 50:
                        return jobs
                    time.sleep(random.uniform(1.5, 3.0))
                    break  # success — move to next page
                except requests.exceptions.ConnectionError as e:
                    if attempt == 0:
                        print(f"  [Adzuna] Connection reset, retrying in 5s...")
                        time.sleep(5)
                    else:
                        print(f"  [Adzuna] Connection reset again — skipping this search")
                        return jobs
                except Exception as e:
                    print(f"  [Adzuna] Fetch error (page {page}): {e}")
                    return jobs

        return jobs

    _DEFAULT_KEYWORDS = ["QA engineer", "quality assurance", "test automation", "software tester"]

    def search_jobs(self) -> list[dict]:
        seen: dict[str, dict] = {}

        # Use ADZUNA_KEYWORDS if passed at runtime, otherwise fall back to broad QA defaults
        import os
        _raw = os.getenv("ADZUNA_KEYWORDS", "").strip()
        adzuna_keywords = (
            [k.strip() for k in _raw.split(",") if k.strip()]
            if _raw
            else self._DEFAULT_KEYWORDS
        )

        for i, kw in enumerate(adzuna_keywords):
            if i > 0:
                time.sleep(random.uniform(4, 7))

            # TX jobs
            print(f"[Adzuna] Search: '{kw}' contract in {_STATE}")
            before = len(seen)
            for j in self._fetch(kw, _STATE):
                jid = str(j.get("id", ""))
                if jid and _is_qa_title(j.get("title", "")):
                    seen[jid] = j
            print(f"  → {len(seen) - before} TX results")

            # Remote jobs
            if INCLUDE_REMOTE:
                time.sleep(random.uniform(2, 4))
                print(f"[Adzuna] Search: '{kw}' contract Remote")
                before = len(seen)
                for j in self._fetch(kw, "remote"):
                    jid = str(j.get("id", ""))
                    if jid and _is_qa_title(j.get("title", "")):
                        seen.setdefault(jid, j)
                print(f"  → {len(seen) - before} new Remote results")

        print(f"[Adzuna] {len(seen)} unique jobs found")
        return list(seen.values())

    @staticmethod
    def _extract(job: dict) -> dict:
        jid = str(job.get("id", ""))
        return {
            "job_id":      f"adzuna-{jid}",
            "title":       job.get("title", ""),
            "company":     (job.get("company") or {}).get("display_name", "Unknown"),
            "location":    (job.get("location") or {}).get("display_name", ""),
            "url":         job.get("redirect_url", ""),
            "description": job.get("description", ""),
        }

    def run(self):
        if not ADZUNA_APP_ID or not ADZUNA_APP_KEY:
            print("[Adzuna] Skipped — ADZUNA_APP_ID / ADZUNA_APP_KEY not set in .env")
            print("         Get free key at: https://developer.adzuna.com")
            return

        raw      = self.search_jobs()
        parsed   = [self._extract(j) for j in raw]
        new_jobs = [j for j in parsed if not self.tracker.already_applied(j["job_id"])]
        saved    = 0
        skipped  = 0

        for job in new_jobs:
            status = "Collected - Manual Apply"
            if not meets_rate(job["description"], MIN_HOURLY_RATE):
                status   = f"Skipped - Rate Below ${MIN_HOURLY_RATE}/hr"
                skipped += 1
            else:
                saved += 1

            self.tracker.log_application(
                platform="Adzuna",
                job_id=job["job_id"],
                title=job["title"],
                company=job["company"],
                url=job["url"],
                status=status,
            )
            time.sleep(random.uniform(0.2, 0.5))

        print(f"[Adzuna] Done — {saved} collected, {skipped} skipped (rate < ${MIN_HOURLY_RATE}/hr)")
