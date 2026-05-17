#!/usr/bin/env pwsh
# Smoke-test the .bat scripts that mirror the .sh scripts in this repo.
#
# Runs on any platform with PowerShell 7+ (`pwsh`). Does NOT actually execute
# the .bat files — cmd.exe isn't available on macOS/Linux — but verifies
# structural invariants that catch typical authoring mistakes:
#   1. Every in-scope .sh has a sibling .bat
#   2. Every .bat starts with `@echo off`
#   3. Every .bat terminates the main flow with `exit /b`
#   4. Delegate shims reference an actually-existing .sh
#   5. `_delegate_to_bash.bat` exists where delegates expect it
#
# On Windows, this same script can be extended to actually invoke each .bat
# with --help (where supported) and check the exit code.
#
# Usage:  pwsh scripts/test_bat_scripts.ps1

$ErrorActionPreference = 'Stop'
$repoRoot = (Resolve-Path "$PSScriptRoot/..").Path

$failures = [System.Collections.Generic.List[string]]::new()
$passes   = 0
function Fail([string]$msg) { $script:failures.Add($msg); Write-Host "  FAIL  $msg" -ForegroundColor Red }
function Pass([string]$msg) { $script:passes++;          Write-Host "  ok    $msg" -ForegroundColor DarkGreen }

$excludedDirs = @('vendor', 'node_modules', '.venv', '.git', 'site-packages')
$excludedPathFrag = 'benchmarks' + [IO.Path]::DirectorySeparatorChar + 'appworld' + [IO.Path]::DirectorySeparatorChar + 'appworld'

function IsExcluded([string]$path) {
    foreach ($d in $excludedDirs) {
        if ($path -match ([regex]::Escape([IO.Path]::DirectorySeparatorChar + $d + [IO.Path]::DirectorySeparatorChar))) { return $true }
    }
    if ($path -like "*$excludedPathFrag*") { return $true }
    return $false
}

function RelPath([string]$full) { return $full.Substring($repoRoot.Length + 1) }

$shFiles  = Get-ChildItem -Path $repoRoot -Recurse -Filter '*.sh'  -File | Where-Object { -not (IsExcluded $_.FullName) }
$batFiles = Get-ChildItem -Path $repoRoot -Recurse -Filter '*.bat' -File | Where-Object { -not (IsExcluded $_.FullName) }

Write-Host "Repo root: $repoRoot"
Write-Host "Found $($shFiles.Count) .sh files and $($batFiles.Count) .bat files in scope."

# ---- [1] every .sh has a sibling .bat -----------------------------------
Write-Host "`n[1] every .sh has a sibling .bat" -ForegroundColor Cyan
foreach ($sh in $shFiles) {
    $sibling = [IO.Path]::ChangeExtension($sh.FullName, '.bat')
    if (Test-Path -LiteralPath $sibling) { Pass (RelPath $sh.FullName) }
    else { Fail "missing .bat sibling for $(RelPath $sh.FullName)" }
}

# ---- [2] every .bat starts with @echo off --------------------------------
Write-Host "`n[2] every .bat starts with '@echo off'" -ForegroundColor Cyan
foreach ($bat in $batFiles) {
    $first = (Get-Content -LiteralPath $bat.FullName -TotalCount 1).Trim()
    if ($first -eq '@echo off') { Pass (RelPath $bat.FullName) }
    else { Fail "$(RelPath $bat.FullName) first line is '$first', expected '@echo off'" }
}

# ---- [3] every .bat has an `exit /b` terminator --------------------------
# common.bat is intentionally a placeholder and uses `exit /b 0` early; ok.
Write-Host "`n[3] every .bat contains 'exit /b' somewhere" -ForegroundColor Cyan
foreach ($bat in $batFiles) {
    $content = Get-Content -LiteralPath $bat.FullName -Raw
    if ($content -match 'exit\s+/b') { Pass (RelPath $bat.FullName) }
    else { Fail "$(RelPath $bat.FullName) has no 'exit /b' terminator" }
}

# ---- [4] delegate shims reference a real .sh -----------------------------
# Skip _delegate_to_bash.bat itself — its REM comments contain example
# placeholders like "<absolute-or-relative-path-to-script.sh>" that aren't
# actual code paths.
Write-Host "`n[4] delegate shims reference an existing .sh" -ForegroundColor Cyan
$delegateRegex = [regex]'_delegate_to_bash\.bat"\s+"([^"]+)"'
foreach ($bat in $batFiles) {
    if ($bat.Name -eq '_delegate_to_bash.bat') { continue }
    # Strip REM-prefixed lines so example syntax in comment blocks is ignored.
    $codeLines = (Get-Content -LiteralPath $bat.FullName) | Where-Object { $_ -notmatch '^\s*(REM|::|@REM)\s' }
    $content = $codeLines -join "`n"
    $m = $delegateRegex.Match($content)
    if (-not $m.Success) { continue }  # not a delegate shim
    $target = $m.Groups[1].Value
    # Expand %_THIS% to the .bat's own directory, normalise separators.
    $batDir = Split-Path -Parent $bat.FullName
    $resolved = $target -replace '%_THIS%', $batDir
    $resolved = $resolved -replace '\\', ([IO.Path]::DirectorySeparatorChar)
    # Collapse parent traversals (Resolve-Path errors if the file is missing)
    try {
        $abs = [IO.Path]::GetFullPath($resolved)
    } catch { $abs = $resolved }
    if (Test-Path -LiteralPath $abs) {
        Pass "$(RelPath $bat.FullName) -> $(Split-Path -Leaf $abs)"
    } else {
        Fail "$(RelPath $bat.FullName) delegates to missing $target (resolved: $abs)"
    }
}

# ---- [5] every delegate shim's _delegate_to_bash.bat actually exists -----
# Skip the helper itself; its own REM block shows an example `call` statement.
Write-Host "`n[5] _delegate_to_bash.bat exists where shims expect it" -ForegroundColor Cyan
$delegateHelperRegex = [regex]'call\s+"([^"]*_delegate_to_bash\.bat)"'
foreach ($bat in $batFiles) {
    if ($bat.Name -eq '_delegate_to_bash.bat') { continue }
    $codeLines = (Get-Content -LiteralPath $bat.FullName) | Where-Object { $_ -notmatch '^\s*(REM|::|@REM)\s' }
    $content = $codeLines -join "`n"
    $m = $delegateHelperRegex.Match($content)
    if (-not $m.Success) { continue }
    $target = $m.Groups[1].Value
    $batDir = Split-Path -Parent $bat.FullName
    $resolved = $target -replace '%_THIS%', $batDir
    $resolved = $resolved -replace '\\', ([IO.Path]::DirectorySeparatorChar)
    try { $abs = [IO.Path]::GetFullPath($resolved) } catch { $abs = $resolved }
    if (Test-Path -LiteralPath $abs) {
        Pass (RelPath $bat.FullName)
    } else {
        Fail "$(RelPath $bat.FullName) calls missing $target (resolved: $abs)"
    }
}

# ---- summary -------------------------------------------------------------
Write-Host "`n=== Summary ===" -ForegroundColor Cyan
Write-Host ("checks passed: {0}" -f $passes) -ForegroundColor Green
Write-Host ("checks failed: {0}" -f $failures.Count) -ForegroundColor ($(if ($failures.Count -eq 0) { 'Green' } else { 'Red' }))
if ($failures.Count -gt 0) {
    Write-Host "`nFailures:" -ForegroundColor Red
    $failures | ForEach-Object { Write-Host "  - $_" -ForegroundColor Red }
    exit 1
}
Write-Host "`nAll structural checks passed."
exit 0
