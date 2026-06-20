"""
RemoteOK job search — public JSON API, no API key required.
API: https://remoteok.com/api

Best for: remote contract QA/SDET roles posted worldwide.
Rate: ~1 req/min recommended (single endpoint, all jobs returned at once).
"""

import httpx
import re
from datetime import datetime, timezone, timedelta

from config import JOB_SEARCH_KEYWORD, MIN_HOURLY_RATE, LISTED_AT_SECONDS
from job_tracker import JobTracker
from utils import meets_rate

REMOTEOK_API = "https://remoteok.com/api"

_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
    "Accept": "application/json",
    "Referer": "https://remoteok.com/",
}

# Tags RemoteOK uses for QA/testing roles
_QA_TAGS = {"qa", "testing", "sdet", "quality-assurance", "test", "automation", "selenium", "cypress"}

# Keywords to match in job title
_QA_TITLE_KEYWORDS = ["qa", "quality", "test", "sdet", "automation engineer"]


_US_LOCATIONS = {"usa", "united states", "us only", "north america", "u.s.",
                  "anywhere", "worldwide", "global", "remote", ""}
_NON_US = {"europe", "uk", "united kingdom", "india", "pakistan", "canada",
           "australia", "latam", "africa", "asia", "apac", "germany", "france",
           "netherlands", "poland", "ukraine", "brazil", "mexico", "singapore"}


def _is_us_eligible(job: dict) -> bool:
    loc = (job.get("location") or "").strip().lower()
    if not loc:
        return True
    if any(b in loc for b in _NON_US):
        return False
    return True  # unknown / worldwide / explicitly US → allow


def _is_qa_job(job: dict) -> bool:
    tags  = {t.lower() for t in (job.get("tags") or [])}
    title = job.get("position", "").lower()
    return bool(tags & _QA_TAGS) or any(kw in title for kw in _QA_TITLE_KEYWORDS)


def _strip_html(text: str) -> str:
    return re.sub(r"<[^>]+>", " ", text or "").strip()


class RemoteOKBot:
    def __init__(self, tracker: JobTracker):
        self.tracker = tracker

    def search_jobs(self) -> list[dict]:
        try:
            resp = httpx.get(REMOTEOK_API, headers=_HEADERS, timeout=20)
            resp.raise_for_status()
            raw = resp.json()
        except Exception as e:
            print(f"[RemoteOK] Fetch error: {e}")
            return []

        # First element is API metadata / legal notice — skip it
        listings = raw[1:] if isinstance(raw, list) and len(raw) > 1 else []

        cutoff  = datetime.now(timezone.utc) - timedelta(seconds=LISTED_AT_SECONDS)
        results = []

        for job in listings:
            if not _is_qa_job(job):
                continue
            if not _is_us_eligible(job):
                continue

            # Date filter via epoch (Unix timestamp)
            epoch = job.get("epoch")
            if epoch:
                posted = datetime.fromtimestamp(int(epoch), tz=timezone.utc)
                if posted < cutoff:
                    continue

            results.append(job)

        hours = LISTED_AT_SECONDS // 3600
        print(f"[RemoteOK] {len(results)} QA/SDET remote jobs in last {hours} hour(s)")
        return results

    def run(self):
        jobs     = self.search_jobs()
        saved    = 0
        skipped  = 0

        for job in jobs:
            job_id = f"remoteok-{job.get('id', '')}"

            if self.tracker.already_applied(job_id):
                continue

            description = _strip_html(job.get("description", "")) + " " + " ".join(job.get("tags") or [])
            url         = job.get("url") or f"https://remoteok.com/remote-jobs/{job.get('id', '')}"

            status = "Collected - Manual Apply"
            if not meets_rate(description, MIN_HOURLY_RATE):
                status  = f"Skipped - Rate Below ${MIN_HOURLY_RATE}/hr"
                skipped += 1
            else:
                saved += 1

            self.tracker.log_application(
                platform="RemoteOK",
                job_id=job_id,
                title=job.get("position", ""),
                company=job.get("company", "Unknown"),
                url=url,
                status=status,
            )

        print(f"[RemoteOK] Done — {saved} collected, {skipped} skipped (rate < ${MIN_HOURLY_RATE}/hr)")
