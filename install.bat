@echo off
set VENV_DIR=.venv

:: 1. Create virtual environment if it doesn't exist
if not exist %VENV_DIR% (
    echo Creating virtual environment...
    python -m venv %VENV_DIR%
)

:: 2. Activate environment and install dependencies
call %VENV_DIR%\Scripts\activate

if exist requirements.txt (
    echo Installing dependencies from requirements.txt...
    pip install -r requirements.txt
) else (
    echo [Warning] requirements.txt not found. Skipping installation.
)

:: Keep the window open if the app crashes or finishes
pause
