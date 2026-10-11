$ErrorActionPreference = 'Stop'
$consoleRoot = $PSScriptRoot
$consolePython = Join-Path $consoleRoot '.venv\Scripts\pythonw.exe'
$consoleScript = Join-Path $consoleRoot 'bot_console.py'
if (!(Test-Path -LiteralPath $consolePython) -or !(Test-Path -LiteralPath $consoleScript)) {
    throw 'Console runtime or source is missing.'
}
$consoleShell = New-Object -ComObject WScript.Shell
$consoleLinks = @(
    (Join-Path ([Environment]::GetFolderPath('Startup')) 'OpenWar3AI Console.lnk'),
    (Join-Path ([Environment]::GetFolderPath('DesktopDirectory')) 'OpenWar3AI Console.lnk')
)
foreach ($consoleLink in $consoleLinks) {
    $consoleShortcut = $consoleShell.CreateShortcut($consoleLink)
    if ((Test-Path -LiteralPath $consoleLink) -and $consoleShortcut.TargetPath -ne $consolePython) {
        throw "Existing shortcut belongs to another application: $consoleLink"
    }
    $consoleShortcut.TargetPath = $consolePython
    $consoleShortcut.Arguments = '-B "' + $consoleScript + '"'
    $consoleShortcut.WorkingDirectory = $consoleRoot
    $consoleShortcut.Description = 'OpenWar3AI status and pause/resume console'
    $consoleShortcut.WindowStyle = 1
    $consoleShortcut.Save()
}
$consoleLinks | ConvertTo-Json | Set-Content -LiteralPath (Join-Path $consoleRoot 'artifacts\console-shortcuts.json') -Encoding utf8
# The user requested a visible control window. pythonw avoids an extra terminal.
Start-Process -FilePath $consolePython -ArgumentList ('-B "' + $consoleScript + '"') -WorkingDirectory $consoleRoot
