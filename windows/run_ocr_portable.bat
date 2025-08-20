@echo off
setlocal enableextensions
cd /d %~dp0
cd ..

REM -- Use local Tesseract if bundled --
call windows\_set_tesseract_portable.bat

REM -- Determine runner: exe if exists, else python script --
set "RUNEXE=pdf2jsonl-ocr.exe"
set "RUNPY=pdf_to_jsonl_ocr_v4.py"

if "%~1"=="" (
  echo.
  echo [Interactive mode]
  set /p INPUT=Enter input PDF path: 
  set /p OUTDIR=Enter output folder: 
) else (
  set "INPUT=%~1"
  set "OUTDIR=%~2"
)

if not defined INPUT (
  echo [ERROR] Input PDF path is required.
  exit /b 2
)
if not defined OUTDIR (
  echo [ERROR] Output folder is required.
  exit /b 2
)

set "BASE_OPTS=--ocr auto --ocr-lang jpn+eng --ocr-rotate auto --ocr-psm 6 --ocr-dpi 300 --csv-encoding utf-8-sig --preflight-report preflight_report.json"

if exist "%RUNEXE%" (
  echo [INFO] Using EXE: %RUNEXE%
  "%RUNEXE%" -i "%INPUT" -o "%OUTDIR%" %BASE_OPTS%
) else if exist "%RUNPY%" (
  echo [INFO] Using Python script: %RUNPY%
  python "%RUNPY%" -i "%INPUT%" -o "%OUTDIR%" %BASE_OPTS%
) else (
  echo [ERROR] Runner not found (pdf2jsonl-ocr.exe or pdf_to_jsonl_ocr_v4.py).
  exit /b 3
)

if errorlevel 1 (
  echo [ERROR] Conversion failed.
  exit /b 1
) else (
  echo [OK] Conversion finished.
)
endlocal
