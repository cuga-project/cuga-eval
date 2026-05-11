@echo off
REM ============================================================================
REM  fix_line_endings.bat
REM
REM  Strips CRLF line endings from *.sh and *.env files in this repo so they
REM  work under WSL bash. Run this once on Windows after cloning the repo (or
REM  after pulling, if you have stale CRLF files), BEFORE running setup_cuga.sh
REM  or setup_m3.sh under WSL.
REM
REM  Usage:  double-click, or from cmd.exe / PowerShell:  fix_line_endings.bat
REM ============================================================================

setlocal
cd /d "%~dp0"

echo.
echo Normalizing *.sh and *.env line endings (CRLF -^> LF) under:
echo   %CD%
echo.

powershell -NoProfile -ExecutionPolicy Bypass -Command "$ErrorActionPreference='Stop'; $root = (Get-Location).Path; $count = 0; $files = Get-ChildItem -Path . -Recurse -File -Include *.sh,*.env | Where-Object { $_.FullName -notmatch '\\(\.git|\.venv|vendor|node_modules)\\' }; foreach ($f in $files) { $b = [IO.File]::ReadAllBytes($f.FullName); if ($b -contains 13) { $c = New-Object Collections.Generic.List[byte]; foreach ($x in $b) { if ($x -ne 13) { $c.Add($x) } }; [IO.File]::WriteAllBytes($f.FullName, $c.ToArray()); Write-Host ('  normalized: ' + $f.FullName.Substring($root.Length + 1)); $count++ } }; Write-Host ''; Write-Host ('Normalized ' + $count + ' file(s).')"

if errorlevel 1 (
    echo.
    echo ERROR: normalization failed. See PowerShell error above.
    exit /b 1
)

echo.
echo Done. You can now run setup_cuga.sh / setup_m3.sh under WSL.
echo.

REM Pause so the window stays open if double-clicked from Explorer.
if defined PROMPT goto :end
pause
:end
endlocal
