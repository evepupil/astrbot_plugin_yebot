param(
    [string]$PythonPath = ".venv\Scripts\python.exe"
)

$ErrorActionPreference = "Stop"
$python = Resolve-Path -LiteralPath $PythonPath -ErrorAction Stop

& $python -m pytest
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
& $python -m ruff check .
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
& $python -m ruff format --check .
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
& $python -m mypy yebot --cache-dir .mypy_cache_release --no-incremental
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

Write-Output "YeBot release checks passed."
