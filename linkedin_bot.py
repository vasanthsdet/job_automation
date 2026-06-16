"""
LinkedIn job search and Easy Apply — pure HTTP, no browser.

Search strategy:
  - Run TWO searches per cycle: Dallas (on-site/hybrid) + Remote
  - Filter: Contract jobs only (JOB_TYPE=C)
  - Filter: Last 3 days (LISTED_AT_DAYS)
  - Filter: Hourly rate >= MIN_HOURLY_RATE ($60) parsed from job description
  - Apply via LinkedIn's Voyager REST API with AI-tailored resume
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
    JOB_SEARCH_KEYWORDS, JOB_SEARCH_KEYWORD, PRIMARY_LOCATION, INCLUDE_REMOTE,
    JOB_TYPE, MIN_HOURLY_RATE, MAX_JOBS_TO_APPLY,
    BASE_RESUME_PATH, YEARS_OF_EXPERIENCE, WORK_AUTHORIZATION, EXPECTED_HOURLY_RATE,
    LISTED_AT_SECONDS,
)
from job_tracker import JobTracker
from resume_updater import create_tailored_resume
from easy_apply_playwright import submit_easy_apply, get_fresh_cookies
from utils import meets_rate

VOYAGER = "https://www.linkedin.com/voyager/api"


class LinkedInBot:
    def __init__(self, tracker: JobTracker, skip_tailor: bool = False):
        self.tracker = tracker
        self.skip_tailor = skip_tailor
        self.api: Linkedin | None = None
        self.session = None
        self.applied = 0

    # ── Auth ──────────────────────────────────────────────────

    COOKIES_FILE = "linkedin_cookies.json"

    def _load_browser_cookies(self) -> dict:
        """Load real browser cookies from file (bypasses JS token requirement)."""
        p = Path(self.COOKIES_FILE)
        if not p.exists():
            return {}
        try:
            content = p.read_text(encoding="utf-8").strip().lstrip("﻿")  # strip BOM
            return json.loads(content) if content else {}
        except Exception:
            return {}

    def login(self):
        print("[LinkedIn] Authenticating via Voyager API...")
        ssl._create_default_https_context = ssl._create_unverified_context

        # Get fresh cookies via Playwright headless login (once per run)
        pw_cookies = get_fresh_cookies()
        browser_cookies = {c["name"]: c["value"] for c in pw_cookies} if pw_cookies else {}
        li_at     = browser_cookies.get("li_at", "")
        jsessionid = browser_cookies.get("JSESSIONID", "")
        print(f"[LinkedIn] Cookies: {len(browser_cookies)} keys, li_at={'SET' if li_at else 'MISSING'}")

        if li_at:
            try:
                self.api = Linkedin(
                    "", "",
                    authenticate=True,
                    cookies={"li_at": li_at, "JSESSIONID": jsessionid},
                )
                self.session = self.api.client.session
                self.session.verify = False

                # linkedin-api sets session.cookies as plain dict — rebuild as proper jar
                if isinstance(self.session.cookies, dict):
                    jar = RequestsCookieJar()
                    for k, v in self.session.cookies.items():
                        jar.set(k, v, domain=".linkedin.com", path="/")
                    self.session.cookies = jar
                elif not hasattr(self.session.cookies, "set"):
                    jar = RequestsCookieJar()
                    self.session.cookies = jar

                # Inject remaining cookies (bcookie, bscookie, etc.)
                for k, v in browser_cookies.items():
                    if k not in ("li_at", "JSESSIONID"):
                        self.session.cookies.set(k, v, domain=".linkedin.com", path="/")

                print("[LinkedIn] Authenticated via fresh cookies")
                return
            except Exception as e:
                print(f"[LinkedIn] Cookie auth failed: {e} — falling back to password login")
        else:
            print("[LinkedIn] No fresh li_at — using email/password login")

        # Fallback: email/password login
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
        print("[LinkedIn] Authenticated via email/password")

    def _headers(self) -> dict:
        csrf = self.session.cookies.get("JSESSIONID", "").replace('"', "")
        return {
            "csrf-token": csrf,
            "x-restli-protocol-version": "2.0.0",
            "accept": "application/vnd.linkedin.normalized+json+2.1",
            "content-type": "application/json",
        }

    # ── Job search ────────────────────────────────────────────

    def _relogin_fresh(self):
        """Force fresh Playwright login and re-authenticate (called on redirect errors)."""
        import easy_apply_playwright as _ea
        _ea._session_cookies = []  # clear in-process cache
        print("[LinkedIn] Re-authenticating with fresh cookies...")
        pw_cookies = get_fresh_cookies(force_login=True)
        if not pw_cookies:
            print("[LinkedIn] Fresh login failed — search will continue to fail")
            return
        browser_cookies = {c["name"]: c["value"] for c in pw_cookies}
        li_at     = browser_cookies.get("li_at", "")
        jsessionid = browser_cookies.get("JSESSIONID", "")
        if not li_at:
            return
        try:
            self.api = Linkedin("", "", authenticate=True,
                                cookies={"li_at": li_at, "JSESSIONID": jsessionid})
            self.session = self.api.client.session
            self.session.verify = False
            if isinstance(self.session.cookies, dict):
                jar = RequestsCookieJar()
                for k, v in self.session.cookies.items():
                    jar.set(k, v, domain=".linkedin.com", path="/")
                self.session.cookies = jar
            for k, v in browser_cookies.items():
                if k not in ("li_at", "JSESSIONID"):
                    self.session.cookies.set(k, v, domain=".linkedin.com", path="/")
            print("[LinkedIn] Re-authenticated successfully")
        except Exception as e:
            print(f"[LinkedIn] Re-auth failed: {e}")

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

    # TX city names LinkedIn recognises
    _TX_CITIES = [
        "Dallas-Fort Worth Metroplex",
        "Houston, Texas, United States",
        "Austin, Texas, United States",
        "San Antonio, Texas, United States",
    ]

    # Title must contain at least one of these (case-insensitive) to be kept
    _QA_TITLE_WORDS = {"qa", "qe", "quality", "test", "sdet", "automation", "tester", "uat"}

    def _is_qa_title(self, title: str) -> bool:
        t = title.lower()
        return any(w in t for w in self._QA_TITLE_WORDS)

    def search_jobs(self) -> list[dict]:
        seen: dict[str, dict] = {}
        search_count = 0

        for kw in JOB_SEARCH_KEYWORDS:
            # TX — search each major city
            for city in self._TX_CITIES:
                print(f"[LinkedIn] Search: '{kw}' in {city}")
                if search_count > 0:
                    time.sleep(random.uniform(4, 8))  # avoid rate limiting
                results = self._safe_search(
                    f"{kw}-{city}",
                    keywords=kw,
                    location_name=city,
                    listed_at=LISTED_AT_SECONDS,
                    limit=25,
                )
                search_count += 1
                before = len(seen)
                for j in results:
                    jid = self._job_id(j)
                    if jid and self._is_qa_title(self._job_title(j)):
                        seen[jid] = j
                print(f"  → {len(seen) - before} new QA/SDET results")

            # Remote jobs
            if INCLUDE_REMOTE:
                print(f"[LinkedIn] Search: '{kw}' Remote")
                if search_count > 0:
                    time.sleep(random.uniform(4, 8))
                remote = self._safe_search(
                    f"{kw}-remote",
                    keywords=kw,
                    location_name="United States",
                    remote=["2"],
                    listed_at=LISTED_AT_SECONDS,
                    limit=30,
                )
                search_count += 1
                before = len(seen)
                for j in remote:
                    jid = self._job_id(j)
                    if jid and self._is_qa_title(self._job_title(j)):
                        seen[jid] = j
                print(f"  → {len(seen) - before} new Remote QA/SDET results")

        all_jobs = list(seen.values())
        easy_apply = [j for j in all_jobs if self._is_easy_apply(j)]
        print(f"[LinkedIn] {len(easy_apply)} Easy Apply + {len(all_jobs)-len(easy_apply)} manual jobs ({len(all_jobs)} total)")
        return all_jobs

    @staticmethod
    def _is_easy_apply(job: dict) -> bool:
        return any("ComplexOnsiteApply" in k for k in job.get("applyMethod", {}))

    @staticmethod
    def _job_id(job: dict) -> str:
        return job.get("entityUrn", "").split(":")[-1]

    def _get_job_detail(self, job_id: str) -> dict:
        """Fetch full job detail — description, applicant count, Easy Apply flag."""
        try:
            detail = self.api.get_job(job_id)
            desc = detail.get("description", {}).get("text", "")

            # Applicant count
            count = detail.get("applies") or detail.get("numApplicants") or 0
            try:
                count = int(str(count).replace("+", "").replace(",", "").strip())
            except (ValueError, TypeError):
                count = 0

            # Easy Apply — checked from full detail (not search result which omits it)
            apply_method = detail.get("applyMethod", {})
            if isinstance(apply_method, dict):
                is_easy = any("ComplexOnsiteApply" in k for k in apply_method)
            else:
                is_easy = False

            # Company name from full detail (more reliable than search result)
            company = ""
            try:
                co_details = detail.get("companyDetails", {})
                if isinstance(co_details, dict):
                    for v in co_details.values():
                        if isinstance(v, dict):
                            crr = v.get("companyResolutionResult", {})
                            if isinstance(crr, dict) and crr.get("name"):
                                company = crr["name"]
                                break
                            if v.get("name"):
                                company = str(v["name"])
                                break
                if not company and detail.get("companyName"):
                    company = str(detail["companyName"])
            except Exception:
                pass

            return {"description": desc, "applicants": count, "is_easy": is_easy, "company": company}
        except Exception:
            return {"description": "", "applicants": 0, "is_easy": False, "company": ""}

    def _job_title(self, job: dict) -> str:
        return job.get("title", "QA Contract Role")

    def _company_name(self, job: dict) -> str:
        try:
            # Most reliable in search results: primaryDescription.text
            primary = job.get("primaryDescription", {})
            if isinstance(primary, dict) and primary.get("text"):
                return primary["text"]
            # Nested companyDetails (search result variant)
            co = job.get("companyDetails", {})
            if isinstance(co, dict):
                for v in co.values():
                    if isinstance(v, dict):
                        crr = v.get("companyResolutionResult", {})
                        if isinstance(crr, dict) and crr.get("name"):
                            return crr["name"]
                        if v.get("name"):
                            return str(v["name"])
            # Some API responses put it at top level
            if job.get("companyName"):
                return str(job["companyName"])
        except Exception:
            pass
        return "Unknown"

    def _job_url(self, job_id: str) -> str:
        return f"https://www.linkedin.com/jobs/view/{job_id}/"

    # ── Easy Apply via Voyager REST API ───────────────────────

    def _upload_resume(self, resume_path: str) -> str | None:
        try:
            reg = self.session.post(
                f"{VOYAGER}/jobs/applyWithEasyApply/resumeUpload",
                headers=self._headers(),
                json={
                    "filename": Path(resume_path).name,
                    "mediaType": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                },
            )
            if reg.status_code not in (200, 201):
                return None
            data = reg.json()
            upload_url = data.get("value", {}).get("uploadUrl") or data.get("uploadUrl")
            media_urn  = data.get("value", {}).get("urn")     or data.get("urn")
            if not upload_url:
                return None
            with open(resume_path, "rb") as f:
                self.session.put(
                    upload_url,
                    data=f.read(),
                    headers={"Content-Type": "application/vnd.openxmlformats-officedocument.wordprocessingml.document"},
                )
            return media_urn
        except Exception as e:
            print(f"  [upload] Failed: {e}")
            return None

    def _submit_easy_apply(self, job_id: str, resume_path: str) -> bool:
        job_urn = f"urn:li:fs_jobPosting:{job_id}"

        form_resp = self.session.get(
            f"{VOYAGER}/jobs/applyWithEasyApply",
            params={"jobPostingUrn": job_urn},
            headers=self._headers(),
        )
        if form_resp.status_code != 200:
            print(f"  [apply] Form fetch failed (HTTP {form_resp.status_code})")
            return False

        media_urn = self._upload_resume(resume_path)

        payload: dict = {
            "jobPostingUrn": job_urn,
            "questionsAndAnswers": [],
            "contactInfo": {"emailAddress": LINKEDIN_EMAIL},
        }
        if media_urn:
            payload["resumeUploadUrn"] = media_urn

        # Auto-answer common contract screening questions
        try:
            for q in form_resp.json().get("value", {}).get("questionFields", []):
                qid   = q.get("fieldId", "").lower()
                qtype = q.get("fieldType", "")
                answer: str | int | float | bool = ""

                if any(k in qid for k in ("year", "experience")):
                    answer = int(YEARS_OF_EXPERIENCE)
                elif any(k in qid for k in ("hourly", "rate", "pay")):
                    answer = float(EXPECTED_HOURLY_RATE)
                elif any(k in qid for k in ("authorized", "eligible", "citizen", "visa")):
                    answer = WORK_AUTHORIZATION
                elif any(k in qid for k in ("salary", "compensation")):
                    answer = float(EXPECTED_HOURLY_RATE)
                elif any(k in qid for k in ("relocat",)):
                    answer = "No"
                elif qtype == "BOOLEAN":
                    answer = True

                if answer != "":
                    payload["questionsAndAnswers"].append(
                        {"questionFieldId": q.get("fieldId", ""), "answer": answer}
                    )
        except Exception:
            pass

        submit_resp = self.session.post(
            f"{VOYAGER}/jobs/applyWithEasyApply",
            json=payload,
            headers=self._headers(),
        )
        ok = submit_resp.status_code in (200, 201)
        if not ok:
            print(f"  [apply] Submit HTTP {submit_resp.status_code}")
        return ok

    # ── Main run ──────────────────────────────────────────────

    def run(self):
        self.login()
        jobs = self.search_jobs()

        to_process = [
            j for j in jobs
            if self._job_id(j) and not self.tracker.already_applied(self._job_id(j))
        ]
        print(f"[LinkedIn] {len(to_process)} new jobs to evaluate")

        for job in to_process:
            if self.applied >= MAX_JOBS_TO_APPLY:
                print(f"[LinkedIn] Limit of {MAX_JOBS_TO_APPLY} reached")
                break

            job_id  = self._job_id(job)
            title   = self._job_title(job)
            company = self._company_name(job)
            url     = self._job_url(job_id)

            print(f"\n[LinkedIn] → {title} @ {company}")

            # Fetch description + applicant count + better company name in one call
            detail      = self._get_job_detail(job_id)
            description = detail["description"]
            applicants  = detail["applicants"]
            # Use detail company name if search result had "Unknown"
            if company == "Unknown" and detail.get("company"):
                company = detail["company"]
                print(f"  [company] Resolved: {company}")

            # ── 100+ applicants gate ──────────────────────────
            if applicants >= 100:
                print(f"  [skip] {applicants}+ applicants already")
                self.tracker.log_application(
                    platform="LinkedIn", job_id=job_id, title=title,
                    company=company, url=url,
                    status=f"Skipped - {applicants}+ Applicants",
                )
                continue

            # ── Hourly rate gate ──────────────────────────────
            if not meets_rate(description, MIN_HOURLY_RATE):
                print(f"  [skip] Rate below ${MIN_HOURLY_RATE}/hr")
                self.tracker.log_application(
                    platform="LinkedIn", job_id=job_id, title=title,
                    company=company, url=url,
                    status=f"Skipped - Rate Below ${MIN_HOURLY_RATE}/hr",
                )
                continue

            is_easy = detail["is_easy"]
            if is_easy:
                # Easy Apply disabled — log for manual apply via the link in the email
                print(f"  [Easy Apply] Logged for manual apply (auto-submit disabled)")
                self.tracker.log_application(
                    platform="LinkedIn", job_id=job_id, title=title,
                    company=company, url=url, status="Easy Apply - Click to Apply",
                )
            else:
                print(f"  [External Apply] Link in email")
                self.tracker.log_application(
                    platform="LinkedIn", job_id=job_id, title=title,
                    company=company, url=url, status="Collected - External Apply",
                )

            time.sleep(random.uniform(3, 6))

        print(f"\n[LinkedIn] Done. Applied: {self.applied}")
