$ErrorActionPreference = 'Stop'
Set-Location -LiteralPath $PSScriptRoot
$candidates = @('py', 'python')
$candidates += @(Get-ChildItem "$env:LOCALAPPDATA\Programs\Python\Python*\python.exe" -ErrorAction SilentlyContinue | Sort-Object FullName -Descending | Select-Object -ExpandProperty FullName)
$candidates += @(Get-ChildItem "$env:ProgramFiles\Python*\python.exe" -ErrorAction SilentlyContinue | Select-Object -ExpandProperty FullName)
foreach ($candidate in $candidates) {
    try {
        $python = & $candidate -c 'import sys; print(sys.executable) if sys.version_info >= (3,9) else sys.exit(1)' 2>$null
        if ($LASTEXITCODE -ne 0 -or -not $python -or -not (Test-Path -LiteralPath ([string]$python))) { continue }
    } catch { continue }
    & $python (Join-Path $PSScriptRoot 'setup.py') --check
    if ($LASTEXITCODE -ne 0) { Write-Host 'Run install.bat first.'; exit 1 }
    & $python (Join-Path $PSScriptRoot 'server.py')
    exit $LASTEXITCODE
}
Write-Host 'Python 3.9+ is required. Run install.bat first.'
exit 1
