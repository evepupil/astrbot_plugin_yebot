param(
    [string]$Distro = "Ubuntu-24.04",
    [string]$Target = "/home/ubuntu/code/qq-ai-bot/data/plugins/astrbot_plugin_yebot",
    [switch]$Restart
)

$ErrorActionPreference = "Stop"
$source = (Resolve-Path -LiteralPath (Join-Path $PSScriptRoot "..")).Path
if ($Target -notmatch '^/home/ubuntu/code/qq-ai-bot/data/plugins/astrbot_plugin_yebot$') {
    throw "Target is restricted to the YeBot plugin directory."
}

$sourceRelative = $source.Substring(3).Replace('\', '/')
$sourceLinux = "/mnt/c/$sourceRelative"
$excluded = @(
    "--exclude=.git",
    "--exclude=.venv",
    "--exclude=.mypy_cache*",
    "--exclude=.pytest_cache",
    "--exclude=.ruff_cache",
    "--exclude=__pycache__"
)
& wsl.exe -d $Distro -- sudo -n rsync -a @excluded "$sourceLinux/" "$Target/"
if ($LASTEXITCODE -ne 0) { throw "WSL rsync failed with exit code $LASTEXITCODE." }

if ($Restart) {
    & wsl.exe -d $Distro -- bash -lc "cd /home/ubuntu/code/qq-ai-bot && docker compose restart astrbot"
    if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
}

Write-Output "YeBot plugin synchronized to ${Distro}:${Target}"
