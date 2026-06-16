import os
import csv
from datetime import datetime

TRACKER_FILE = "applied_jobs.csv"
FIELDNAMES = ["date", "platform", "job_id", "title", "company", "url", "status", "resume_used"]


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
                writer = csv.DictWriter(f, fieldnames=FIELDNAMES)
                writer.writeheader()

    def _reset_if_new_day(self):
        """Clear the CSV if all entries are from a previous calendar day."""
        today = datetime.now().date()
        try:
            with open(self.filepath, "r", encoding="utf-8") as f:
                rows = list(csv.DictReader(f))
            if not rows:
                return
            last_date = datetime.strptime(rows[-1]["date"], "%Y-%m-%d %H:%M").date()
            if last_date < today:
                print(f"[Tracker] New day ({today}) — resetting CSV (last entry was {last_date})")
                with open(self.filepath, "w", newline="", encoding="utf-8") as f:
                    csv.DictWriter(f, fieldnames=FIELDNAMES).writeheader()
        except Exception:
            pass

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
