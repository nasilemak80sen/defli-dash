param(
    [Parameter(Mandatory = $true)][string]$WorkbookPath,
    [Parameter(Mandatory = $true)][string]$ProjectRoot,
    [string]$TaskName = "DELFI Utilisation Monthly Build",
    [string]$RunAt = "02:00",
    [string]$PythonExe
)

$ErrorActionPreference = "Stop"
$resolvedRoot = (Resolve-Path -LiteralPath $ProjectRoot).Path
$resolvedWorkbook = (Resolve-Path -LiteralPath $WorkbookPath).Path
$runner = Join-Path $resolvedRoot "jobs\run_monthly_build.ps1"
if (-not (Test-Path -LiteralPath $runner -PathType Leaf)) {
    throw "Task runner not found: $runner"
}

if ([string]::IsNullOrWhiteSpace($PythonExe)) {
    $venvPython = Join-Path $resolvedRoot ".venv\Scripts\python.exe"
    $PythonExe = if (Test-Path -LiteralPath $venvPython -PathType Leaf) { $venvPython } else { "python" }
}
if (Test-Path -LiteralPath $PythonExe -PathType Leaf) {
    $resolvedPython = (Resolve-Path -LiteralPath $PythonExe).Path
}
else {
    $pythonCommand = Get-Command $PythonExe -ErrorAction SilentlyContinue
    if (-not $pythonCommand) {
        throw "Python executable was not found: $PythonExe. Activate/create the project virtual environment or pass -PythonExe."
    }
    $resolvedPython = $pythonCommand.Source
}

try {
    $time = [datetime]::ParseExact($RunAt, "HH:mm", [Globalization.CultureInfo]::InvariantCulture)
}
catch {
    throw "RunAt must use 24-hour HH:mm format, for example 02:00."
}

# New-ScheduledTaskTrigger does not define a monthly parameter. Use the
# Task Scheduler COM API (TASK_TRIGGER_MONTHLY = 3) to create a true calendar
# monthly trigger on day 1, all months of the year.
$now = Get-Date
$firstRun = Get-Date -Year $now.Year -Month $now.Month -Day 1 -Hour $time.Hour -Minute $time.Minute -Second 0
if ($firstRun -le $now) {
    $nextMonth = $now.AddMonths(1)
    $firstRun = Get-Date -Year $nextMonth.Year -Month $nextMonth.Month -Day 1 -Hour $time.Hour -Minute $time.Minute -Second 0
}

$powerShell = Join-Path $env:SystemRoot "System32\WindowsPowerShell\v1.0\powershell.exe"
$arguments = '-NoProfile -NonInteractive -ExecutionPolicy Bypass -File "' + $runner + '" -WorkbookPath "' + $resolvedWorkbook + '" -ProjectRoot "' + $resolvedRoot + '" -PythonExe "' + $resolvedPython + '"'

$service = New-Object -ComObject "Schedule.Service"
$service.Connect()
$folder = $service.GetFolder("\")
$definition = $service.NewTask(0)
$definition.RegistrationInfo.Description = "Validates the latest DELFI source workbook and publishes approved Parquet marts. Failed controls quarantine the period."
$definition.Settings.StartWhenAvailable = $true
$definition.Settings.ExecutionTimeLimit = "PT2H"
$definition.Settings.MultipleInstances = 2
$definition.Principal.UserId = [Security.Principal.WindowsIdentity]::GetCurrent().Name
$definition.Principal.LogonType = 3
$definition.Principal.RunLevel = 0

$trigger = $definition.Triggers.Create(3)
$trigger.StartBoundary = $firstRun.ToString("yyyy-MM-dd'T'HH:mm:ss")
$trigger.DaysOfMonth = 1
$trigger.MonthsOfYear = 4095
$trigger.Enabled = $true

$action = $definition.Actions.Create(0)
$action.Path = $powerShell
$action.Arguments = $arguments
$action.WorkingDirectory = $resolvedRoot

# TASK_CREATE_OR_UPDATE = 6; TASK_LOGON_INTERACTIVE_TOKEN = 3.
$null = $folder.RegisterTaskDefinition($TaskName, $definition, 6, $null, $null, 3, $null)

Write-Host "Registered '$TaskName' for day 1 of every month at $RunAt."
Write-Host "Python executable: $resolvedPython"
Write-Host "Workbook: $resolvedWorkbook"
Write-Host "The job uses the latest reporting month found in the workbook."
