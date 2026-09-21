param([string]$Distro = 'Ubuntu-24.04')
$ErrorActionPreference = 'Stop'
$linuxScript = (& wsl -d $Distro -- wslpath -a (Join-Path $PSScriptRoot 'Allrun')).Trim()
if ($LASTEXITCODE -ne 0) { throw 'Cannot locate the reference scripts in WSL.' }
& wsl -d $Distro -- bash $linuxScript
if ($LASTEXITCODE -ne 0) { throw 'Reference did not pass. Inspect the preserved run logs; do not label it validated.' }
