import os
from dotenv import load_dotenv

load_dotenv()

# ── Platform credentials ──────────────────────────────────────
LINKEDIN_EMAIL = os.getenv("LINKEDIN_EMAIL", "")
LINKEDIN_PASSWORD = os.getenv("LINKEDIN_PASSWORD", "")
DICE_EMAIL = os.getenv("DICE_EMAIL", "")
DICE_PASSWORD = os.getenv("DICE_PASSWORD", "")
ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY", "")

# ── Job search ────────────────────────────────────────────────
_kw_raw = os.getenv("JOB_SEARCH_KEYWORDS", os.getenv("JOB_SEARCH_KEYWORD", "QA"))
JOB_SEARCH_KEYWORDS = [k.strip() for k in _kw_raw.split(",") if k.strip()]
JOB_SEARCH_KEYWORD  = JOB_SEARCH_KEYWORDS[0]   # backwards-compat for bots that use single keyword
PRIMARY_LOCATION    = os.getenv("PRIMARY_LOCATION", "Texas, United States")
INCLUDE_REMOTE     = os.getenv("INCLUDE_REMOTE", "true").lower() == "true"
JOB_TYPE           = os.getenv("JOB_TYPE", "C")           # C=Contract, F=Full-time, P=Part-time
MIN_HOURLY_RATE    = float(os.getenv("MIN_HOURLY_RATE", "60"))
MAX_JOBS_TO_APPLY  = int(os.getenv("MAX_JOBS_TO_APPLY", "10"))
LISTED_AT_SECONDS  = int(os.getenv("LISTED_AT_DAYS", "3")) * 24 * 60 * 60

# ── Resume ────────────────────────────────────────────────────
BASE_RESUME_PATH = os.getenv("BASE_RESUME_PATH", "resume/base_resume.docx")
TRACKER_FILE     = os.getenv("TRACKER_FILE", "applied_jobs.csv")

# ── Application form defaults ─────────────────────────────────
YEARS_OF_EXPERIENCE = os.getenv("YEARS_OF_EXPERIENCE", "5")
WORK_AUTHORIZATION  = os.getenv("WORK_AUTHORIZATION", "Yes")
WILLING_TO_RELOCATE = os.getenv("WILLING_TO_RELOCATE", "No")
EXPECTED_HOURLY_RATE = os.getenv("EXPECTED_HOURLY_RATE", str(int(MIN_HOURLY_RATE)))

# ── Additional portal API keys (optional) ────────────────────
ZIPRECRUITER_API_KEY = os.getenv("ZIPRECRUITER_API_KEY", "")
ADZUNA_APP_ID        = os.getenv("ADZUNA_APP_ID", "")
ADZUNA_APP_KEY       = os.getenv("ADZUNA_APP_KEY", "")

# ── Email report ──────────────────────────────────────────────
EMAIL_SENDER      = os.getenv("EMAIL_SENDER", "")
EMAIL_APP_PASSWORD = os.getenv("EMAIL_APP_PASSWORD", "")
EMAIL_RECIPIENTS  = os.getenv(
    "EMAIL_RECIPIENTS",
    "revathibathina11@gmail.com,dama.vasanth@gmail.com",
)
