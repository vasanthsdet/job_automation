"""
Dice.com job search — pure HTTP via Dice's public REST API.

Search strategy:
  - Two passes: Dallas, TX (radius 30mi) + Remote
  - Filter: Contract employment type
  - Filter: Posted within last LISTED_AT_DAYS (default 3 days)
  - Filter: Hourly rate >= MIN_HOURLY_RATE ($60) where visible in description
"""

import time
import random
import ssl
import urllib3
from datetime import datetime, timezone, timedelta

import httpx
import requests

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

from config import (
    JOB_SEARCH_KEYWORDS, JOB_SEARCH_KEYWORD, PRIMARY_LOCATION,
    INCLUDE_REMOTE, MIN_HOURLY_RATE, LISTED_AT_SECONDS,
)
from job_tracker import JobTracker
from utils import meets_rate

DICE_SEARCH_API = "https://job-search-api.svc.dhigroupinc.com/v1/dice/jobs/search"
DICE_HOME       = "https://www.dice.com/jobs"

_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/125.0.0.0 Safari/537.36"
)


def _within_window(posted_date_str: str) -> bool:
    if not posted_date_str:
        return True
    try:
        dt = datetime.fromisoformat(posted_date_str.replace("Z", "+00:00"))
        cutoff = datetime.now(timezone.utc) - timedelta(seconds=LISTED_AT_SECONDS)
        return dt >= cutoff
    except Exception:
        return True


class DiceBot:
    def __init__(self, tracker: JobTracker):
        self.tracker = tracker
        self._session: requests.Session | None = None

    def _get_session(self) -> requests.Session:
        if self._session:
            return self._session
        s = requests.Session()
        s.verify = False
        s.headers.update({
            "User-Agent": _UA,
            "Accept-Language": "en-US,en;q=0.9",
        })
        # Seed cookies by visiting Dice homepage
        try:
            s.get(DICE_HOME, timeout=15)
            time.sleep(1)
        except Exception:
            pass
        self._session = s
        return s

    def _fetch_page(self, keyword: str, extra_params: dict) -> list[dict]:
        s = self._get_session()
        jobs: list[dict] = []
        for page in range(1, 4):
            params = {
                "q": keyword,
                "countryCode": "US",
                "page": page,
                "pageSize": 20,
                "language": "en",
                "employmentType": "CONTRACTS",
                "sortBy": "-postedDate",
                **extra_params,
            }
            headers = {
                "Accept": "application/json, text/plain, */*",
                "Origin": "https://www.dice.com",
                "Referer": "https://www.dice.com/jobs",
                "Sec-Fetch-Dest": "empty",
                "Sec-Fetch-Mode": "cors",
                "Sec-Fetch-Site": "cross-site",
            }
            try:
                resp = s.get(DICE_SEARCH_API, params=params, headers=headers, timeout=15)
                resp.raise_for_status()
                hits = resp.json().get("data", [])
                recent = [h for h in hits if _within_window(h.get("postedDate", ""))]
                jobs.extend(recent)
                if len(recent) < len(hits) or len(hits) < 20:
                    break
                time.sleep(random.uniform(1, 2))
            except Exception as e:
                print(f"  [Dice] API error page {page}: {e}")
                break
        return jobs

    def search_jobs(self) -> list[dict]:
        seen: dict[str, dict] = {}

        for kw in JOB_SEARCH_KEYWORDS:
            # TX jobs
            print(f"[Dice] Search: Contract '{kw}' in Texas")
            for j in self._fetch_page(kw, {"location": "Texas", "radius": 100, "radiusUnit": "mi"}):
                if j.get("id"):
                    seen[j["id"]] = j
            print(f"  → {len(seen)} total so far")

            # Remote jobs
            if INCLUDE_REMOTE:
                print(f"[Dice] Search: Remote contract '{kw}'")
                before = len(seen)
                for j in self._fetch_page(kw, {"workFromHome": "true"}):
                    if j.get("id"):
                        seen[j["id"]] = j
                print(f"  → {len(seen) - before} new remote results")

        all_jobs = list(seen.values())
        print(f"[Dice] {len(all_jobs)} unique contract jobs found")
        return all_jobs

    @staticmethod
    def _extract(job: dict) -> dict:
        jid = job.get("id", "")
        return {
            "job_id": f"dice-{jid}",
            "title": job.get("title", ""),
            "company": job.get("company", "Unknown"),
            "location": job.get("location", ""),
            "url": job.get("applyUrl") or f"https://www.dice.com/job-detail/{jid}",
            "description": job.get("summary", "") or job.get("jobDescription", ""),
        }

    def run(self):
        raw_jobs = self.search_jobs()
        parsed = [self._extract(j) for j in raw_jobs]
        new_jobs = [j for j in parsed if not self.tracker.already_applied(j["job_id"])]

        skipped_rate = 0
        saved = 0

        for job in new_jobs:
            # Hourly rate gate
            if not meets_rate(job["description"], MIN_HOURLY_RATE):
                skipped_rate += 1
                self.tracker.log_application(
                    platform="Dice", job_id=job["job_id"],
                    title=job["title"], company=job["company"], url=job["url"],
                    status=f"Skipped - Rate Below ${MIN_HOURLY_RATE}/hr",
                )
                continue

            self.tracker.log_application(
                platform="Dice", job_id=job["job_id"],
                title=job["title"], company=job["company"], url=job["url"],
                status="Collected - Manual Apply",
            )
            saved += 1

        print(
            f"[Dice] Done — {saved} collected, "
            f"{skipped_rate} skipped (rate below ${MIN_HOURLY_RATE}/hr)"
        )
