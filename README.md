# QA Job Application Automation

Automatically searches LinkedIn, Adzuna, and RemoteOK for QA/SDET contract roles, AI-tailors your resume per job using Claude, and sends you a daily email report.

---

## How It Works

| Step | What runs | Where |
|---|---|---|
| 1 | **Adzuna + RemoteOK** collect jobs via public APIs | GitHub cloud (`ubuntu-latest`) |
| 2 | **LinkedIn Easy Apply** searches and applies | Your Windows PC (`self-hosted` runner) |
| 3 | **Email report** sent with all found jobs | End of LinkedIn step |

The split runner approach is intentional — LinkedIn blocks logins from GitHub cloud IPs (CHALLENGE error). Running on your own machine uses your home IP and avoids that.

---

## Prerequisites

- Python 3.11+
- Git
- A GitHub account with this repo
- Accounts on: LinkedIn, Adzuna (free API key), Gmail (App Password)
- Anthropic API key (for AI resume tailoring)

---

## Local Setup (Self-Hosted Runner — Required for LinkedIn)

### 1. Clone the repo

```bash
git clone https://github.com/vasanthsdet/job_automation.git
cd job_automation
```

### 2. Install Python dependencies

```bash
pip install -r requirements.txt
```

### 3. Add your resume

Place your resume at:

```
job_automation/resume/base_resume.docx
```

### 4. Create your `.env` file

Copy the example and fill in your values:

```bash
cp .env.example .env
```

```env
# ── Credentials ───────────────────────────────────────────────
LINKEDIN_EMAIL=your_linkedin_email@gmail.com
LINKEDIN_PASSWORD=your_linkedin_password
ANTHROPIC_API_KEY=sk-ant-...

# ── Adzuna (free key at https://developer.adzuna.com) ─────────
ADZUNA_APP_ID=your_app_id
ADZUNA_APP_KEY=your_app_key

# ── Email report (Gmail App Password, NOT your Gmail password) ─
# Steps: Google Account → Security → 2-Step Verification → App Passwords → Generate
EMAIL_SENDER=your_gmail@gmail.com
EMAIL_APP_PASSWORD=xxxx xxxx xxxx xxxx
EMAIL_RECIPIENTS=revathibathina11@gmail.com,dama.vasanth@gmail.com

# ── Job search config ─────────────────────────────────────────
JOB_SEARCH_KEYWORDS=QA Engineer,SDET,QA Automation,Automation QA
PRIMARY_LOCATION=Texas, United States
INCLUDE_REMOTE=true
JOB_TYPE=C
MAX_JOBS_TO_APPLY=10
LISTED_AT_DAYS=1
MIN_HOURLY_RATE=50
EXPECTED_HOURLY_RATE=50
YEARS_OF_EXPERIENCE=11
WORK_AUTHORIZATION=Yes
WILLING_TO_RELOCATE=YES
BASE_RESUME_PATH=resume/base_resume.docx
TRACKER_FILE=applied_jobs.csv
```

### 5. Run locally to test

```bash
# Full run (Adzuna + RemoteOK + LinkedIn)
python main.py

# Collect only (no LinkedIn apply)
python main.py --collect-only

# LinkedIn only
python main.py --linkedin-only

# Dry run (search only, no apply, no email)
python main.py --dry-run

# Pass credentials at runtime without storing in .env
python main.py --linkedin-email you@email.com --linkedin-password yourpass --technologies "SDET,QA"
```

---

## GitHub Actions Setup

The pipeline runs automatically 4× per day (7 AM, 11 AM, 3 PM, 7 PM CDT).

### Step 1 — Add GitHub Secrets

Go to your repo → **Settings → Secrets and variables → Actions → New repository secret**

Add each of these:

| Secret name | Value |
|---|---|
| `LINKEDIN_EMAIL` | Your LinkedIn email |
| `LINKEDIN_PASSWORD` | Your LinkedIn password |
| `ANTHROPIC_API_KEY` | From [console.anthropic.com](https://console.anthropic.com) |
| `EMAIL_SENDER` | Your Gmail address |
| `EMAIL_APP_PASSWORD` | Gmail App Password (not your login password) |
| `ADZUNA_APP_ID` | From [developer.adzuna.com](https://developer.adzuna.com) |
| `ADZUNA_APP_KEY` | From [developer.adzuna.com](https://developer.adzuna.com) |
| `RESUME_BASE64` | Your resume encoded as base64 (see below) |

**Encode your resume to base64:**

```powershell
# PowerShell (Windows)
[Convert]::ToBase64String([IO.File]::ReadAllBytes("C:\path\to\resume\base_resume.docx")) | Set-Clipboard
```

```bash
# Linux / macOS
base64 resume/base_resume.docx | pbcopy
```

Paste the output as the value of `RESUME_BASE64`.

### Step 2 — Create the `jobAlert` Environment

Secrets must be stored in the **`jobAlert`** environment (not just repo-level):

1. Go to repo → **Settings → Environments → New environment**
2. Name it exactly: `jobAlert`
3. Move all the secrets you added above into this environment
   *(Secrets → Environments → jobAlert → Add secret)*

### Step 3 — Install the Self-Hosted Runner (for LinkedIn)

LinkedIn runs on your local Windows machine to avoid bot detection.

1. Go to repo → **Settings → Actions → Runners → New self-hosted runner**
2. Select **Windows** → copy and run each command in PowerShell on your PC
3. When asked for runner labels, press Enter to use the default (`self-hosted`)
4. Start the runner:

```powershell
# Run once manually to verify
.\run.cmd

# Or install as a Windows service (runs in background automatically)
.\svc.cmd install
.\svc.cmd start
```

Once running, the `linkedin` job in the pipeline will automatically pick up your machine.

### Step 4 — Trigger manually (optional runtime overrides)

Go to repo → **Actions → LinkedIn Job Bot → Run workflow**

All inputs are optional — leave blank to use secrets/defaults:

| Input | Default |
|---|---|
| `linkedin_email` | `LINKEDIN_EMAIL` secret |
| `linkedin_password` | `LINKEDIN_PASSWORD` secret |
| `email_recipients` | `revathibathina11@gmail.com,dama.vasanth@gmail.com` |
| `technologies` | `QA Engineer,SDET,QA Automation,Automation QA` |

---

## Project Structure

```
job_automation/
├── main.py                  # Orchestrator — runs all bots in sequence
├── config.py                # Reads .env into Python variables
├── linkedin_bot.py          # LinkedIn Voyager API search + Easy Apply
├── adzuna_bot.py            # Adzuna REST API job collection
├── remoteok_bot.py          # RemoteOK public API job collection
├── ziprecruiter_bot.py      # ZipRecruiter API (optional key)
├── resume_updater.py        # AI resume tailoring via Claude Haiku
├── email_reporter.py        # HTML email report builder + sender
├── job_tracker.py           # CSV tracker (applied_jobs.csv)
├── utils.py                 # Shared helpers (rate filter, etc.)
├── requirements.txt
├── .env.example
├── resume/
│   └── base_resume.docx     # Your base resume (gitignored)
└── .github/
    └── workflows/
        └── linkedin_job_bot.yml
```

---

## API Keys Needed

| Service | Where to get | Cost |
|---|---|---|
| **Anthropic** | [console.anthropic.com](https://console.anthropic.com) | Pay per use (~$0.01/run) |
| **Adzuna** | [developer.adzuna.com](https://developer.adzuna.com) | Free (250 calls/day) |
| **Gmail App Password** | Google Account → Security → App Passwords | Free |
| **ZipRecruiter** | [ziprecruiter.com/zap/app](https://www.ziprecruiter.com/zap/app) | Free (optional) |
