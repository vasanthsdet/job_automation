"""
Remotive job search — public API, no key required.
API: https://remotive.com/api/remote-jobs

Covers remote tech QA/testing roles. US-eligible filter applied.
Replaces Wellfound which has no public API (requires OAuth).
"""

import time
import random
import requests
from datetime import datetime, timezone, timedelta

from config import JOB_SEARCH_KEYWORDS, MIN_HOURLY_RATE, LISTED_AT_SECONDS
from job_tracker import JobTracker
from utils import meets_rate

REMOTIVE_API = "https://remotive.com/api/remote-jobs"

_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
    "Accept":     "application/json",
}

_QA_WORDS = {"qa", "qe", "quality", "test", "sdet", "automation", "tester", "uat"}

_BLOCKED_LOCATIONS = {
    "india", "pakistan", "europe", "uk", "canada", "australia",
    "latam", "africa", "asia", "worldwide",
}


def _is_qa_title(title: str) -> bool:
    t = title.lower()
    return any(w in t for w in _QA_WORDS)


def _is_us_eligible(job: dict) -> bool:
    loc = (job.get("candidate_required_location") or "").lower()
    if not loc or loc in ("anywhere", "worldwide", "remote"):
        return True
    if "us" in loc or "usa" in loc or "united states" in loc or "north america" in loc:
        return True
    return not any(blocked in loc for blocked in _BLOCKED_LOCATIONS)


class RemotiveBot:
    def __init__(self, tracker: JobTracker):
        self.tracker = tracker

    def _fetch(self, keyword: str) -> list[dict]:
        try:
            resp = requests.get(
                REMOTIVE_API,
                params={"search": keyword, "limit": 100},
                headers=_HEADERS,
                timeout=20,
            )
            if resp.status_code == 200:
                return resp.json().get("jobs", [])
            print(f"[Remotive] HTTP {resp.status_code}")
            return []
        except Exception as e:
            print(f"[Remotive] Error: {e}")
            return []

    def search_jobs(self) -> list[dict]:
        seen: dict[str, dict] = {}
        cutoff = datetime.now(timezone.utc) - timedelta(seconds=LISTED_AT_SECONDS)

        for i, kw in enumerate(JOB_SEARCH_KEYWORDS):
            if i > 0:
                time.sleep(random.uniform(2, 4))

            print(f"[Remotive] Search: '{kw}' Remote QA")
            before = len(seen)

            for job in self._fetch(kw):
                jid = str(job.get("id", ""))
                if not jid or not _is_qa_title(job.get("title", "")):
                    continue
                if not _is_us_eligible(job):
                    continue

                pub = job.get("publication_date", "")
                if pub:
                    try:
                        posted = datetime.fromisoformat(pub.replace("Z", "+00:00"))
                        if posted < cutoff:
                            continue
                    except Exception:
                        pass

                seen[jid] = job

            print(f"  → {len(seen) - before} new US-eligible QA results")

        print(f"[Remotive] {len(seen)} unique jobs found")
        return list(seen.values())

    @staticmethod
    def _extract(job: dict) -> dict:
        jid = str(job.get("id", ""))
        return {
            "job_id":      f"remotive-{jid}",
            "title":       job.get("title", ""),
            "company":     job.get("company_name", "Unknown"),
            "url":         job.get("url", ""),
            "description": job.get("description", ""),
        }

    def run(self):
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
                platform="Remotive",
                job_id=job["job_id"],
                title=job["title"],
                company=job["company"],
                url=job["url"],
                status=status,
            )
            time.sleep(random.uniform(0.2, 0.5))

        print(f"[Remotive] Done — {saved} collected, {skipped} skipped (rate < ${MIN_HOURLY_RATE}/hr)")
