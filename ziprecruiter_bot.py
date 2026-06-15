"""
ZipRecruiter job search — via ZipRecruiter's Jobs API.

Requires a free API key from: https://www.ziprecruiter.com/zap/app
Set ZIPRECRUITER_API_KEY in .env — bot is silently skipped if key is missing.

Search strategy:
  - Dallas, TX (radius 30mi) + Remote — both filtered to Contract type
  - Date filter: last LISTED_AT_DAYS
  - Rate filter: >= MIN_HOURLY_RATE
"""

import httpx
import time
import random
from datetime import datetime, timezone, timedelta

from config import (
    JOB_SEARCH_KEYWORD, PRIMARY_LOCATION, INCLUDE_REMOTE,
    MIN_HOURLY_RATE, LISTED_AT_SECONDS,
)
from job_tracker import JobTracker
from utils import meets_rate

try:
    from config import ZIPRECRUITER_API_KEY
except ImportError:
    ZIPRECRUITER_API_KEY = ""

ZR_API = "https://api.ziprecruiter.com/jobs/v1"

_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
    "Accept": "application/json",
}


class ZipRecruiterBot:
    def __init__(self, tracker: JobTracker):
        self.tracker = tracker

    def _fetch(self, location: str | None, remote: bool = False) -> list[dict]:
        if not ZIPRECRUITER_API_KEY:
            return []

        params: dict = {
            "search":          JOB_SEARCH_KEYWORD,
            "days_ago":        max(1, LISTED_AT_SECONDS // 86400),
            "employment_type": "Contract",
            "api_key":         ZIPRECRUITER_API_KEY,
            "jobs_per_page":   25,
            "page":            1,
        }
        if location:
            params["location"]      = location
            params["radius_miles"]  = 30
        if remote:
            params["remote"]        = True

        jobs: list[dict] = []
        try:
            resp = httpx.get(ZR_API, params=params, headers=_HEADERS, timeout=15)
            resp.raise_for_status()
            data = resp.json()
            if not data.get("success"):
                print(f"  [ZipRecruiter] API error: {data.get('error', 'unknown')}")
                return []
            jobs = data.get("jobs", [])
        except Exception as e:
            print(f"  [ZipRecruiter] Fetch error: {e}")

        return jobs

    def search_jobs(self) -> list[dict]:
        seen: dict[str, dict] = {}
        city = f"{PRIMARY_LOCATION.split(',')[0].strip()}, {PRIMARY_LOCATION.split(',')[1].strip()}"

        # Dallas contract jobs
        print(f"[ZipRecruiter] Search 1: Contract '{JOB_SEARCH_KEYWORD}' near {city}")
        for j in self._fetch(location=city):
            if j.get("id"):
                seen[j["id"]] = j
        print(f"  → {len(seen)} results")

        # Remote contract jobs
        if INCLUDE_REMOTE:
            print(f"[ZipRecruiter] Search 2: Remote contract '{JOB_SEARCH_KEYWORD}'")
            before = len(seen)
            for j in self._fetch(location=None, remote=True):
                seen.setdefault(j["id"], j)
            print(f"  → {len(seen) - before} new remote results")

        return list(seen.values())

    @staticmethod
    def _extract(job: dict) -> dict:
        return {
            "job_id":      f"zr-{job.get('id', '')}",
            "title":       job.get("name", ""),
            "company":     (job.get("hiring_company") or {}).get("name", "Unknown"),
            "url":         job.get("url", ""),
            "description": job.get("snippet", ""),
        }

    def run(self):
        if not ZIPRECRUITER_API_KEY:
            print("[ZipRecruiter] Skipped — ZIPRECRUITER_API_KEY not set in .env")
            return

        raw       = self.search_jobs()
        parsed    = [self._extract(j) for j in raw]
        new_jobs  = [j for j in parsed if not self.tracker.already_applied(j["job_id"])]
        saved     = 0
        skipped   = 0

        for job in new_jobs:
            status = "Collected - Manual Apply"
            if not meets_rate(job["description"], MIN_HOURLY_RATE):
                status  = f"Skipped - Rate Below ${MIN_HOURLY_RATE}/hr"
                skipped += 1
            else:
                saved += 1

            self.tracker.log_application(
                platform="ZipRecruiter",
                job_id=job["job_id"],
                title=job["title"],
                company=job["company"],
                url=job["url"],
                status=status,
            )
            time.sleep(random.uniform(0.5, 1.0))

        print(f"[ZipRecruiter] Done — {saved} collected, {skipped} skipped (rate < ${MIN_HOURLY_RATE}/hr)")
