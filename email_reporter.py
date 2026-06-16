"""
Reads applied_jobs.csv, builds an HTML report, and emails it to all recipients.
"""

import csv
import smtplib
import os
from collections import Counter
from datetime import datetime
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.mime.base import MIMEBase
from email import encoders
from pathlib import Path

from config import (
    EMAIL_SENDER, EMAIL_APP_PASSWORD,
    EMAIL_RECIPIENTS, TRACKER_FILE, MIN_HOURLY_RATE,
)

# ── Status badge colors ───────────────────────────────────────
STATUS_COLORS = {
    "Easy Apply - Applied":       "#22863a",  # green
    "Applied":                    "#22863a",  # green
    "Collected - Manual Apply":   "#0077b5",  # blue
    "Collected - External Apply": "#0077b5",  # blue
    "Easy Apply - Click to Apply": "#22863a",  # green — ready to apply in 1 click
    "Easy Apply - Failed":        "#e36209",  # orange
    "Easy Apply - Error":         "#cb2431",  # red
    "Failed - Manual Apply":      "#e36209",  # orange
    "Error":                      "#cb2431",  # red
    "Skipped - 100+ Applicants":  "#6f42c1",  # purple
    "Skipped - Rate Below":       "#586069",  # grey
}


def _badge(status: str) -> str:
    color = "#586069"
    for key, col in STATUS_COLORS.items():
        if status.startswith(key) or status == key:
            color = col
            break
    return (
        f'<span style="background:{color};color:#fff;padding:2px 8px;'
        f'border-radius:10px;font-size:12px;white-space:nowrap">{status}</span>'
    )


def _read_jobs(run_start: datetime | None = None) -> list[dict]:
    if not Path(TRACKER_FILE).exists():
        return []
    with open(TRACKER_FILE, newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def _build_html(jobs: list[dict], run_start: datetime) -> str:
    counts = Counter(j["status"] for j in jobs)
    applied_count   = sum(v for k, v in counts.items() if "applied" in k.lower() and "fail" not in k.lower() and "error" not in k.lower())
    collected_count = sum(v for k, v in counts.items() if "collected" in k.lower())
    skipped_100     = sum(v for k, v in counts.items() if "100+" in k or "applicants" in k.lower())
    skipped_rate    = sum(v for k, v in counts.items() if "rate below" in k.lower())
    failed_count    = sum(v for k, v in counts.items() if "fail" in k.lower() or k.lower() == "error" or "error" in k.lower())
    total = len(jobs)

    # ── Summary cards ─────────────────────────────────────────
    def card(label, value, color):
        return (
            f'<div style="display:inline-block;background:{color};color:#fff;'
            f'border-radius:8px;padding:14px 22px;margin:6px;text-align:center;min-width:110px">'
            f'<div style="font-size:28px;font-weight:bold">{value}</div>'
            f'<div style="font-size:12px;margin-top:4px">{label}</div></div>'
        )

    summary_html = (
        card("Total Found", total, "#444")
        + card("Applied", applied_count, "#22863a")
        + card("Collected", collected_count, "#0077b5")
        + card("Skipped 100+", skipped_100, "#6f42c1")
        + card(f"Rate < ${int(MIN_HOURLY_RATE)}/hr", skipped_rate, "#586069")
        + card("Failed / Error", failed_count, "#cb2431")
    )

    # ── Jobs table ────────────────────────────────────────────
    rows = ""
    for i, j in enumerate(jobs):
        bg = "#f6f8fa" if i % 2 == 0 else "#ffffff"
        url = j.get("url", "")
        link = f'<a href="{url}" style="color:#0077b5">View</a>' if url else "—"
        status = j.get("status", "")
        # Easy Apply jobs get a prominent Apply Now button
        if status == "Easy Apply - Click to Apply" and url:
            apply_btn = (
                f'<a href="{url}" style="background:#0077b5;color:#fff;padding:4px 12px;'
                f'border-radius:4px;text-decoration:none;font-size:12px;font-weight:bold">'
                f'Apply Now</a>'
            )
        else:
            apply_btn = link

        rows += (
            f'<tr style="background:{bg}">'
            f'<td style="{_td}">{j.get("date","")}</td>'
            f'<td style="{_td}">{j.get("platform","")}</td>'
            f'<td style="{_td};font-weight:500">{j.get("title","")}</td>'
            f'<td style="{_td}">{j.get("company","")}</td>'
            f'<td style="{_td}">{_badge(status)}</td>'
            f'<td style="{_td}">{apply_btn}</td>'
            f'</tr>'
        )

    table_html = f"""
    <table style="width:100%;border-collapse:collapse;font-size:13px;margin-top:10px">
      <thead>
        <tr style="background:#0077b5;color:#fff">
          <th style="{_th}">Date</th>
          <th style="{_th}">Platform</th>
          <th style="{_th}">Job Title</th>
          <th style="{_th}">Company</th>
          <th style="{_th}">Status</th>
          <th style="{_th}">Link</th>
        </tr>
      </thead>
      <tbody>{rows}</tbody>
    </table>"""

    platform_breakdown = ""
    for platform in ("LinkedIn", "Dice"):
        p_jobs = [j for j in jobs if j.get("platform") == platform]
        if p_jobs:
            p_applied = sum(1 for j in p_jobs if j["status"] == "Applied")
            platform_breakdown += (
                f'<li><strong>{platform}</strong>: {len(p_jobs)} found, '
                f'{p_applied} applied</li>'
            )

    return f"""
    <!DOCTYPE html>
    <html>
    <head><meta charset="UTF-8"></head>
    <body style="font-family:Arial,sans-serif;color:#24292e;max-width:960px;margin:0 auto;padding:20px">

      <div style="background:#0077b5;color:#fff;padding:20px 24px;border-radius:8px 8px 0 0">
        <h2 style="margin:0">QA Job Application Report</h2>
        <p style="margin:4px 0 0;opacity:.85;font-size:13px">
          Generated: {run_start.strftime("%A, %B %d %Y at %I:%M %p")}
        </p>
      </div>

      <div style="background:#f1f8ff;padding:16px 24px;border:1px solid #c8e1ff">
        <p style="margin:0 0 10px;font-weight:600">Summary</p>
        {summary_html}
        <ul style="margin-top:14px;font-size:13px">
          {platform_breakdown}
        </ul>
      </div>

      <h3 style="color:#0077b5;border-bottom:2px solid #0077b5;padding-bottom:6px">
        All Applications ({total})
      </h3>
      {table_html}

      <p style="font-size:11px;color:#888;margin-top:20px;border-top:1px solid #eee;padding-top:10px">
        This is an automated report from the QA Job Application Bot.<br>
        Applied via LinkedIn Easy Apply (HTTP API) · Dice jobs are for manual review.
      </p>
    </body>
    </html>
    """


_th = "padding:10px 12px;text-align:left;white-space:nowrap"
_td = "padding:8px 12px;border-bottom:1px solid #eee"


def send_report(run_start: datetime | None = None):
    if not EMAIL_SENDER or not EMAIL_APP_PASSWORD:
        print("[Email] EMAIL_SENDER / EMAIL_APP_PASSWORD not set — skipping email")
        return

    if not EMAIL_RECIPIENTS:
        print("[Email] No recipients configured — skipping email")
        return

    if run_start is None:
        run_start = datetime.now()

    jobs = _read_jobs(run_start)
    if not jobs:
        print("[Email] No jobs found this run — skipping email")
        return

    html = _build_html(jobs, run_start)

    recipients = [r.strip() for r in EMAIL_RECIPIENTS.split(",") if r.strip()]
    subject = f"QA Job Report — {run_start.strftime('%b %d %Y %I:%M %p')} | {len(jobs)} jobs this run"

    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"] = EMAIL_SENDER
    msg["To"] = ", ".join(recipients)
    msg.attach(MIMEText(html, "html"))

    # Attach CSV
    if Path(TRACKER_FILE).exists():
        with open(TRACKER_FILE, "rb") as f:
            part = MIMEBase("application", "octet-stream")
            part.set_payload(f.read())
        encoders.encode_base64(part)
        part.add_header("Content-Disposition", f'attachment; filename="{TRACKER_FILE}"')
        msg.attach(part)

    try:
        print(f"[Email] Sending report to: {', '.join(recipients)}")
        with smtplib.SMTP("smtp.gmail.com", 587) as smtp:
            smtp.ehlo()
            smtp.starttls()
            smtp.login(EMAIL_SENDER, EMAIL_APP_PASSWORD)
            smtp.sendmail(EMAIL_SENDER, recipients, msg.as_string())
        print(f"[Email] Report sent successfully ({len(jobs)} jobs)")
    except smtplib.SMTPAuthenticationError:
        print("[Email] Auth failed — check EMAIL_APP_PASSWORD is a Gmail App Password (not your account password)")
    except Exception as e:
        print(f"[Email] Failed to send: {e}")
