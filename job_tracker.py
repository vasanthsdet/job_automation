import csv
from datetime import datetime
from pathlib import Path

TRACKER_FILE = "applied_jobs.csv"
FIELDNAMES = ["posted_at", "date", "platform", "job_id", "title", "company", "url", "status", "resume_used"]


class JobTracker:
    def __init__(self, filepath=TRACKER_FILE, append=False):
        self.filepath = filepath
        self._applied_ids: set[str] = set()
        if append and Path(filepath).exists():
            # Load existing IDs so we don't re-log jobs from the cloud collect step
            self._load_applied_ids()
        else:
            with open(self.filepath, "w", newline="", encoding="utf-8") as f:
                csv.DictWriter(f, fieldnames=FIELDNAMES).writeheader()

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
        posted_at: str = "",
    ):
        self._applied_ids.add(job_id)
        row = {
            "posted_at": posted_at,
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
