param(
    [Parameter(Mandatory = $true)][string]$WorkbookPath,
    [string]$ProjectRoot = (Split-Path -Parent $PSScriptRoot),
    [string]$PythonExe = "python"
)

$ErrorActionPreference = "Stop"
$resolvedWorkbook = (Resolve-Path -LiteralPath $WorkbookPath).Path
$resolvedRoot = (Resolve-Path -LiteralPath $ProjectRoot).Path
$buildScript = Join-Path $resolvedRoot "jobs\build_period.py"

if (-not (Test-Path -LiteralPath $buildScript -PathType Leaf)) {
    throw "Build script not found: $buildScript"
}
if (Test-Path -LiteralPath $PythonExe -PathType Leaf) {
    $PythonExe = (Resolve-Path -LiteralPath $PythonExe).Path
}
else {
    $pythonCommand = Get-Command $PythonExe -ErrorAction SilentlyContinue
    if (-not $pythonCommand) {
        throw "Python executable was not found: $PythonExe"
    }
    $PythonExe = $pythonCommand.Source
}

Push-Location $resolvedRoot
try {
    & $PythonExe $buildScript --source $resolvedWorkbook
    if ($LASTEXITCODE -ne 0) {
        throw "DELFI period build failed with exit code $LASTEXITCODE. Check the quarantined reconciliation report."
    }
}
finally {
    Pop-Location
}
