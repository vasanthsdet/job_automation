"""
LinkedIn Easy Apply via Playwright headless browser.

Does a fresh headless login every run to get valid session cookies.
Called only for jobs flagged as Easy Apply by the HTTP search.
"""

import json
import time
from pathlib import Path

from playwright.sync_api import sync_playwright, TimeoutError as PWTimeout

from config import (
    LINKEDIN_EMAIL, LINKEDIN_PASSWORD,
    YEARS_OF_EXPERIENCE, WORK_AUTHORIZATION,
    EXPECTED_HOURLY_RATE, WILLING_TO_RELOCATE,
)

COOKIES_FILE = "linkedin_cookies.json"
_LINKEDIN    = "https://www.linkedin.com"

_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/125.0.0.0 Safari/537.36"
)

# Cached cookies for the current process (login once per run)
_session_cookies: list[dict] = []


def get_fresh_cookies() -> list[dict]:
    """
    Login to LinkedIn via headless Chromium and return fresh session cookies.
    Caches result for the duration of the process so we only log in once per run.
    """
    global _session_cookies
    if _session_cookies:
        return _session_cookies

    print("  [playwright] Logging in to LinkedIn for fresh session cookies...")
    with sync_playwright() as pw:
        browser = pw.chromium.launch(
            headless=True,
            args=[
                "--disable-blink-features=AutomationControlled",
                "--no-sandbox",
                "--disable-setuid-sandbox",
                "--disable-dev-shm-usage",
            ],
        )
        ctx = browser.new_context(
            viewport={"width": 1280, "height": 800},
            user_agent=_USER_AGENT,
            extra_http_headers={"Accept-Language": "en-US,en;q=0.9"},
        )
        # Hide headless fingerprint
        ctx.add_init_script(
            "Object.defineProperty(navigator, 'webdriver', {get: () => undefined})"
        )
        page = ctx.new_page()

        try:
            page.goto(f"{_LINKEDIN}/login", wait_until="domcontentloaded", timeout=45000)
            time.sleep(3)
            print(f"  [playwright] Login page URL: {page.url}")

            # Wait for the visible email input to appear
            page.wait_for_selector("input[type='email']:visible", timeout=20000)

            # Use :visible to target only the on-screen fields (LinkedIn has hidden decoy inputs)
            email_input = page.locator("input[type='email']:visible").first
            email_input.click()
            time.sleep(0.3)
            email_input.fill(LINKEDIN_EMAIL)
            time.sleep(0.5)

            pwd_input = page.locator("input[type='password']:visible").first
            pwd_input.click()
            time.sleep(0.3)
            pwd_input.fill(LINKEDIN_PASSWORD)
            time.sleep(0.5)

            # Press Enter to submit the email/password form
            # (avoids accidentally clicking "Sign in with Google/Microsoft" buttons)
            pwd_input.press("Enter")
            print("  [playwright] Submitted login form")
            # Wait for post-login navigation to settle
            try:
                page.wait_for_load_state("domcontentloaded", timeout=30000)
            except Exception:
                pass
            time.sleep(5)
            print(f"  [playwright] Post-login URL: {page.url}")

            if "checkpoint" in page.url or "challenge" in page.url:
                print("  [playwright] LinkedIn requires verification — skipping cookie login")
                return []

            # Check for li_at cookie — presence means login succeeded regardless of URL
            cookies = ctx.cookies()
            li_at = next((c["value"] for c in cookies if c["name"] == "li_at"), "")
            if not li_at:
                # Show error from page if any
                try:
                    errors = page.locator("[role='alert'], .form__error, [data-error]").all()
                    for el in errors[:2]:
                        try:
                            msg = el.inner_text().strip()
                            if msg:
                                print(f"  [playwright] Page error: {msg[:200]}")
                        except Exception:
                            pass
                except Exception:
                    pass
                print(f"  [playwright] No li_at in cookies — login failed (URL: {page.url})")
                return []

            # Save as flat dict for fallback
            cookie_dict = {c["name"]: c["value"] for c in cookies}
            Path(COOKIES_FILE).write_text(json.dumps(cookie_dict, indent=2), encoding="utf-8")
            print(f"  [playwright] Fresh login OK — {len(cookies)} cookies saved (li_at SET)")
            _session_cookies = cookies
            return _session_cookies

        except Exception as e:
            print(f"  [playwright] Login error: {e}")
            return []
        finally:
            try:
                browser.close()
            except Exception:
                pass


def _load_stored_cookies() -> list[dict]:
    """Load previously saved cookies from file (only if they contain li_at)."""
    p = Path(COOKIES_FILE)
    if not p.exists():
        return []
    try:
        content = p.read_text(encoding="utf-8").strip().lstrip("﻿")
        raw = json.loads(content) if content else {}
        if not raw.get("li_at"):
            print("  [playwright] Stored cookies have no li_at — skipping fallback")
            return []
        print(f"  [playwright] Using stored cookies ({len(raw)} keys)")
        return [
            {"name": k, "value": str(v), "domain": ".linkedin.com", "path": "/"}
            for k, v in raw.items()
        ]
    except Exception:
        return []


def _load_cookies() -> list[dict]:
    """Used by submit_easy_apply — gets fresh cookies (login if needed)."""
    return get_fresh_cookies() or _load_stored_cookies()


def _fill_field(page, label_keywords: list[str], value: str):
    """Try to fill a visible input/textarea that matches any of the label keywords."""
    for kw in label_keywords:
        try:
            # Find label containing keyword, then fill its associated input
            locator = page.locator(
                f"input[aria-label*='{kw}' i], textarea[aria-label*='{kw}' i], "
                f"input[id*='{kw}' i], textarea[id*='{kw}' i]"
            ).first
            if locator.is_visible(timeout=1000):
                locator.fill(str(value))
                return True
        except Exception:
            pass
    return False


def _handle_form_page(page) -> bool:
    """Fill current Easy Apply form page. Returns True if we should continue clicking Next."""
    # Phone / mobile
    _fill_field(page, ["phone", "mobile", "telephone"], "")

    # Years of experience
    _fill_field(page, ["year", "experience", "years of"], YEARS_OF_EXPERIENCE)

    # Hourly rate / salary
    _fill_field(page, ["hourly", "rate", "salary", "compensation", "pay"], EXPECTED_HOURLY_RATE)

    # Work authorization
    try:
        auth_locator = page.locator(
            f"select[aria-label*='authorized' i], select[aria-label*='eligible' i], "
            f"select[aria-label*='citizen' i], select[aria-label*='visa' i]"
        ).first
        if auth_locator.is_visible(timeout=1000):
            auth_locator.select_option(label=WORK_AUTHORIZATION)
    except Exception:
        pass

    # Relocation
    try:
        reloc = page.locator("select[aria-label*='relocat' i]").first
        if reloc.is_visible(timeout=1000):
            reloc.select_option(label=WILLING_TO_RELOCATE)
    except Exception:
        pass

    # Radio buttons — pick first visible option for yes/no questions
    try:
        radios = page.locator("fieldset input[type='radio']")
        for i in range(min(radios.count(), 5)):
            radio = radios.nth(i)
            if radio.is_visible(timeout=500) and not radio.is_checked():
                radio.check()
                break
    except Exception:
        pass

    return True


def submit_easy_apply(job_url: str, resume_path: str) -> bool:
    """
    Opens the job URL in a headless browser, clicks Easy Apply,
    fills the form, uploads resume, and submits.
    Returns True on success.
    """
    cookies = _load_cookies()
    if not cookies:
        print("  [playwright] No cookies file — cannot submit Easy Apply")
        return False

    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=True)
        ctx     = browser.new_context(
            viewport={"width": 1280, "height": 800},
            user_agent=(
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/125.0.0.0 Safari/537.36"
            ),
        )
        ctx.add_cookies(cookies)
        page = ctx.new_page()

        try:
            # Navigate to job page
            print(f"  [playwright] Opening job page...")
            page.goto(job_url, wait_until="domcontentloaded", timeout=45000)
            time.sleep(3)

            # Check if we're still logged in
            if "authwall" in page.url or "login" in page.url:
                print("  [playwright] Session expired — need fresh cookies")
                return False

            print(f"  [playwright] Page loaded: {page.title()[:80]}")

            # Click Easy Apply button — LinkedIn uses several different selectors
            EASY_APPLY_SELECTORS = [
                "button.jobs-apply-button",
                "button[data-job-id]",
                "button:has-text('Easy Apply')",
                "button[aria-label*='Easy Apply' i]",
                "button[aria-label*='easy apply' i]",
                # Broader fallback — any top-card apply button
                ".jobs-unified-top-card__content--two-pane button",
                ".jobs-apply-button--top-card",
            ]

            clicked = False
            for sel in EASY_APPLY_SELECTORS:
                try:
                    btn = page.locator(sel).first
                    btn.wait_for(state="visible", timeout=3000)
                    btn_text = btn.inner_text().strip().lower()
                    print(f"  [playwright] Found button: '{btn_text[:40]}' via {sel}")
                    if "easy apply" in btn_text or "apply" in btn_text:
                        btn.click()
                        time.sleep(1.5)
                        clicked = True
                        break
                except Exception:
                    pass

            if not clicked:
                # Last resort: dump all visible button texts for debugging
                try:
                    buttons = page.locator("button").all()
                    visible_btns = [b.inner_text().strip() for b in buttons if b.is_visible()]
                    print(f"  [playwright] Visible buttons: {visible_btns[:10]}")
                except Exception:
                    pass
                print("  [playwright] Easy Apply button not found on page")
                return False

            # Handle multi-step form (up to 10 pages)
            for step in range(10):
                time.sleep(1)

                # Upload resume if file input visible
                try:
                    file_input = page.locator("input[type='file']").first
                    if file_input.is_visible(timeout=1000):
                        file_input.set_input_files(str(resume_path))
                        time.sleep(1)
                except Exception:
                    pass

                # Fill form fields
                _handle_form_page(page)

                # Check for Submit button
                submit_btn = page.locator(
                    "button:has-text('Submit application'), "
                    "button[aria-label*='Submit application' i]"
                ).first
                try:
                    if submit_btn.is_visible(timeout=1000):
                        submit_btn.click()
                        time.sleep(2)
                        print(f"  [playwright] Application submitted!")
                        return True
                except Exception:
                    pass

                # Check for Next / Review button
                next_btn = page.locator(
                    "button:has-text('Next'), "
                    "button:has-text('Review'), "
                    "button[aria-label*='Continue' i]"
                ).first
                try:
                    if next_btn.is_visible(timeout=2000):
                        next_btn.click()
                        continue
                except Exception:
                    pass

                # Check for confirmation modal (already applied / success)
                try:
                    if page.locator("div:has-text('application was sent')").is_visible(timeout=1000):
                        print(f"  [playwright] Application confirmed!")
                        return True
                except Exception:
                    pass

                # No next/submit found — exit loop
                break

            print("  [playwright] Could not complete form — flagged for manual apply")
            return False

        except Exception as e:
            print(f"  [playwright] Error: {e}")
            return False
        finally:
            browser.close()
