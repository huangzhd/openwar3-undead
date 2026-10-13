$ErrorActionPreference = 'Stop'
$taskPython = Join-Path $PSScriptRoot '.venv\Scripts\python.exe'
if (-not (Test-Path -LiteralPath $taskPython)) { throw 'Missing project .venv; follow README environment setup first.' }
& $taskPython -B (Join-Path $PSScriptRoot 'machine_start.py') --machine upstream @args
exit $LASTEXITCODE
