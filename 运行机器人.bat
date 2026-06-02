@echo off
title Petezz Bot
cd /d "%~dp0"
echo ========================================
echo   Petezz Bot - Starting...
echo ========================================
echo.
echo Installing dependencies (this may take a minute)...
echo.

set PIP_MIRROR=-i https://pypi.tuna.tsinghua.edu.cn/simple

python -m pip install -r requirements.txt %PIP_MIRROR%
if %errorlevel% neq 0 (
    echo [Info] Trying alternative python command...
    py -m pip install -r requirements.txt %PIP_MIRROR%
)
if %errorlevel% neq 0 (
    echo [Info] Manual installation...
    python -m pip install itchat-uos==1.5.0.dev0 google-genai %PIP_MIRROR%
    py -m pip install itchat-uos==1.5.0.dev0 google-genai %PIP_MIRROR%
)

echo.
echo ========================================
echo   Scan QR code to login!
echo ========================================
echo.

python main.py
if %errorlevel% neq 0 (
    py main.py
)

echo.
pause