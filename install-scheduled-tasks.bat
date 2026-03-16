@echo off
REM ============================================================================
REM Sentinel Aerial Inspections — Install Scheduled Tasks
REM
REM Creates Windows Task Scheduler entries for:
REM   1. Archive Sync — Weekly Sunday 2am
REM
REM Run as Administrator.
REM ============================================================================

setlocal

set "PYTHON=C:\Users\redle.SOULAAN\AppData\Local\Programs\Python\Python312\python.exe"
set "REPO_DIR=C:\Users\redle.SOULAAN\Documents\drone-pipeline"

echo.
echo  Installing Sentinel scheduled tasks...
echo  (Requires Administrator privileges)
echo.

REM ── Archive Sync — Weekly Sunday 2am
echo [1/1] Archive Sync (weekly Sunday 2:00 AM)...
schtasks /create /tn "Sentinel\ArchiveSync" /tr "\"%PYTHON%\" \"%REPO_DIR%\archive_sync.py\"" /sc weekly /d SUN /st 02:00 /rl HIGHEST /f
if errorlevel 1 (
    echo   FAIL: Could not create task. Run as Administrator.
) else (
    echo   OK: Task created — Sentinel\ArchiveSync
)

echo.
echo  Done. View tasks: taskschd.msc ^> Sentinel
echo.

endlocal
