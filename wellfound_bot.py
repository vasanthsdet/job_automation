"""
Wellfound (AngelList) job search — public job board API.
No API key required.

Covers: startup/tech QA roles, strong remote coverage.
URL: https://wellfound.com/jobs
"""

import time
import random
import requests

from config import (
    JOB_SEARCH_KEYWORDS, PRIMARY_LOCATION,
    INCLUDE_REMOTE, MIN_HOURLY_RATE, LISTED_AT_SECONDS,
)
from job_tracker import JobTracker
from utils import meets_rate

# Wellfound internal search API (used by their web app)
WELLFOUND_SEARCH = "https://wellfound.com/api/v2/search"

_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/125.0.0.0 Safari/537.36"
    ),
    "Accept":          "application/json, text/plain, */*",
    "Accept-Language": "en-US,en;q=0.9",
    "Referer":         "https://wellfound.com/jobs",
    "x-requested-with": "XMLHttpRequest",
}

_QA_WORDS = {"qa", "qe", "quality", "test", "sdet", "automation", "tester", "uat"}

_STATE = PRIMARY_LOCATION.split(",")[0].strip()   # e.g. "Texas"


def _is_qa_title(title: str) -> bool:
    t = title.lower()
    return any(w in t for w in _QA_WORDS)


class WellfoundBot:
    def __init__(self, tracker: JobTracker):
        self.tracker = tracker
        self._api_ok  = True   # flip False on first auth/404 to avoid repeated calls

    # ── Fetch ─────────────────────────────────────────────────

    def _fetch(self, keyword: str, location: str = "", remote: bool = False) -> list[dict]:
        if not self._api_ok:
            return []

        params: dict = {
            "q":          keyword,
            "type":       "jobs",
            "job_types[]": "contract",
        }
        if remote:
            params["remote"] = "true"
        elif location:
            params["location"] = location

        for attempt in range(2):
            try:
                resp = requests.get(
                    WELLFOUND_SEARCH,
                    params=params,
                    headers=_HEADERS,
                    timeout=20,
                )
                if resp.status_code == 200:
                    data = resp.json()
                    # Handle different response shapes
                    return (
                        data.get("jobs")
                        or data.get("results")
                        or data.get("data", {}).get("jobs", [])
                        or []
                    )
                if resp.status_code in (401, 403):
                    print("[Wellfound] API requires authentication — skipping remaining searches")
                    self._api_ok = False
                    return []
                if resp.status_code == 404:
                    print("[Wellfound] API endpoint not found — skipping remaining searches")
                    self._api_ok = False
                    return []
                if resp.status_code == 429 and attempt == 0:
                    print("[Wellfound] Rate-limited — waiting 30s...")
                    time.sleep(30)
                    continue
                print(f"[Wellfound] HTTP {resp.status_code}")
                return []
            except Exception as e:
                if attempt == 0:
                    time.sleep(5)
                    continue
                print(f"[Wellfound] Error: {e}")
                return []
        return []

    # ── Search ────────────────────────────────────────────────

    def search_jobs(self) -> list[dict]:
        seen: dict[str, dict] = {}

        for i, kw in enumerate(JOB_SEARCH_KEYWORDS):
            if i > 0:
                time.sleep(random.uniform(4, 7))

            # On-site / hybrid in primary state
            print(f"[Wellfound] Search: '{kw}' contract in {_STATE}")
            before = len(seen)
            for job in self._fetch(kw, location=_STATE):
                jid = str(job.get("id", ""))
                if jid and _is_qa_title(job.get("title", "")):
                    seen[jid] = job
            print(f"  → {len(seen) - before} results")

            # Remote — USA only
            if INCLUDE_REMOTE:
                time.sleep(random.uniform(2, 4))
                print(f"[Wellfound] Search: '{kw}' Remote contract")
                before = len(seen)
                for job in self._fetch(kw, remote=True):
                    jid = str(job.get("id", ""))
                    if jid and _is_qa_title(job.get("title", "")):
                        seen.setdefault(jid, job)
                print(f"  → {len(seen) - before} new Remote results")

        print(f"[Wellfound] {len(seen)} unique QA jobs found")
        return list(seen.values())

    # ── Extract / normalize ───────────────────────────────────

    @staticmethod
    def _extract(job: dict) -> dict:
        jid  = str(job.get("id", ""))
        slug = job.get("slug", "")
        # Company can be nested dict or plain string depending on API response shape
        co   = job.get("startup") or job.get("company") or {}
        company_name = co.get("name", "Unknown") if isinstance(co, dict) else str(co)
        url  = (
            job.get("url")
            or job.get("job_url")
            or (f"https://wellfound.com/jobs/{slug}" if slug else "https://wellfound.com/jobs")
        )
        return {
            "job_id":      f"wellfound-{jid}",
            "title":       job.get("title", job.get("role", "")),
            "company":     company_name,
            "url":         url,
            "description": job.get("description", ""),
        }

    # ── Main run ──────────────────────────────────────────────

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
                platform="Wellfound",
                job_id=job["job_id"],
                title=job["title"],
                company=job["company"],
                url=job["url"],
                status=status,
            )
            time.sleep(random.uniform(0.2, 0.5))

        print(f"[Wellfound] Done — {saved} collected, {skipped} skipped (rate < ${MIN_HOURLY_RATE}/hr)")
