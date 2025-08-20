@echo off
REM Resolve local Tesseract if bundled next to this script
setlocal
cd /d %~dp0
cd ..
set "_TESS=%CD%\Tesseract-OCR\tesseract.exe"
if exist "%_TESS%" (
  setx TESSERACT_EXE "%_TESS%" >nul 2>&1
  setx TESSDATA_PREFIX "%CD%\Tesseract-OCR" >nul 2>&1
  set "TESSERACT_EXE=%_TESS%"
  set "TESSDATA_PREFIX=%CD%\Tesseract-OCR"
  echo [INFO] Using bundled Tesseract: %_TESS%
) else (
  echo [INFO] Bundled Tesseract not found. Will use system PATH.
)
endlocal & set TESSERACT_EXE=%TESSERACT_EXE% & set TESSDATA_PREFIX=%TESSDATA_PREFIX%
