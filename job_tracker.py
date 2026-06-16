import os
import csv
from datetime import datetime
from pathlib import Path
try:
    from zoneinfo import ZoneInfo
    _US_CENTRAL = ZoneInfo("America/Chicago")
except Exception:
    _US_CENTRAL = None  # fallback: use local time

TRACKER_FILE = "applied_jobs.csv"
RESET_MARKER = "last_reset_date.txt"
FIELDNAMES = ["date", "platform", "job_id", "title", "company", "url", "status", "resume_used"]


def _today_cdt() -> str:
    """Return today's date string in US/Central time (CDT/CST)."""
    if _US_CENTRAL:
        return datetime.now(_US_CENTRAL).strftime("%Y-%m-%d")
    return datetime.now().strftime("%Y-%m-%d")


class JobTracker:
    def __init__(self, filepath=TRACKER_FILE):
        self.filepath = filepath
        self._applied_ids: set[str] = set()
        self._ensure_file()
        self._reset_if_new_day()
        self._load_applied_ids()

    def _ensure_file(self):
        if not os.path.exists(self.filepath):
            with open(self.filepath, "w", newline="", encoding="utf-8") as f:
                csv.DictWriter(f, fieldnames=FIELDNAMES).writeheader()

    def _reset_if_new_day(self):
        """Reset CSV once per US/Central calendar day using a marker file.

        Comparing CSV row timestamps is unreliable because GitHub Actions (UTC)
        and the local Windows machine (CDT) write different timezone offsets.
        The marker file always stores a CDT date so the boundary is consistent.
        """
        today = _today_cdt()
        marker = Path(RESET_MARKER)
        try:
            if marker.exists() and marker.read_text(encoding="utf-8").strip() >= today:
                return  # Already reset today (CDT)
        except Exception:
            pass
        print(f"[Tracker] New CDT day ({today}) — resetting CSV")
        with open(self.filepath, "w", newline="", encoding="utf-8") as f:
            csv.DictWriter(f, fieldnames=FIELDNAMES).writeheader()
        marker.write_text(today, encoding="utf-8")

    def _load_applied_ids(self):
        with open(self.filepath, "r", encoding="utf-8") as f:
            for row in csv.DictReader(f):
                if row.get("job_id"):
                    self._applied_ids.add(row["job_id"])

    def already_applied(self, job_id: str) -> bool:
        return job_id in self._applied_ids

    def log_application(
        self,
        platform: str,
        job_id: str,
        title: str,
        company: str,
        url: str,
        status: str,
        resume_used: str = "",
    ):
        self._applied_ids.add(job_id)
        row = {
            "date": datetime.now().strftime("%Y-%m-%d %H:%M"),
            "platform": platform,
            "job_id": job_id,
            "title": title,
            "company": company,
            "url": url,
            "status": status,
            "resume_used": resume_used,
        }
        with open(self.filepath, "a", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=FIELDNAMES)
            writer.writerow(row)
        print(f"  Logged [{status}]: {title} @ {company}")
