$ErrorActionPreference = 'Stop'
$spectatorRoot = $PSScriptRoot
$spectatorPython = Join-Path $spectatorRoot '.venv\Scripts\pythonw.exe'
$spectatorScript = Join-Path $spectatorRoot 'sparring_panel.py'
if (!(Test-Path -LiteralPath $spectatorPython) -or !(Test-Path -LiteralPath $spectatorScript)) {
    throw 'Spectator panel runtime or source is missing.'
}
$spectatorLink = Join-Path ([Environment]::GetFolderPath('DesktopDirectory')) 'dayuan 训练观战.lnk'
$spectatorShell = New-Object -ComObject WScript.Shell
$spectatorShortcut = $spectatorShell.CreateShortcut($spectatorLink)
if ((Test-Path -LiteralPath $spectatorLink) -and ($spectatorShortcut.TargetPath -ne $spectatorPython -or $spectatorShortcut.Arguments -notlike '*sparring_panel.py*')) {
    throw "Existing shortcut belongs to another application: $spectatorLink"
}
$spectatorShortcut.TargetPath = $spectatorPython
$spectatorShortcut.Arguments = '-X utf8 -B "' + $spectatorScript + '"'
$spectatorShortcut.WorkingDirectory = $spectatorRoot
$spectatorShortcut.Description = '查看 dayuan 陪练状态，调节观战视距和游戏速度'
$spectatorShortcut.WindowStyle = 1
$spectatorShortcut.Save()
Write-Output $spectatorLink
