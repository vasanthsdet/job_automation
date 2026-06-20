"""
Dice.com job search — REST API with RSS fallback.

Primary:  https://job-search-api.svc.dhigroupinc.com/v1/dice/jobs/search
Fallback: https://www.dice.com/jobs/rss/rss.html  (if API returns 0 results)

Search strategy:
  - Texas (100 mi radius) + Remote US
  - Filter: Contract employment type
  - Filter: Posted within LISTED_AT_DAYS
  - Filter: Hourly rate >= MIN_HOURLY_RATE where visible in description
"""

import time
import random
import urllib3
from datetime import datetime, timezone, timedelta
from email.utils import parsedate_to_datetime
from xml.etree import ElementTree as ET

import requests

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

from config import (
    JOB_SEARCH_KEYWORDS,
    INCLUDE_REMOTE, MIN_HOURLY_RATE, LISTED_AT_SECONDS,
)
from job_tracker import JobTracker
from utils import meets_rate

_LISTED_AT_DAYS = max(1, LISTED_AT_SECONDS // 86400)

DICE_SEARCH_API = "https://job-search-api.svc.dhigroupinc.com/v1/dice/jobs/search"
DICE_HOME       = "https://www.dice.com"
DICE_RSS_BASE   = "https://www.dice.com/jobs/rss/rss.html"

_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/125.0.0.0 Safari/537.36"
)

_API_HEADERS = {
    "User-Agent":      _UA,
    "Accept":          "application/json, text/plain, */*",
    "Accept-Language": "en-US,en;q=0.9",
    "Accept-Encoding": "gzip, deflate, br",
    "Origin":          "https://www.dice.com",
    "Referer":         "https://www.dice.com/jobs",
    "Sec-Fetch-Dest":  "empty",
    "Sec-Fetch-Mode":  "cors",
    "Sec-Fetch-Site":  "cross-site",
}

_RSS_HEADERS = {
    "User-Agent": _UA,
    "Accept":     "application/rss+xml, application/xml, */*",
}

# Dice server-side date filter values
_POSTED_DATE_MAP = {
    1: "ONE",
    3: "THREE",
    7: "SEVEN",
    30: "THIRTY",
}


def _within_window(date_str: str) -> bool:
    if not date_str:
        return True
    try:
        dt = datetime.fromisoformat(date_str.replace("Z", "+00:00"))
        cutoff = datetime.now(timezone.utc) - timedelta(seconds=LISTED_AT_SECONDS)
        return dt >= cutoff
    except Exception:
        return True


def _rfc2822_within_window(date_str: str) -> bool:
    if not date_str:
        return True
    try:
        dt = parsedate_to_datetime(date_str).astimezone(timezone.utc)
        cutoff = datetime.now(timezone.utc) - timedelta(seconds=LISTED_AT_SECONDS)
        return dt >= cutoff
    except Exception:
        return True


class DiceBot:
    def __init__(self, tracker: JobTracker):
        self.tracker = tracker
        self._session: requests.Session | None = None
        self._api_ok = True

    # ── Session ───────────────────────────────────────────────────

    def _get_session(self) -> requests.Session:
        if self._session:
            return self._session
        s = requests.Session()
        s.headers.update({"User-Agent": _UA, "Accept-Language": "en-US,en;q=0.9"})
        try:
            r = s.get(DICE_HOME, timeout=15, allow_redirects=True)
            print(f"[Dice] Homepage seed: HTTP {r.status_code}")
            time.sleep(random.uniform(1, 2))
        except Exception as e:
            print(f"[Dice] Homepage seed failed: {e}")
        self._session = s
        return s

    # ── REST API ──────────────────────────────────────────────────

    def _api_fetch(self, keyword: str, extra_params: dict) -> list[dict]:
        if not self._api_ok:
            return []
        s = self._get_session()
        jobs: list[dict] = []

        posted_filter = _POSTED_DATE_MAP.get(_LISTED_AT_DAYS, "THREE")

        for page in range(1, 4):
            params = {
                "q":              keyword,
                "countryCode":    "US",
                "page":           page,
                "pageSize":       20,
                "language":       "en",
                "employmentType": "CONTRACTS",
                "postedDate":     posted_filter,
                "sortBy":         "-postedDate",
                **extra_params,
            }
            try:
                resp = s.get(
                    DICE_SEARCH_API,
                    params=params,
                    headers=_API_HEADERS,
                    timeout=20,
                )
                print(f"  [Dice API] page={page} status={resp.status_code}")
                if resp.status_code in (401, 403):
                    print("  [Dice API] Auth required — switching to RSS fallback")
                    self._api_ok = False
                    return []
                if resp.status_code == 404:
                    print("  [Dice API] Endpoint not found — switching to RSS fallback")
                    self._api_ok = False
                    return []
                if resp.status_code != 200:
                    body_snippet = resp.text[:200] if resp.text else "(empty)"
                    print(f"  [Dice API] Unexpected {resp.status_code}: {body_snippet}")
                    break

                payload = resp.json()
                hits = payload.get("data", [])
                print(f"  [Dice API] page={page} hits={len(hits)}")
                recent = [h for h in hits if _within_window(h.get("postedDate", ""))]
                jobs.extend(recent)
                if len(hits) < 20:
                    break
                time.sleep(random.uniform(1, 2))
            except Exception as e:
                print(f"  [Dice API] Error page={page}: {e}")
                if page == 1:
                    self._api_ok = False
                break
        return jobs

    # ── RSS fallback ──────────────────────────────────────────────

    def _rss_fetch(self, keyword: str, location: str = "", remote: bool = False) -> list[dict]:
        params: dict = {"q": keyword, "type": "contract"}
        if remote:
            params["remote"] = "true"
        elif location:
            params["l"] = location

        try:
            resp = requests.get(
                DICE_RSS_BASE,
                params=params,
                headers=_RSS_HEADERS,
                timeout=20,
            )
            print(f"  [Dice RSS] status={resp.status_code} len={len(resp.content)}")
            if resp.status_code != 200:
                return []
            root = ET.fromstring(resp.content)
            ns   = {"atom": "http://www.w3.org/2005/Atom"}
            jobs = []
            for item in root.iter("item"):
                pub = item.findtext("pubDate", "")
                if not _rfc2822_within_window(pub):
                    continue
                jid_el = item.find("{http://purl.org/dc/elements/1.1/}identifier")
                jid    = jid_el.text if jid_el is not None else item.findtext("link", "").split("/")[-1]
                jobs.append({
                    "id":          jid or item.findtext("link", ""),
                    "title":       item.findtext("title", ""),
                    "company":     item.findtext("{http://purl.org/dc/elements/1.1/}publisher", "Unknown"),
                    "location":    item.findtext("{http://purl.org/dc/elements/1.1/}subject", ""),
                    "applyUrl":    item.findtext("link", ""),
                    "summary":     item.findtext("description", ""),
                    "postedDate":  pub,
                    "_source":     "rss",
                })
            return jobs
        except Exception as e:
            print(f"  [Dice RSS] Error: {e}")
            return []

    # ── Unified search ────────────────────────────────────────────

    def search_jobs(self) -> list[dict]:
        seen: dict[str, dict] = {}

        for i, kw in enumerate(JOB_SEARCH_KEYWORDS):
            if i > 0:
                time.sleep(random.uniform(2, 3))

            # Texas on-site
            print(f"[Dice] Search: Contract '{kw}' in Texas")
            before = len(seen)
            api_jobs = self._api_fetch(kw, {"location": "Texas", "radius": 100, "radiusUnit": "mi"})
            for j in api_jobs:
                if j.get("id"):
                    seen[j["id"]] = j

            if not api_jobs and not self._api_ok:
                rss_jobs = self._rss_fetch(kw, location="Texas")
                for j in rss_jobs:
                    if j.get("id"):
                        seen.setdefault(j["id"], j)
                print(f"  → {len(seen) - before} RSS results (Texas)")
            else:
                print(f"  → {len(seen) - before} API results (Texas)")

            # Remote USA
            if INCLUDE_REMOTE:
                time.sleep(random.uniform(1, 2))
                print(f"[Dice] Search: Remote contract '{kw}'")
                before = len(seen)
                api_remote = self._api_fetch(kw, {"workFromHome": True})
                for j in api_remote:
                    if j.get("id"):
                        seen.setdefault(j["id"], j)

                if not api_remote and not self._api_ok:
                    rss_jobs = self._rss_fetch(kw, remote=True)
                    for j in rss_jobs:
                        if j.get("id"):
                            seen.setdefault(j["id"], j)
                    print(f"  → {len(seen) - before} RSS results (Remote)")
                else:
                    print(f"  → {len(seen) - before} API results (Remote)")

        print(f"[Dice] {len(seen)} unique contract jobs found")
        return list(seen.values())

    # ── Extract / normalize ───────────────────────────────────────

    @staticmethod
    def _extract(job: dict) -> dict:
        jid = job.get("id", "")
        return {
            "job_id":      f"dice-{jid}",
            "title":       job.get("title", ""),
            "company":     job.get("company", "Unknown"),
            "location":    job.get("location", ""),
            "url":         job.get("applyUrl") or f"https://www.dice.com/job-detail/{jid}",
            "description": job.get("summary", "") or job.get("jobDescription", ""),
        }

    # ── Main run ──────────────────────────────────────────────────

    def run(self):
        raw_jobs = self.search_jobs()
        parsed   = [self._extract(j) for j in raw_jobs]
        new_jobs = [j for j in parsed if not self.tracker.already_applied(j["job_id"])]

        saved        = 0
        skipped_rate = 0

        for job in new_jobs:
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

        print(f"[Dice] Done — {saved} collected, {skipped_rate} skipped (rate < ${MIN_HOURLY_RATE}/hr)")
