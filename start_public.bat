@echo off
chcp 65001 >nul
title 尔将AI助手 - 公开访问服务

echo ============================================
echo  尔将AI助手 - 启动公开访问服务
echo ============================================
echo.

set PROJECT_DIR=%~dp0
set CLOUDFLARED=%USERPROFILE%\.trae-cn\work\6a61c6335ca1edf6e77756c0\cloudflared.exe

REM 检查cloudflared是否存在
if not exist "%CLOUDFLARED%" (
    echo 正在下载 Cloudflare Tunnel...
    powershell -Command "Invoke-WebRequest -Uri 'https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-windows-amd64.exe' -OutFile '%CLOUDFLARED%' -UseBasicParsing"
    if !errorlevel! neq 0 (
        echo 下载失败，请手动下载:
        echo https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-windows-amd64.exe
        pause
        exit /b 1
    )
)

echo 1. 启动 Streamlit 应用...
cd /d "%PROJECT_DIR%"
start "Streamlit" cmd /c "python -m streamlit run app.py --server.port 8501 --server.headless true"
echo   等待5秒...
timeout /t 5 /nobreak >nul

echo 2. 启动 Cloudflare Tunnel...
echo   正在创建公开链接...
start "Cloudflare Tunnel" cmd /c "%CLOUDFLARED% tunnel --url http://localhost:8501"

echo.
echo ============================================
echo  ✅ 正在启动，请稍候...
echo.
echo  公开链接将在 Cloudflare Tunnel 窗口显示
echo  格式: https://xxxx.trycloudflare.com
echo ============================================
echo.
echo  将此链接分享给任何人，他们即可使用！
echo.
echo  按任意键查看启动状态...
pause >nul