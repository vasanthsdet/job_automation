@echo off
echo ============================================================
echo  QA Job Automation - First-time Setup (HTTP/API only)
echo ============================================================

echo.
echo [1/3] Installing Python dependencies...
pip install -r requirements.txt
if %errorlevel% neq 0 (
    echo ERROR: pip install failed. Make sure Python 3.10+ is installed.
    pause & exit /b 1
)

echo.
echo [2/3] Creating .env from template...
if not exist .env (
    copy .env.example .env
    echo .env created — open it and fill in your credentials!
) else (
    echo .env already exists — skipping
)

echo.
echo [3/3] Checking for resume...
if not exist resume\base_resume.docx (
    echo WARNING: Place your resume as resume\base_resume.docx before running.
) else (
    echo Resume found.
)

echo.
echo ============================================================
echo  Setup complete!
echo.
echo  Next steps:
echo  1. Edit .env with LinkedIn/Dice credentials + Anthropic key
echo  2. Copy your resume to resume\base_resume.docx
echo  3. python main.py
echo ============================================================
pause
