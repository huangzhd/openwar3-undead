$ErrorActionPreference = 'Stop'
$practiceRoot = $PSScriptRoot
$practicePython = Join-Path $practiceRoot '.venv\Scripts\pythonw.exe'
$practiceScript = Join-Path $practiceRoot 'practice_panel.py'
if (!(Test-Path -LiteralPath $practicePython) -or !(Test-Path -LiteralPath $practiceScript)) {
    throw 'Practice panel runtime or source is missing.'
}
$practiceLink = Join-Path ([Environment]::GetFolderPath('DesktopDirectory')) 'dayuan 人机练习.lnk'
$practiceShell = New-Object -ComObject WScript.Shell
$practiceShortcut = $practiceShell.CreateShortcut($practiceLink)
if ((Test-Path -LiteralPath $practiceLink) -and $practiceShortcut.TargetPath -ne $practicePython) {
    throw "Existing shortcut belongs to another application: $practiceLink"
}
$practiceShortcut.TargetPath = $practicePython
$practiceShortcut.Arguments = '-X utf8 -B "' + $practiceScript + '"'
$practiceShortcut.WorkingDirectory = $practiceRoot
$practiceShortcut.Description = '选择地图和种族，开始一局对 dayuan 的本地练习'
$practiceShortcut.WindowStyle = 1
$practiceShortcut.Save()
Write-Output $practiceLink
