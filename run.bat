@echo off
set VENV_DIR=.venv

:: 2. Activate environment and install dependencies
call %VENV_DIR%\Scripts\activate

:: 3. Run the application
start pythonw run.py
