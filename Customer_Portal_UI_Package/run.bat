@echo off
title Customer Portal UI Studio
chcp 65001 >nul
echo ========================================================
echo   🚀 در حال راه‌اندازی استودیو طراحی پرتال مشتری...
echo ========================================================
pip install -r requirements.txt -q
start http://127.0.0.1:5000
python app.py
pause
