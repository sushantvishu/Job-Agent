@echo off
echo Starting LinkedIn 1-Time Session Login...
cd /d "%~dp0"
call .venv\Scripts\activate.bat
python login_linkedin.py
pause

