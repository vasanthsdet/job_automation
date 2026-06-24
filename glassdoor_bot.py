"""
Glassdoor job search — HTML scraping via BeautifulSoup.

Note: Glassdoor aggressively blocks automated requests and requires
JavaScript for most pages. This bot returns 0 results silently when
blocked (HTTP 403/429) rather than crashing the workflow.

Search strategy:
  - glassdoor.com/Job/jobs.htm with q= and l= params
  - Texas + Remote searches
  - Date/contract filter applied post-fetch (no server-side param)
"""

import re
import time
import random
from datetime import datetime, timezone

import requests
from bs4 import BeautifulSoup

from config import (
    JOB_SEARCH_KEYWORDS, PRIMARY_LOCATION, INCLUDE_REMOTE,
    MIN_HOURLY_RATE, LISTED_AT_SECONDS,
)
from job_tracker import JobTracker
from utils import meets_rate

GLASSDOOR_SEARCH = "https://www.glassdoor.com/Job/jobs.htm"
GLASSDOOR_HOME   = "https://www.glassdoor.com"

_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/125.0.0.0 Safari/537.36"
    ),
    "Accept":          "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
    "Referer":         "https://www.glassdoor.com/",
}

# CSS selectors — Glassdoor's class names change with UI updates;
# the fallbacks cover older and newer markup versions.
_CARD_SEL    = "li.react-job-listing, li[data-test='jobListing'], article.JobCard, div[data-jobid]"
_TITLE_SEL   = "a.JobCard_jobTitle___7I6y, a[data-test='job-title'], div.job-title a, a[id^='job-title']"
_COMPANY_SEL = "div.EmployerProfile_compactEmployerName__LE242, span[data-test='employer-name'], div.employer-name"
_LOC_SEL     = "div.JobCard_location__N_iYE, span[data-test='emp-location'], div.location"
_SALARY_SEL  = "div.JobCard_salaryEstimate__arV5J, span[data-test='detailSalary'], span.salary-estimate"
_LINK_SEL    = "a.JobCard_jobTitle___7I6y, a[data-test='job-title'], a[href*='/job-listing/'], a[href*='/partner/jobListing.htm']"

_JOB_ID_RE = re.compile(r"/job-listing/[^/]+-(\d+)", re.IGNORECASE)


def _jid_from_href(href: str) -> str:
    m = _JOB_ID_RE.search(href)
    return m.group(1) if m else str(abs(hash(href)))


class GlassdoorBot:
    def __init__(self, tracker: JobTracker):
        self.tracker = tracker
        self._session: requests.Session | None = None

    def _get_session(self) -> requests.Session:
        if self._session:
            return self._session
        s = requests.Session()
        s.headers.update(_HEADERS)
        # Seed a session cookie by visiting the homepage first
        try:
            time.sleep(random.uniform(2, 3))
            s.get(GLASSDOOR_HOME, timeout=15)
        except Exception:
            pass
        self._session = s
        return s

    def _fetch(self, keyword: str, location: str) -> list[dict]:
        s = self._get_session()
        params = {
            "sc.keyword": keyword,
            "locT":       "C",
            "locId":      "1",   # default to US
            "jobType":    "contract",
            "fromAge":    max(1, LISTED_AT_SECONDS // 86400),
        }
        if location:
            params["sc.keyword"] = f"{keyword} contract"
            params["locKeyword"] = location

        try:
            time.sleep(random.uniform(3, 5))
            resp = s.get(GLASSDOOR_SEARCH, params=params, timeout=20)
            print(f"  [Glassdoor] HTTP {resp.status_code} — '{keyword}' in '{location}'")
            if resp.status_code in (403, 429, 503):
                print(f"  [Glassdoor] Blocked ({resp.status_code}) — skipping")
                return []
            if resp.status_code != 200:
                return []
        except Exception as e:
            print(f"  [Glassdoor] Request error: {e}")
            return []

        soup  = BeautifulSoup(resp.text, "lxml")
        cards = soup.select(_CARD_SEL)
        print(f"  [Glassdoor] {len(cards)} cards found")

        jobs = []
        for card in cards:
            title_el   = card.select_one(_TITLE_SEL)
            company_el = card.select_one(_COMPANY_SEL)
            loc_el     = card.select_one(_LOC_SEL)
            salary_el  = card.select_one(_SALARY_SEL)
            link_el    = card.select_one(_LINK_SEL)

            title   = title_el.get_text(strip=True)   if title_el   else ""
            company = company_el.get_text(strip=True)  if company_el else "Unknown"
            loc     = loc_el.get_text(strip=True)      if loc_el     else location
            salary  = salary_el.get_text(strip=True)   if salary_el  else ""
            href    = link_el.get("href", "")          if link_el    else ""
            if href and href.startswith("/"):
                href = GLASSDOOR_HOME + href
            jid = _jid_from_href(href)

            if not title:
                continue

            jobs.append({
                "id":          jid,
                "title":       title,
                "company":     company,
                "location":    loc,
                "url":         href or GLASSDOOR_SEARCH,
                "description": salary,   # salary hint used for rate filter
                "posted_at":   "",
            })

        return jobs

    def search_jobs(self) -> list[dict]:
        seen: dict[str, dict] = {}
        city = PRIMARY_LOCATION.split(",")[0].strip()

        for i, kw in enumerate(JOB_SEARCH_KEYWORDS):
            if i > 0:
                time.sleep(random.uniform(5, 8))

            print(f"[Glassdoor] Search: '{kw}' in {city}, TX")
            before = len(seen)
            for j in self._fetch(kw, f"{city}, TX"):
                seen.setdefault(j["id"], j)
            print(f"  → {len(seen) - before} new results (Texas)")

            if INCLUDE_REMOTE:
                time.sleep(random.uniform(3, 6))
                print(f"[Glassdoor] Search: '{kw}' Remote")
                before = len(seen)
                for j in self._fetch(kw, "Remote"):
                    seen.setdefault(j["id"], j)
                print(f"  → {len(seen) - before} new remote results")

        print(f"[Glassdoor] {len(seen)} unique jobs found")
        return list(seen.values())

    @staticmethod
    def _extract(job: dict) -> dict:
        return {
            "job_id":      f"glassdoor-{job['id']}",
            "title":       job.get("title", ""),
            "company":     job.get("company") or "Unknown",
            "url":         job.get("url", ""),
            "description": job.get("description", ""),
            "posted_at":   job.get("posted_at", ""),
        }

    def run(self):
        raw_jobs = self.search_jobs()
        parsed   = [self._extract(j) for j in raw_jobs]
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
                platform="Glassdoor",
                job_id=job["job_id"],
                title=job["title"],
                company=job["company"],
                url=job["url"],
                status=status,
                posted_at=job.get("posted_at", ""),
            )
            time.sleep(random.uniform(0.3, 0.6))

        print(f"[Glassdoor] Done — {saved} collected, {skipped} skipped (rate < ${MIN_HOURLY_RATE}/hr)")
