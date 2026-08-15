import os
import re
from dotenv import load_dotenv

load_dotenv()

# ── Platform credentials ──────────────────────────────────────
LINKEDIN_EMAIL = os.getenv("LINKEDIN_EMAIL", "")
LINKEDIN_PASSWORD = os.getenv("LINKEDIN_PASSWORD", "")
DICE_EMAIL = os.getenv("DICE_EMAIL", "")
DICE_PASSWORD = os.getenv("DICE_PASSWORD", "")
ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY", "")

# ── Job search ────────────────────────────────────────────────
_DEFAULT_KEYWORDS = "QA"
_kw_raw = os.getenv("JOB_SEARCH_KEYWORDS", os.getenv("JOB_SEARCH_KEYWORD", _DEFAULT_KEYWORDS))
JOB_SEARCH_KEYWORDS = [k.strip() for k in _kw_raw.split(",") if k.strip()]
JOB_SEARCH_KEYWORD  = JOB_SEARCH_KEYWORDS[0]   # backwards-compat for bots that use single keyword
USING_CUSTOM_KEYWORDS = _kw_raw.strip() != _DEFAULT_KEYWORDS

# Title-relevance filter used by every portal bot to discard obviously
# unrelated results. Defaults to QA/SDET vocabulary; when the user supplies
# their own --technologies / JOB_SEARCH_KEYWORDS, relevance is judged against
# those keywords instead so a search like "Java,Spring Boot" isn't silently
# filtered down to QA-titled jobs only.
_QA_TITLE_WORDS = {"qa", "qe", "quality", "test", "sdet", "automation", "tester", "uat"}
_BOOLEAN_STOPWORDS = {"and", "or", "not"}


def _split_boolean_keyword(raw_keyword: str) -> tuple[set[str], set[str]]:
    """
    Split a keyword string that may contain boolean query syntax
    (AND/OR/NOT, quotes, parentheses) into (include_words, exclude_words) —
    e.g. '(...) AND Java NOT Android NOT iOS' excludes Android/iOS terms
    instead of matching on them, and drops bare operators/punctuation.
    """
    cleaned = re.sub(r'[()"“”]', " ", raw_keyword)
    tokens  = cleaned.split()

    include, exclude = set(), set()
    negate_next = False
    for tok in tokens:
        low = tok.lower()
        if low == "not":
            negate_next = True
            continue
        if low in _BOOLEAN_STOPWORDS:
            continue
        (exclude if negate_next else include).add(low)
        negate_next = False
    return include, exclude


if USING_CUSTOM_KEYWORDS:
    TITLE_FILTER_WORDS: set[str] = set()
    TITLE_EXCLUDE_WORDS: set[str] = set()
    for _kw in JOB_SEARCH_KEYWORDS:
        _inc, _exc = _split_boolean_keyword(_kw)
        TITLE_FILTER_WORDS  |= _inc
        TITLE_EXCLUDE_WORDS |= _exc
else:
    TITLE_FILTER_WORDS  = _QA_TITLE_WORDS
    TITLE_EXCLUDE_WORDS = set()


def title_is_relevant(title: str) -> bool:
    """True if the job title matches the active keyword/QA filter and doesn't hit a NOT term."""
    t = (title or "").lower()
    if any(w in t for w in TITLE_EXCLUDE_WORDS):
        return False
    return any(w in t for w in TITLE_FILTER_WORDS)
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
