"""
Indeed job search — via Indeed's public RSS feed (no API key needed).

Search strategy:
  - RSS feed: contract jobs near Dallas, TX + separate remote search
  - Date filter: last LISTED_AT_DAYS
  - Rate filter: >= MIN_HOURLY_RATE
  - Results logged to tracker as "Collected - Manual Apply"
"""

import re
import xml.etree.ElementTree as ET
import httpx
from datetime import datetime, timezone, timedelta

from config import JOB_SEARCH_KEYWORDS, JOB_SEARCH_KEYWORD, PRIMARY_LOCATION, INCLUDE_REMOTE, MIN_HOURLY_RATE, LISTED_AT_SECONDS
from job_tracker import JobTracker
from utils import meets_rate

INDEED_RSS = "https://www.indeed.com/rss"

_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept": "application/rss+xml, application/xml, text/xml, */*",
    "Accept-Language": "en-US,en;q=0.9",
}

# Indeed pubDate: "Mon, 03 Jun 2024 12:00:00 GMT"
_DATE_FMT = "%a, %d %b %Y %H:%M:%S %Z"


def _parse_pub_date(s: str) -> datetime | None:
    try:
        return datetime.strptime(s.strip(), _DATE_FMT).replace(tzinfo=timezone.utc)
    except Exception:
        return None


def _strip_html(text: str) -> str:
    return re.sub(r"<[^>]+>", " ", text).strip()


class IndeedBot:
    def __init__(self, tracker: JobTracker):
        self.tracker = tracker

    def _fetch(self, query: str, location: str | None) -> list[dict]:
        params: dict = {
            "q": query,
            "sort": "date",
            "fromage": max(1, LISTED_AT_SECONDS // 86400),
            "jt": "contract",
        }
        if location:
            params["l"] = location

        try:
            resp = httpx.get(INDEED_RSS, params=params, headers=_HEADERS, timeout=15, follow_redirects=True)
            resp.raise_for_status()
        except Exception as e:
            print(f"  [Indeed] Fetch error: {e}")
            return []

        try:
            root = ET.fromstring(resp.text)
        except ET.ParseError as e:
            print(f"  [Indeed] XML parse error: {e}")
            return []

        cutoff = datetime.now(timezone.utc) - timedelta(seconds=LISTED_AT_SECONDS)
        jobs: list[dict] = []

        for item in root.findall(".//item"):
            raw_title = item.findtext("title", "")
            link      = item.findtext("link", "")
            desc_html = item.findtext("description", "")
            pub_date  = item.findtext("pubDate", "")
            guid      = item.findtext("guid", link)

            # Drop jobs older than the window
            dt = _parse_pub_date(pub_date)
            if dt and dt < cutoff:
                continue

            # Title format: "Job Title - Company - City, ST"
            parts   = raw_title.split(" - ")
            title   = parts[0].strip() if parts else raw_title
            company = parts[1].strip() if len(parts) > 1 else "Unknown"

            # Stable job ID from the jk= URL parameter
            m = re.search(r"jk=([a-f0-9]+)", link)
            job_id = f"indeed-{m.group(1)}" if m else f"indeed-{abs(hash(guid))}"

            jobs.append({
                "job_id":      job_id,
                "title":       title,
                "company":     company,
                "url":         link,
                "description": _strip_html(desc_html),
                "posted_at":   pub_date,
            })

        return jobs

    def search_jobs(self) -> list[dict]:
        seen: dict[str, dict] = {}
        state = PRIMARY_LOCATION.split(",")[0].strip()   # "Texas"

        for kw in JOB_SEARCH_KEYWORDS:
            query = f"{kw} contract"

            # TX jobs
            print(f"[Indeed] Search: '{query}' in {state}")
            before = len(seen)
            for j in self._fetch(query, state):
                seen.setdefault(j["job_id"], j)
            print(f"  → {len(seen) - before} new results")

            # Remote jobs
            if INCLUDE_REMOTE:
                print(f"[Indeed] Search: '{query}' Remote")
                before = len(seen)
                for j in self._fetch(f"{query} remote", None):
                    seen.setdefault(j["job_id"], j)
                print(f"  → {len(seen) - before} new remote results")

        return list(seen.values())

    def run(self):
        jobs     = self.search_jobs()
        new_jobs = [j for j in jobs if not self.tracker.already_applied(j["job_id"])]
        saved    = 0
        skipped  = 0

        for job in new_jobs:
            status = "Collected - Manual Apply"
            if not meets_rate(job["description"], MIN_HOURLY_RATE):
                status  = f"Skipped - Rate Below ${MIN_HOURLY_RATE}/hr"
                skipped += 1
            else:
                saved += 1

            self.tracker.log_application(
                platform="Indeed",
                job_id=job["job_id"],
                title=job["title"],
                company=job["company"],
                url=job["url"],
                status=status,
                posted_at=job.get("posted_at", ""),
            )

        print(f"[Indeed] Done — {saved} collected, {skipped} skipped (rate < ${MIN_HOURLY_RATE}/hr)")
