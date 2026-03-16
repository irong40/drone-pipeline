@echo off
REM ============================================================================
REM Sentinel Aerial Inspections — Pipeline Startup
REM
REM Starts all pipeline services:
REM   1. Verifies Docker containers (WebODM, NodeODM, n8n) are running
REM   2. Starts folder watcher for incoming missions
REM   3. Verifies Supabase connectivity
REM   4. Verifies FFmpeg is available
REM
REM Usage:
REM   start-all.bat          Start everything
REM   start-all.bat --check  Health check only (don't start watcher)
REM ============================================================================

setlocal enabledelayedexpansion

set "REPO_DIR=%~dp0"
set "PYTHON=C:\Users\redle.SOULAAN\AppData\Local\Programs\Python\Python312\python.exe"
set "INCOMING=E:\incoming"
set "OUTPUT=E:\output"

echo.
echo  ============================================
echo   Sentinel Aerial Inspections — Pipeline
echo  ============================================
echo.

REM ── Check Python
echo [1/6] Python...
"%PYTHON%" --version >nul 2>&1
if errorlevel 1 (
    echo   FAIL: Python not found at %PYTHON%
    goto :fail
)
for /f "tokens=*" %%v in ('"%PYTHON%" --version 2^>^&1') do echo   OK: %%v

REM ── Check FFmpeg
echo [2/6] FFmpeg...
ffmpeg -version >nul 2>&1
if errorlevel 1 (
    echo   WARN: FFmpeg not found in PATH — video processing will fail
) else (
    echo   OK: FFmpeg available
)

REM ── Check Docker containers
echo [3/6] Docker containers...
set "DOCKER_OK=1"

docker ps --format "{{.Names}}" 2>nul | findstr /i "webapp" >nul
if errorlevel 1 (
    echo   WARN: WebODM webapp not running
    set "DOCKER_OK=0"
) else (
    echo   OK: WebODM webapp
)

docker ps --format "{{.Names}}" 2>nul | findstr /i "nodeodm" >nul
if errorlevel 1 (
    echo   WARN: NodeODM not running — Path C will fail
    set "DOCKER_OK=0"
) else (
    echo   OK: NodeODM (GPU)
)

docker ps --format "{{.Names}}" 2>nul | findstr /i "n8n" >nul
if errorlevel 1 (
    echo   WARN: n8n not running — workflow orchestration unavailable
    set "DOCKER_OK=0"
) else (
    echo   OK: n8n
)

REM ── Check directories
echo [4/6] Directories...
if not exist "%INCOMING%" (
    mkdir "%INCOMING%"
    echo   Created: %INCOMING%
) else (
    echo   OK: %INCOMING%
)
if not exist "%OUTPUT%" (
    mkdir "%OUTPUT%"
    echo   Created: %OUTPUT%
) else (
    echo   OK: %OUTPUT%
)
if not exist "%REPO_DIR%logs" (
    mkdir "%REPO_DIR%logs"
    echo   Created: %REPO_DIR%logs
) else (
    echo   OK: %REPO_DIR%logs
)

REM ── Check Supabase env vars
echo [5/6] Supabase...
if "%SUPABASE_URL%"=="" (
    REM Try loading from .env
    if exist "%REPO_DIR%.env" (
        for /f "usebackq tokens=1,* delims==" %%a in ("%REPO_DIR%.env") do (
            if "%%a"=="SUPABASE_URL" set "SUPABASE_URL=%%b"
            if "%%a"=="SUPABASE_SERVICE_KEY" set "SUPABASE_SERVICE_KEY=%%b"
        )
    )
)
if "%SUPABASE_URL%"=="" (
    echo   WARN: SUPABASE_URL not set — Supabase features unavailable
) else (
    echo   OK: SUPABASE_URL configured
)

REM ── Check-only mode
echo [6/6] Services...
if "%1"=="--check" (
    echo   Health check complete — no services started.
    echo.
    goto :done
)

REM ── Start folder watcher
echo   Starting folder watcher...
start "Sentinel Folder Watcher" /min "%PYTHON%" "%REPO_DIR%folder_watcher.py" --watch-dir "%INCOMING%"
echo   OK: Folder watcher started (minimized)

echo.
echo  ============================================
echo   Pipeline ready.
echo.
echo   Incoming:  %INCOMING%
echo   Output:    %OUTPUT%
echo   Logs:      %REPO_DIR%logs\
echo   n8n:       http://localhost:5678
echo   NodeODM:   http://localhost:3000
echo  ============================================
echo.

:done
endlocal
exit /b 0

:fail
endlocal
exit /b 1
