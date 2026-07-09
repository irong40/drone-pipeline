@echo off
REM ===========================================================================
REM  Sentinel Aerial - headless RGB vegetation analysis wrapper (Windows)
REM  Invokes the QGIS-LTR python so PyQGIS + GDAL resolve, no GUI required.
REM
REM  Usage:
REM    run_veg_analysis.bat <ortho.tif> <out_dir> [mission_id]
REM
REM  Example:
REM    run_veg_analysis.bat "I:\My Drive\...\odm_orthophoto.tif" ".\out" ZV-0142
REM ===========================================================================
setlocal

REM --- edit this if your QGIS version differs -------------------------------
set "QGIS_PY=C:\Program Files\QGIS 3.44.12\bin\python-qgis-ltr.bat"

if not exist "%QGIS_PY%" (
  echo [ERROR] QGIS python not found at "%QGIS_PY%".
  echo         Update QGIS_PY in this .bat to your installed QGIS version.
  exit /b 2
)

set "ORTHO=%~1"
set "OUTDIR=%~2"
set "MID=%~3"
if "%MID%"=="" set "MID=ad-hoc"

if "%ORTHO%"=="" (
  echo Usage: run_veg_analysis.bat ^<ortho.tif^> ^<out_dir^> [mission_id]
  exit /b 1
)

set "SCRIPT=%~dp0rgb_vegetation_analysis.py"

echo [run] "%QGIS_PY%" "%SCRIPT%" --ortho "%ORTHO%" --out "%OUTDIR%" --mission-id "%MID%"
call "%QGIS_PY%" "%SCRIPT%" --ortho "%ORTHO%" --out "%OUTDIR%" --mission-id "%MID%"
exit /b %errorlevel%
