@echo off
setlocal EnableDelayedExpansion

echo ============================================================
echo  QA Job Automation — Windows Task Scheduler Setup
echo  Runs every 6 hours: 7AM / 1PM / 7PM / 1AM (no terminal needed)
echo ============================================================

:: Find Python executable
for /f "tokens=*" %%i in ('where python 2^>nul') do (
    set PYTHON_EXE=%%i
    goto :found_python
)
echo ERROR: Python not found in PATH. Install Python and re-run.
pause & exit /b 1
:found_python
echo Found Python: %PYTHON_EXE%

:: Set paths
set SCRIPT_DIR=%~dp0
set SCRIPT_DIR=%SCRIPT_DIR:~0,-1%
set MAIN_SCRIPT=%SCRIPT_DIR%\main.py
set LOG_FILE=%SCRIPT_DIR%\task_scheduler.log
set TASK_NAME=QA_Job_Automation
set WRAPPER_BAT=%SCRIPT_DIR%\run_job_bot.bat

:: Create wrapper bat that logs output
(
  echo @echo off
  echo cd /d "%SCRIPT_DIR%"
  echo echo [%%date%% %%time%%] Starting QA Job Bot ^>^> "%LOG_FILE%"
  echo "%PYTHON_EXE%" "%MAIN_SCRIPT%" ^>^> "%LOG_FILE%" 2^>^&1
  echo echo [%%date%% %%time%%] Run complete ^>^> "%LOG_FILE%"
) > "%WRAPPER_BAT%"
echo Created wrapper: %WRAPPER_BAT%

:: Remove old task if exists
schtasks /delete /tn "%TASK_NAME%" /f >nul 2>&1

:: Create task: daily at 7:00 AM, repeat every 6 hours (4 runs/day)
schtasks /create ^
  /tn "%TASK_NAME%" ^
  /tr "\"%WRAPPER_BAT%\"" ^
  /sc DAILY ^
  /st 07:00 ^
  /ri 360 ^
  /du 1440 ^
  /rl HIGHEST ^
  /f

if %errorlevel% equ 0 (
    echo.
    echo ============================================================
    echo  Task registered successfully!
    echo.
    echo  Name     : %TASK_NAME%
    echo  Schedule : 7:00 AM, 1:00 PM, 7:00 PM, 1:00 AM (daily)
    echo  Logs     : %LOG_FILE%
    echo.
    echo  To run immediately : schtasks /run /tn "%TASK_NAME%"
    echo  To view task       : Task Scheduler ^> Task Scheduler Library
    echo  To remove          : schtasks /delete /tn "%TASK_NAME%" /f
    echo ============================================================
) else (
    echo.
    echo ERROR: Failed to create task. Right-click this .bat and
    echo        choose "Run as administrator", then try again.
)
pause
