param(
    [Parameter(Mandatory = $true)][string]$WorkbookPath,
    [Parameter(Mandatory = $true)][string]$ProjectRoot,
    [string]$TaskName = "DELFI Utilisation Monthly Build",
    [string]$RunAt = "02:00"
)

$ErrorActionPreference = "Stop"
$resolvedRoot = (Resolve-Path -LiteralPath $ProjectRoot).Path
$resolvedWorkbook = (Resolve-Path -LiteralPath $WorkbookPath).Path
$runner = Join-Path $resolvedRoot "jobs\run_monthly_build.ps1"
if (-not (Test-Path -LiteralPath $runner -PathType Leaf)) {
    throw "Task runner not found: $runner"
}

$powerShell = Join-Path $env:SystemRoot "System32\WindowsPowerShell\v1.0\powershell.exe"
$arguments = '-NoProfile -NonInteractive -ExecutionPolicy Bypass -File "' + $runner + '" -WorkbookPath "' + $resolvedWorkbook + '" -ProjectRoot "' + $resolvedRoot + '"'
$action = New-ScheduledTaskAction -Execute $powerShell -Argument $arguments
$trigger = New-ScheduledTaskTrigger -Monthly -DaysOfMonth 1 -At ([datetime]::ParseExact($RunAt, "HH:mm", $null))
$settings = New-ScheduledTaskSettingsSet -StartWhenAvailable -ExecutionTimeLimit (New-TimeSpan -Hours 2)
$principal = New-ScheduledTaskPrincipal -UserId ($env:USERDOMAIN + "\" + $env:USERNAME) -LogonType Interactive -RunLevel Limited

Register-ScheduledTask -TaskName $TaskName -Action $action -Trigger $trigger -Settings $settings -Principal $principal -Description "Validates the latest DELFI source workbook and publishes approved Parquet marts. Failed controls quarantine the period." -Force | Out-Null
Write-Host "Registered '$TaskName' to run at $RunAt on the first day of each month."
Write-Host "The task runs the build using the latest reporting month found in the workbook."
