"""
LinkedIn job search — pure HTTP, no browser.

Search strategy:
  - Run TWO searches per cycle: Dallas (on-site/hybrid) + Remote
  - Filter: Contract jobs only
  - Filter: Last 3 days (LISTED_AT_SECONDS)
  - Collect all jobs; Easy Apply jobs are flagged in the report for quick manual apply
"""

import json
import ssl
import time
import random
import urllib3
from pathlib import Path

import requests
from requests.cookies import RequestsCookieJar
from linkedin_api import Linkedin

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

from config import (
    LINKEDIN_EMAIL, LINKEDIN_PASSWORD,
    JOB_SEARCH_KEYWORDS, PRIMARY_LOCATION, INCLUDE_REMOTE,
    LISTED_AT_SECONDS,
)
from job_tracker import JobTracker

VOYAGER = "https://www.linkedin.com/voyager/api"


class LinkedInBot:
    def __init__(self, tracker: JobTracker):
        self.tracker = tracker
        self.api: Linkedin | None = None
        self.session     = None
        self._authed     = False

    # ── Auth ──────────────────────────────────────────────────

    COOKIES_FILE = "linkedin_cookies.json"

    def _load_browser_cookies(self) -> dict:
        p = Path(self.COOKIES_FILE)
        if not p.exists():
            return {}
        try:
            content = p.read_text(encoding="utf-8").strip().lstrip("﻿")
            return json.loads(content) if content else {}
        except Exception:
            return {}

    def login(self):
        if self._authed:
            print("[LinkedIn] Session already active — skipping re-login")
            return
        print("[LinkedIn] Authenticating via Voyager API (once per run)...")
        ssl._create_default_https_context = ssl._create_unverified_context

        browser_cookies = self._load_browser_cookies()
        li_at      = browser_cookies.get("li_at", "")
        jsessionid = browser_cookies.get("JSESSIONID", "")
        print(f"[LinkedIn] Stored cookies: {len(browser_cookies)} keys, li_at={'SET' if li_at else 'MISSING'}")

        if li_at:
            try:
                self.api = Linkedin(
                    "", "",
                    authenticate=True,
                    cookies={"li_at": li_at, "JSESSIONID": jsessionid},
                )
                self.session = self.api.client.session
                self.session.verify = False

                if isinstance(self.session.cookies, dict):
                    jar = RequestsCookieJar()
                    for k, v in self.session.cookies.items():
                        jar.set(k, v, domain=".linkedin.com", path="/")
                    self.session.cookies = jar
                elif not hasattr(self.session.cookies, "set"):
                    jar = RequestsCookieJar()
                    self.session.cookies = jar

                for k, v in browser_cookies.items():
                    if k not in ("li_at", "JSESSIONID"):
                        self.session.cookies.set(k, v, domain=".linkedin.com", path="/")

                print("[LinkedIn] Authenticated via stored cookies")
                self._authed = True
                return
            except Exception as e:
                print(f"[LinkedIn] Cookie auth failed: {e} — falling back to password login")

        _orig = requests.Session.request
        def _no_verify(self, method, url, **kw):
            kw.setdefault("verify", False)
            return _orig(self, method, url, **kw)
        requests.Session.request = _no_verify
        try:
            self.api = Linkedin(LINKEDIN_EMAIL, LINKEDIN_PASSWORD)
        finally:
            requests.Session.request = _orig
        self.session = self.api.client.session
        self.session.verify = False
        self._authed = True
        print("[LinkedIn] Authenticated via email/password — session pinned for this run")

    # ── Job search ────────────────────────────────────────────

    def _relogin_fresh(self):
        print("[LinkedIn] Auth token expired — refreshing...")
        _orig = requests.Session.request
        def _no_verify(self_inner, method, url, **kw):
            kw.setdefault("verify", False)
            return _orig(self_inner, method, url, **kw)
        requests.Session.request = _no_verify
        try:
            fresh_api = Linkedin(LINKEDIN_EMAIL, LINKEDIN_PASSWORD)
        except Exception as e:
            print(f"[LinkedIn] Token refresh failed: {e}")
            return
        finally:
            requests.Session.request = _orig
        for cookie in fresh_api.client.session.cookies:
            self.session.cookies.set(cookie.name, cookie.value, domain=cookie.domain, path=cookie.path)
        self.api = fresh_api
        print("[LinkedIn] Token refreshed — continuing")

    def _safe_search(self, label: str, **kwargs) -> list[dict]:
        try:
            results = self.api.search_jobs(**kwargs) or []
            return list(results)
        except Exception as e:
            err = str(e)
            if "redirect" in err.lower() or "30 redirect" in err:
                print(f"  [LinkedIn] Auth expired ({label}) — refreshing and retrying...")
                self._relogin_fresh()
                try:
                    results = self.api.search_jobs(**kwargs) or []
                    return list(results)
                except Exception as e2:
                    print(f"  [LinkedIn] Search error ({label}) after re-auth: {e2}")
                    return []
            print(f"  [LinkedIn] Search error ({label}): {e}")
            return []

    _QA_TITLE_WORDS = {"qa", "qe", "quality", "test", "sdet", "automation", "tester", "uat"}

    def _is_qa_title(self, title: str) -> bool:
        t = title.lower()
        return any(w in t for w in self._QA_TITLE_WORDS)

    PAGE_SIZE = 25   # results per API call (LinkedIn max ~25)
    MAX_PAGES = 7    # pages per search → up to 175 results per keyword per location

    def _paginated_search(self, label: str, **base_kwargs) -> list[dict]:
        """Fetch up to MAX_PAGES pages for one keyword+location combo."""
        hits: list[dict] = []
        for page in range(self.MAX_PAGES):
            if page > 0:
                time.sleep(random.uniform(2, 4))
            batch = self._safe_search(
                f"{label}-p{page + 1}",
                limit=self.PAGE_SIZE,
                offset=page * self.PAGE_SIZE,
                **base_kwargs,
            )
            hits.extend(batch)
            if len(batch) < self.PAGE_SIZE:
                break  # LinkedIn returned fewer than a full page — no more results
        return hits

    def search_jobs(self) -> list[dict]:
        seen: dict[str, dict] = {}

        for i, kw in enumerate(JOB_SEARCH_KEYWORDS):
            if i > 0:
                time.sleep(random.uniform(5, 9))

            # ── Texas on-site / hybrid ────────────────────────
            print(f"[LinkedIn] Search: '{kw}' in {PRIMARY_LOCATION}")
            before = len(seen)
            for j in self._paginated_search(
                f"{kw}-{PRIMARY_LOCATION}",
                keywords=kw,
                location_name=PRIMARY_LOCATION,
                listed_at=LISTED_AT_SECONDS,
            ):
                jid = self._job_id(j)
                if jid and self._is_qa_title(self._job_title(j)):
                    seen[jid] = j
            print(f"  → {len(seen) - before} new QA/SDET results (Texas)")

            # ── Remote USA ────────────────────────────────────
            if INCLUDE_REMOTE:
                time.sleep(random.uniform(4, 7))
                print(f"[LinkedIn] Search: '{kw}' Remote (USA only)")
                before = len(seen)
                for j in self._paginated_search(
                    f"{kw}-remote-usa",
                    keywords=kw,
                    location_name="United States",
                    remote=["2"],
                    listed_at=LISTED_AT_SECONDS,
                ):
                    jid = self._job_id(j)
                    if jid and self._is_qa_title(self._job_title(j)):
                        seen[jid] = j
                print(f"  → {len(seen) - before} new Remote USA QA/SDET results")

        all_jobs   = list(seen.values())
        easy_count = sum(1 for j in all_jobs if self._is_easy_apply(j))
        print(f"[LinkedIn] {easy_count} Easy Apply + {len(all_jobs)-easy_count} external ({len(all_jobs)} total)")
        return all_jobs

    @staticmethod
    def _is_easy_apply(job: dict) -> bool:
        return any("ComplexOnsiteApply" in k for k in job.get("applyMethod", {}))

    @staticmethod
    def _job_id(job: dict) -> str:
        return job.get("entityUrn", "").split(":")[-1]

    def _job_title(self, job: dict) -> str:
        return job.get("title", "QA Contract Role")

    _debug_company_logged = False  # print raw keys once to help diagnose

    def _company_name(self, job: dict) -> str:
        try:
            primary = job.get("primaryDescription", {})
            if isinstance(primary, dict) and primary.get("text"):
                return str(primary["text"]).strip()
            subtitle = job.get("subtitle", {})
            if isinstance(subtitle, dict) and subtitle.get("text"):
                return str(subtitle["text"]).strip()
            for field in ("companyName", "company"):
                val = job.get(field)
                if isinstance(val, str) and val.strip():
                    return val.strip()
                if isinstance(val, dict) and val.get("name"):
                    return str(val["name"]).strip()
            co = job.get("companyDetails", {})
            if isinstance(co, dict):
                for v in co.values():
                    if isinstance(v, dict):
                        crr = v.get("companyResolutionResult", {})
                        if isinstance(crr, dict) and crr.get("name"):
                            return str(crr["name"]).strip()
                        if v.get("name"):
                            return str(v["name"]).strip()
        except Exception:
            pass
        # Log raw keys once so we can see what the search result actually contains
        if not self._debug_company_logged:
            self.__class__._debug_company_logged = True
            print(f"  [DEBUG company] keys={list(job.keys())}")
            print(f"  [DEBUG company] primaryDescription={job.get('primaryDescription')}")
            print(f"  [DEBUG company] companyDetails={str(job.get('companyDetails',''))[:200]}")
        return "Unknown"

    def _job_url(self, job_id: str) -> str:
        return f"https://www.linkedin.com/jobs/view/{job_id}/"

    # ── Main run ──────────────────────────────────────────────

    MAX_DETAIL_CALLS = 120  # cap detail lookups to bound runtime

    def run(self):
        self.login()
        jobs = self.search_jobs()

        to_process = [
            j for j in jobs
            if self._job_id(j) and not self.tracker.already_applied(self._job_id(j))
        ]
        print(f"[LinkedIn] {len(to_process)} new jobs to collect")

        collected    = 0
        detail_calls = 0

        for job in to_process:
            job_id    = self._job_id(job)
            title     = self._job_title(job)
            company   = self._company_name(job)
            url       = self._job_url(job_id)
            is_easy   = self._is_easy_apply(job)
            posted_at = str(job.get("listedAt", ""))  # Unix ms timestamp

            # Search result doesn't reliably carry company — fetch detail as fallback
            if company == "Unknown" and detail_calls < self.MAX_DETAIL_CALLS:
                detail = self._get_job_detail(job_id)
                if detail.get("company"):
                    company = detail["company"]
                detail_calls += 1
                time.sleep(random.uniform(0.5, 1.0))

            status = "Collected - Easy Apply Available" if is_easy else "Collected - Manual Apply"
            print(f"  [{'Easy' if is_easy else 'Ext  '}] {title} @ {company}")

            self.tracker.log_application(
                platform="LinkedIn", job_id=job_id, title=title,
                company=company, url=url, status=status, posted_at=posted_at,
            )
            collected += 1
            time.sleep(random.uniform(0.2, 0.5))

        print(f"\n[LinkedIn] Done. Collected: {collected}  Detail lookups: {detail_calls}")
