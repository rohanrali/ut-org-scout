@echo off
title UT Org Finder
cd /d "%~dp0"
set PYTHONIOENCODING=utf-8
set PYTHONUTF8=1

echo ============================================
echo   UT Org Finder
echo ============================================
echo.

set PY=
py -c "1" >nul 2>nul && set PY=py
if not defined PY ( python -c "1" >nul 2>nul && set PY=python )
if not defined PY (
  echo Python isn't working on this PC. Opening the download page...
  start "" https://www.python.org/downloads/
  pause
  exit /b
)

if not exist .env (
  echo Paste your Apify API token below, then press Enter.
  echo ^(apify.com - Settings - API ^& Integrations^)
  set /p TOKEN=Token: 
  call :savetoken
)

echo.
echo Installing packages...
%PY% -m pip install --quiet --disable-pip-version-check -r requirements.txt
if errorlevel 1 (
  echo Package install failed. Copy the text above ^(not your token^) and send it to Claude.
  pause
  exit /b
)

echo.
echo Finding UT org accounts and officers. This takes about 30-45 minutes - leave this window open.
echo.
%PY% org_finder.py %*
if errorlevel 1 (
  echo.
  echo Something went wrong. Copy the text above ^(not your token^) and send it to Claude.
  pause
  exit /b
)

for /f "delims=" %%f in ('dir /b /o-d ut_orgs_*.xlsx 2^>nul') do (
  start "" "%%f"
  goto opened
)
:opened
echo.
echo All done! Your spreadsheet should open now.
pause
exit /b

:savetoken
>.env echo APIFY_TOKEN=%TOKEN%
exit /b
