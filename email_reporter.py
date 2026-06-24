"""
Builds a single HTML email with one section per job portal and sends it
to all configured recipients.
"""

import csv
import smtplib
from collections import defaultdict, Counter
from datetime import datetime, timezone
from email import encoders
from email.mime.base import MIMEBase
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from pathlib import Path

from config import (
    EMAIL_SENDER, EMAIL_APP_PASSWORD,
    EMAIL_RECIPIENTS, TRACKER_FILE, MIN_HOURLY_RATE,
)

# ── Portal display config (order matters) ────────────────────────────
PORTALS = [
    ("LinkedIn",    "#0077b5", "LinkedIn — Collected Jobs"),
    ("Adzuna",      "#e84c4c", "Adzuna — Aggregator (Texas + Remote)"),
    ("Indeed",      "#2164f3", "Indeed — Aggregator (Texas + Remote)"),
    ("RemoteOK",    "#4caf50", "RemoteOK — Remote US"),
    ("ZipRecruiter","#f4511e", "ZipRecruiter — Texas + Remote"),
    ("Remotive",    "#2196f3", "Remotive — Remote US-Eligible"),
    ("Dice",        "#00a0dc", "Dice — Tech Contractor Board"),
    ("Glassdoor",   "#0caa41", "Glassdoor — Company Reviews + Jobs"),
]

# Status badge colors
_STATUS_COLORS = {
    "Easy Apply - Applied":           "#22863a",
    "Applied":                        "#22863a",
    "Easy Apply - Click to Apply":    "#22863a",
    "Collected - Easy Apply Available": "#0a66c2",
    "Collected - Manual Apply":       "#0077b5",
    "Collected - External Apply":     "#0077b5",
    "Easy Apply - Failed":            "#e36209",
    "Easy Apply - Error":             "#cb2431",
    "Failed - Manual Apply":          "#e36209",
    "Error":                          "#cb2431",
    "Skipped - 100+ Applicants":      "#6f42c1",
    "Skipped - Rate Below":           "#586069",
}

# Shared CSS — one definition covers all rows; badge colours each get a class.
# Shrinks per-row HTML from ~420 to ~220 chars, fitting 400+ jobs under Gmail's 102KB clip.
_EMAIL_CSS = """
<style>
.jt{width:100%;border-collapse:collapse;margin-top:8px;font-size:13px}
.jt th{padding:9px 11px;text-align:left;white-space:nowrap;color:#555;background:#f1f3f5}
.jt td{padding:7px 11px;border-bottom:1px solid #eee}
.jt tr.r0{background:#f6f8fa}.jt tr.r1{background:#fff}
.jt td.ts{color:#555;white-space:nowrap}.jt td.tt{font-weight:500}
a.va{color:#0077b5;font-size:13px}
a.ea{background:#0a66c2;color:#fff;padding:3px 10px;border-radius:4px;
     text-decoration:none;font-size:12px;font-weight:bold}
.bx{padding:2px 8px;border-radius:10px;font-size:11px;white-space:nowrap;color:#fff}
.bg{background:#22863a}.bb{background:#0a66c2}.bc{background:#0077b5}
.bo{background:#e36209}.br{background:#cb2431}.bp{background:#6f42c1}.bs{background:#586069}
</style>"""

_th = "padding:10px 12px;text-align:left;white-space:nowrap;font-size:13px"
_td = "padding:8px 12px;border-bottom:1px solid #eee;font-size:13px"


def _fmt_posted(val: str) -> str:
    """Convert a raw timestamp/date string to a human-readable posting age."""
    if not val:
        return "—"
    try:
        # Unix ms (LinkedIn listedAt: 13-digit number)
        if val.isdigit() and len(val) >= 13:
            dt = datetime.fromtimestamp(int(val) / 1000, tz=timezone.utc)
        # Unix seconds (RemoteOK epoch: 10-digit number)
        elif val.isdigit() and len(val) == 10:
            dt = datetime.fromtimestamp(int(val), tz=timezone.utc)
        # Adzuna format: "2024/06/22 10:30:15"
        elif "/" in val and " " in val:
            dt = datetime.strptime(val[:19], "%Y/%m/%d %H:%M:%S").replace(tzinfo=timezone.utc)
        else:
            dt = datetime.fromisoformat(val.replace("Z", "+00:00"))
        now   = datetime.now(timezone.utc)
        delta = now - dt
        mins  = int(delta.total_seconds() / 60)
        hours = mins // 60
        if mins < 60:
            return f"{mins}m ago"
        if hours < 24:
            return f"{hours}h ago"
        if delta.days == 1:
            return "1d ago"
        if delta.days < 8:
            return f"{delta.days}d ago"
        return dt.strftime("%b %d")
    except Exception:
        return val[:10] if val else "—"


def _badge(status: str) -> str:
    s = status.lower()
    if "easy apply available" in s:          cls = "bb"  # linkedin blue
    elif "collected" in s:                   cls = "bc"  # blue
    elif ("applied" in s or "easy apply" in s) and "fail" not in s and "error" not in s:
                                             cls = "bg"  # green
    elif "100+" in s or "applicants" in s:   cls = "bp"  # purple
    elif "fail" in s:                        cls = "bo"  # orange
    elif "error" in s:                       cls = "br"  # red
    else:                                    cls = "bs"  # grey (skipped / unknown)
    return f'<span class="bx {cls}">{status}</span>'



def _apply_link_compact(job: dict) -> str:
    url    = job.get("url", "")
    status = job.get("status", "")
    if not url:
        return "—"
    if status in ("Easy Apply - Click to Apply", "Collected - Easy Apply Available"):
        return f'<a href="{url}" class="ea">Easy Apply</a>'
    return f'<a href="{url}" class="va">View</a>'


def _portal_table(jobs: list[dict]) -> str:
    if not jobs:
        return '<p style="color:#888;font-size:13px;margin:8px 0 0">No jobs found this run.</p>'

    rows = ""
    for i, j in enumerate(jobs):
        rows += (
            f'<tr class="r{i%2}">'
            f'<td class="ts">{_fmt_posted(j.get("posted_at",""))}</td>'
            f'<td class="tt">{j.get("title","")}</td>'
            f'<td>{j.get("company","")}</td>'
            f'<td>{_badge(j.get("status",""))}</td>'
            f'<td>{_apply_link_compact(j)}</td>'
            f'</tr>'
        )

    return f"""
    <table class="jt">
      <thead><tr>
        <th>Posted</th><th>Job Title</th><th>Company</th><th>Status</th><th>Link</th>
      </tr></thead>
      <tbody>{rows}</tbody>
    </table>"""


def _portal_section(name: str, color: str, label: str, jobs: list[dict]) -> str:
    applied   = sum(1 for j in jobs if "applied" in j.get("status","").lower()
                    and "fail" not in j.get("status","").lower()
                    and "error" not in j.get("status","").lower())
    collected = sum(1 for j in jobs if "collected" in j.get("status","").lower())
    skipped   = sum(1 for j in jobs if "skipped" in j.get("status","").lower())
    failed    = sum(1 for j in jobs if "fail" in j.get("status","").lower()
                    or "error" in j.get("status","").lower())
    total     = len(jobs)

    chips = ""
    if total == 0:
        chips = '<span style="color:#888;font-size:12px">No results this run</span>'
    else:
        def chip(val, label_txt, col):
            if val == 0:
                return ""
            return (
                f'<span style="background:{col};color:#fff;padding:2px 10px;'
                f'border-radius:10px;font-size:12px;margin-right:6px">'
                f'{val} {label_txt}</span>'
            )
        chips = (
            chip(total,     "Found",     "#444")
            + chip(applied,   "Applied",   "#22863a")
            + chip(collected, "Collected", "#0077b5")
            + chip(skipped,   "Skipped",   "#586069")
            + chip(failed,    "Failed",    "#cb2431")
        )

    return f"""
    <div style="margin-top:28px;border:1px solid #e1e4e8;border-radius:8px;overflow:hidden">
      <div style="background:{color};color:#fff;padding:12px 18px;display:flex;align-items:center;justify-content:space-between">
        <div>
          <span style="font-weight:bold;font-size:16px">{name}</span>
          <span style="font-size:12px;opacity:.85;margin-left:10px">{label}</span>
        </div>
        <span style="font-size:22px;font-weight:bold;opacity:.9">{total}</span>
      </div>
      <div style="padding:10px 18px 6px;background:#fafbfc;border-bottom:1px solid #e1e4e8">
        {chips}
      </div>
      <div style="padding:0 18px 14px">
        {_portal_table(jobs)}
      </div>
    </div>"""


def _build_html(jobs: list[dict], run_start: datetime) -> str:
    by_platform: dict[str, list[dict]] = defaultdict(list)
    for j in jobs:
        by_platform[j.get("platform", "Unknown")].append(j)

    total     = len(jobs)
    applied   = sum(1 for j in jobs if "applied" in j.get("status","").lower()
                    and "fail" not in j.get("status","").lower()
                    and "error" not in j.get("status","").lower())
    collected = sum(1 for j in jobs if "collected" in j.get("status","").lower())
    skipped   = sum(1 for j in jobs if "skipped" in j.get("status","").lower())
    failed    = sum(1 for j in jobs if "fail" in j.get("status","").lower()
                    or "error" in j.get("status","").lower())

    def card(label, value, color):
        return (
            f'<div style="display:inline-block;background:{color};color:#fff;'
            f'border-radius:8px;padding:14px 22px;margin:6px;text-align:center;min-width:110px">'
            f'<div style="font-size:28px;font-weight:bold">{value}</div>'
            f'<div style="font-size:12px;margin-top:4px">{label}</div></div>'
        )

    summary_cards = (
        card("Total Found", total, "#444")
        + card("Applied", applied, "#22863a")
        + card("Collected", collected, "#0077b5")
        + card("Skipped", skipped, "#586069")
        + card("Failed / Error", failed, "#cb2431")
    )

    # Portal breakdown summary table
    breakdown_rows = ""
    for name, color, _ in PORTALS:
        p_jobs    = by_platform.get(name, [])
        p_applied = sum(1 for j in p_jobs if "applied" in j.get("status","").lower()
                        and "fail" not in j.get("status","").lower()
                        and "error" not in j.get("status","").lower())
        p_collect = sum(1 for j in p_jobs if "collected" in j.get("status","").lower())
        p_skip    = sum(1 for j in p_jobs if "skipped" in j.get("status","").lower())
        dot = f'<span style="display:inline-block;width:10px;height:10px;border-radius:50%;background:{color};margin-right:6px"></span>'
        breakdown_rows += (
            f'<tr>'
            f'<td style="{_td}">{dot}{name}</td>'
            f'<td style="{_td};text-align:center"><b>{len(p_jobs)}</b></td>'
            f'<td style="{_td};text-align:center;color:#22863a">{p_applied}</td>'
            f'<td style="{_td};text-align:center;color:#0077b5">{p_collect}</td>'
            f'<td style="{_td};text-align:center;color:#586069">{p_skip}</td>'
            f'</tr>'
        )

    breakdown_table = f"""
    <table style="width:100%;border-collapse:collapse;font-size:13px;margin-top:12px">
      <thead>
        <tr style="background:#f1f3f5">
          <th style="{_th};color:#555">Portal</th>
          <th style="{_th};color:#555;text-align:center">Found</th>
          <th style="{_th};color:#22863a;text-align:center">Applied</th>
          <th style="{_th};color:#0077b5;text-align:center">Collected</th>
          <th style="{_th};color:#586069;text-align:center">Skipped</th>
        </tr>
      </thead>
      <tbody>{breakdown_rows}</tbody>
    </table>"""

    # One section per portal
    portal_sections = ""
    for name, color, label in PORTALS:
        portal_sections += _portal_section(name, color, label, by_platform.get(name, []))

    return f"""
    <!DOCTYPE html>
    <html>
    <head><meta charset="UTF-8">{_EMAIL_CSS}</head>
    <body style="font-family:Arial,sans-serif;color:#24292e;max-width:980px;margin:0 auto;padding:20px">

      <div style="background:#0077b5;color:#fff;padding:20px 24px;border-radius:8px 8px 0 0">
        <h2 style="margin:0">QA Job Application Report</h2>
        <p style="margin:4px 0 0;opacity:.85;font-size:13px">
          {run_start.strftime("%A, %B %d %Y at %I:%M %p")}
          &nbsp;·&nbsp; {total} jobs across {len([n for n,_,_ in PORTALS if by_platform.get(n)])} portals
        </p>
      </div>

      <div style="background:#f1f8ff;padding:16px 24px;border:1px solid #c8e1ff;border-top:none">
        <p style="margin:0 0 8px;font-weight:600;font-size:14px">Overall Summary</p>
        {summary_cards}
        <p style="margin:14px 0 4px;font-weight:600;font-size:14px">By Portal</p>
        {breakdown_table}
      </div>

      {portal_sections}

      <p style="font-size:11px;color:#888;margin-top:24px;border-top:1px solid #eee;padding-top:10px">
        Automated report from QA Job Bot &nbsp;·&nbsp;
        LinkedIn Easy Apply (HTTP API) &nbsp;·&nbsp;
        All other portals require manual apply via the View Job link.
      </p>
    </body>
    </html>"""


def _read_jobs() -> list[dict]:
    if not Path(TRACKER_FILE).exists():
        return []
    with open(TRACKER_FILE, newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def send_report(run_start: datetime | None = None):
    if not EMAIL_SENDER or not EMAIL_APP_PASSWORD:
        print("[Email] EMAIL_SENDER / EMAIL_APP_PASSWORD not set — skipping")
        return
    if not EMAIL_RECIPIENTS:
        print("[Email] No recipients configured — skipping")
        return
    if run_start is None:
        run_start = datetime.now()

    jobs = _read_jobs()
    print(f"[Email] Tracker has {len(jobs)} jobs")
    if not jobs:
        print("[Email] No jobs in tracker — skipping email")
        return

    html       = _build_html(jobs, run_start)
    recipients = [r.strip() for r in EMAIL_RECIPIENTS.split(",") if r.strip()]
    subject    = (
        f"QA Job Report — {run_start.strftime('%b %d %Y %I:%M %p')} "
        f"| {len(jobs)} jobs"
    )

    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"]    = EMAIL_SENDER
    msg["To"]      = ", ".join(recipients)
    msg.attach(MIMEText(html, "html"))

    if Path(TRACKER_FILE).exists():
        with open(TRACKER_FILE, "rb") as f:
            part = MIMEBase("application", "octet-stream")
            part.set_payload(f.read())
        encoders.encode_base64(part)
        part.add_header("Content-Disposition", f'attachment; filename="{TRACKER_FILE}"')
        msg.attach(part)

    try:
        print(f"[Email] Sending to: {', '.join(recipients)}")
        with smtplib.SMTP("smtp.gmail.com", 587) as smtp:
            smtp.ehlo()
            smtp.starttls()
            smtp.login(EMAIL_SENDER, EMAIL_APP_PASSWORD)
            smtp.sendmail(EMAIL_SENDER, recipients, msg.as_string())
        print(f"[Email] Sent — {len(jobs)} jobs, {len(recipients)} recipients")
    except smtplib.SMTPAuthenticationError:
        print("[Email] Auth failed — check EMAIL_APP_PASSWORD is a Gmail App Password")
    except Exception as e:
        print(f"[Email] Failed: {e}")
