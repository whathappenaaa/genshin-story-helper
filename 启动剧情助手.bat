@echo off
cd /d "%~dp0"
if exist "%~dp0dist\原神剧情辅助.exe" (
    start "" "%~dp0dist\原神剧情辅助.exe"
    exit /b 0
)
start "" pyw -3 "%~dp0genshin_story_helper.pyw"
