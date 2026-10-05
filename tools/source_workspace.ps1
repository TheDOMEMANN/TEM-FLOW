param(
    [ValidateSet('Launch', 'Restart', 'Stop', 'Check', 'Inspect')]
    [string]$Action = 'Launch',
    [switch]$NoBrowser
)
$ErrorActionPreference = 'Stop'
$sourceRoot = Split-Path -Parent $PSScriptRoot
$sourceParent = Split-Path -Parent $sourceRoot
$versionFile = Join-Path $sourceRoot 'src\temflow\_version.py'
$versionMatch = [regex]::Match((Get-Content -LiteralPath $versionFile -Raw), 'VERSION\s*=\s*["'']([^"'']+)')
if (-not $versionMatch.Success) { throw 'Cannot read the software version.' }
$sourceVersion = $versionMatch.Groups[1].Value
$runtimeCandidates = @(
    (Join-Path $sourceParent 'Desktop\runtime\python.exe'),
    (Join-Path $sourceRoot '.venv\Scripts\python.exe'),
    (Join-Path $sourceRoot 'runtime\python.exe'),
    (Join-Path $sourceParent "TEM-FLOW-$sourceVersion-Structural\runtime\python.exe"),
    (Join-Path $sourceParent "TEM-FLOW-$sourceVersion-Desktop\runtime\python.exe")
)
$chosenPython = $null
foreach ($candidate in $runtimeCandidates) {
    if (Test-Path -LiteralPath $candidate -PathType Leaf) { $chosenPython = $candidate; break }
}
if (-not $chosenPython) {
    $normalPython = Get-Command python -ErrorAction SilentlyContinue
    if ($normalPython -and $normalPython.Source -notlike '*WindowsApps*') { $chosenPython = $normalPython.Source }
}
if (-not $chosenPython) { throw 'Python was not found. Read EDITABLE_SOURCE_START_HERE.html for setup instructions.' }
Push-Location -LiteralPath $sourceRoot
try {
    & $chosenPython -B -c 'import sys, numpy, scipy; assert sys.version_info >= (3,10)'
    if ($LASTEXITCODE -ne 0) { throw 'Python needs NumPy and SciPy. Follow the setup section in the guide.' }
    if ($Action -eq 'Inspect') {
        Write-Output "Editable source: $sourceRoot"
        Write-Output "Python runtime: $chosenPython"
        exit 0
    }
    if ($Action -eq 'Check') {
        & $chosenPython -B (Join-Path $sourceRoot 'tools\check.py')
    } else {
        $launchArguments = @('-B', (Join-Path $sourceRoot 'desktop_launcher.py'), '--port', '8810')
        if ($Action -eq 'Restart') { $launchArguments += '--restart' }
        if ($Action -eq 'Stop') { $launchArguments += '--stop' }
        if ($NoBrowser) { $launchArguments += '--no-browser' }
        & $chosenPython @launchArguments
    }
    exit $LASTEXITCODE
} finally {
    Pop-Location
}
