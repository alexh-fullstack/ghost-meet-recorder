@echo off
title Ghost Meet Recorder

where python >nul 2>nul
if errorlevel 1 (
    echo Python not found. Install Python 3.10+ from https://python.org
    pause
    exit /b 1
)

if not exist ".venv" (
    echo Creating virtual environment...
    python -m venv .venv
)

call .venv\Scripts\activate.bat

pip show customtkinter >nul 2>nul
if errorlevel 1 (
    echo Installing dependencies...
    pip install -r requirements.txt
)

start /b pythonw main.py