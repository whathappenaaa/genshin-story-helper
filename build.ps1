$ErrorActionPreference = 'Stop'

$projectRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$buildEnvironment = Join-Path $projectRoot '.build_env'
$buildPython = Join-Path $buildEnvironment 'Scripts\python.exe'

if (-not (Test-Path -LiteralPath $buildPython)) {
    py -3 -m venv $buildEnvironment
}

& $buildPython -m pip install --disable-pip-version-check -r (Join-Path $projectRoot 'requirements-build.txt')
& $buildPython -m PyInstaller `
    --noconfirm `
    --clean `
    --onefile `
    --windowed `
    --uac-admin `
    --collect-all customtkinter `
    --add-data ((Join-Path $projectRoot 'assets\raiden-app-icon-256.png') + ';assets') `
    --icon (Join-Path $projectRoot 'assets\raiden-app-icon.ico') `
    --name '把你砌进神像里' `
    --distpath (Join-Path $projectRoot 'dist') `
    --workpath (Join-Path $projectRoot 'build\work') `
    --specpath (Join-Path $projectRoot 'build') `
    (Join-Path $projectRoot 'genshin_story_helper.pyw')

Write-Host ''
Write-Host ('构建完成：' + (Join-Path $projectRoot 'dist\把你砌进神像里.exe')) -ForegroundColor Green
