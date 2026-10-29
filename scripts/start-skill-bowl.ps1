param(
    [ValidateRange(1024, 65535)][int]$Port = 8002,
    [switch]$PrepareOnly
)
$ErrorActionPreference = 'Stop'
$Launcher = Join-Path $PSScriptRoot 'start_local.py'
$LauncherArgs = @($Launcher, '--port', "$Port")
if ($PrepareOnly) { $LauncherArgs += '--prepare-only' }
if (Get-Command py -ErrorAction SilentlyContinue) {
    & py -3 @LauncherArgs
} elseif (Get-Command python -ErrorAction SilentlyContinue) {
    & python @LauncherArgs
} else {
    throw 'Install Python 3.12+ first, then retry.'
}
exit $LASTEXITCODE
