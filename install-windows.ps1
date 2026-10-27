$ErrorActionPreference = 'Stop'
Set-Location -LiteralPath $PSScriptRoot

function Find-Python {
    $candidates = @('py', 'python')
    $candidates += @(Get-ChildItem "$env:LOCALAPPDATA\Programs\Python\Python*\python.exe" -ErrorAction SilentlyContinue | Sort-Object FullName -Descending | Select-Object -ExpandProperty FullName)
    $candidates += @(Get-ChildItem "$env:ProgramFiles\Python*\python.exe" -ErrorAction SilentlyContinue | Select-Object -ExpandProperty FullName)
    foreach ($candidate in $candidates) {
        try {
            $result = & $candidate -c 'import sys; print(sys.executable) if sys.version_info >= (3,9) else sys.exit(1)' 2>$null
            if ($LASTEXITCODE -eq 0 -and $result -and (Test-Path -LiteralPath ([string]$result))) { return [string]$result }
        } catch { }
    }
    return $null
}

try {
    $python = Find-Python
    if (-not $python) {
        if (-not (Get-Command winget -ErrorAction SilentlyContinue)) {
            throw 'Python is missing and winget is unavailable. Install Python 3 from https://www.python.org/downloads/windows/ and run this script again.'
        }
        Write-Host 'Installing Python 3.12 using winget...'
        & winget install --id Python.Python.3.12 --exact --source winget --scope user --accept-source-agreements --accept-package-agreements
        if ($LASTEXITCODE -ne 0) { throw 'Python installation failed. Please install Python 3 manually and retry.' }
        $python = Find-Python
        if (-not $python) { throw 'Python was not found. Close this window and run the installer again.' }
    }
    & $python (Join-Path $PSScriptRoot 'setup.py')
    if ($LASTEXITCODE -ne 0) { throw 'FFmpeg setup failed. See the message above, then retry.' }
    Write-Host 'Ready. Double-click start.bat to launch.' -ForegroundColor Green
    exit 0
} catch {
    Write-Host $_.Exception.Message -ForegroundColor Red
    exit 1
}
