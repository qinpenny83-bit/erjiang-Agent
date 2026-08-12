@echo off
chcp 65001 >nul
echo ============================================
echo   ??????????Agent
echo   ??? release-v1.0.1-final
echo ============================================
echo.

:: 1. ????????
echo [1/5] ??????...
taskkill /F /IM python.exe >nul 2>&1
echo       ???

:: 2. ??????????? v1.0.1-final?
echo [2/5] ?????????...
powershell -Command "& 7z x '%~dp0releases\release-v1.0.1-final_20260812_180216.zip' -o'%~dp0' -y" >nul 2>&1
if %errorlevel% neq 0 (
    echo       ? ???????? releases\release-v1.0.1-final_20260812_180216.zip ????
    pause
    exit /b 1
)
echo       ?????

:: 3. ?? Python ??
echo [3/5] ????...
powershell -Command "Remove-Item -Recurse -Force '%~dp0core\__pycache__' -ErrorAction SilentlyContinue"
powershell -Command "Remove-Item -Recurse -Force '%~dp0utils\__pycache__' -ErrorAction SilentlyContinue"
echo       ?????

:: 4. ?? .env
echo [4/5] ??????...
if not exist "%~dp0.env" (
    echo       ? .env ??????? .env.example ??...
    copy "%~dp0.env.example" "%~dp0.env" >nul
    echo       ??? .env ????? API Key?
) else (
    echo       .env ???
)

:: 5. ??
echo [5/5] ????...
powershell -Command "if (Test-Path '%~dp0packages.txt') { Write-Host '       ? ?????? ? release-v1.0.1-final' } else { Write-Host '       ? ???????' }"

echo.
echo ============================================
echo   ??????????
echo   python -m streamlit run app.py --server.port 8501 --server.headless true
echo ============================================
echo.
echo   ????? release-v1.0-final???????
echo   & 7z x releases\release-v1.0-final_20260812_173833.zip -o. -y
pause