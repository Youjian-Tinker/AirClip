param(
    [string]$Name = $env:COMPUTERNAME,
    [string]$RelayName = "AirClip-Relay",
    [string]$InstallDir = "$env:LOCALAPPDATA\AirClip",
    [switch]$NoStartup,
    [switch]$NoLaunch
)

$ErrorActionPreference = "Stop"

# Prefer the launcher that is already installed on the machine.
function Find-Python {
    $py = Get-Command py.exe -ErrorAction SilentlyContinue
    if ($py) {
        return @($py.Source, "-3")
    }

    $python = Get-Command python.exe -ErrorAction SilentlyContinue
    if ($python) {
        return @($python.Source)
    }

    throw "Python was not found. Install Python 3.11+ from python.org or Microsoft Store, then run install.cmd again."
}

# Create a Windows shortcut without depending on external tools.
function New-Shortcut {
    param(
        [string]$Path,
        [string]$TargetPath,
        [string]$Arguments,
        [string]$WorkingDirectory,
        [string]$Description,
        [string]$IconLocation
    )

    $shell = New-Object -ComObject WScript.Shell
    $shortcut = $shell.CreateShortcut($Path)
    $shortcut.TargetPath = $TargetPath
    $shortcut.Arguments = $Arguments
    $shortcut.WorkingDirectory = $WorkingDirectory
    $shortcut.Description = $Description
    if ($IconLocation) {
        $shortcut.IconLocation = $IconLocation
    }
    $shortcut.Save()
}

$sourceDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$venvDir = Join-Path $InstallDir ".venv"
$pythonSpec = Find-Python
$launcher = $pythonSpec[0]
$launcherArgs = @()
if ($pythonSpec.Count -gt 1) {
    $launcherArgs = $pythonSpec[1..($pythonSpec.Count - 1)]
}

# Stop old background agents before copying files so the installed code really updates.
Get-Process -ErrorAction SilentlyContinue | Where-Object {
    $_.Path -and $_.Path.StartsWith($InstallDir, [System.StringComparison]::OrdinalIgnoreCase)
} | Stop-Process -Force

Write-Host "Installing AirClip to $InstallDir"
New-Item -ItemType Directory -Force -Path $InstallDir | Out-Null
Copy-Item -Path (Join-Path $sourceDir "airclip_agent") -Destination $InstallDir -Recurse -Force
Copy-Item -Path (Join-Path $sourceDir "requirements.txt") -Destination $InstallDir -Force

Write-Host "Creating Python virtual environment"
& $launcher @launcherArgs -m venv $venvDir
if ($LASTEXITCODE -ne 0) {
    throw "Failed to create the Python virtual environment."
}

$venvPython = Join-Path $venvDir "Scripts\python.exe"
$venvPythonw = Join-Path $venvDir "Scripts\pythonw.exe"
$agentExe = Join-Path $venvDir "Scripts\AirClipAgent.exe"
Write-Host "Installing Python dependencies"
& $venvPython -m pip install --upgrade pip
if ($LASTEXITCODE -ne 0) {
    throw "Failed to upgrade pip."
}
& $venvPython -m pip install -r (Join-Path $InstallDir "requirements.txt")
if ($LASTEXITCODE -ne 0) {
    throw "Failed to install AirClip dependencies."
}

$escapedName = $Name.Replace('"', '\"')
$escapedRelayName = $RelayName.Replace('"', '\"')
$agentArgs = "-m airclip_agent --name `"$escapedName`" --relay-name `"$escapedRelayName`" --no-console"
$iconPath = Join-Path $InstallDir "airclip_agent\assets\airclip-icon.ico"
# Copying pythonw.exe keeps the virtual environment binding while giving Task Manager a clear process name.
Copy-Item -LiteralPath $venvPythonw -Destination $agentExe -Force

$desktopShortcut = Join-Path ([Environment]::GetFolderPath("Desktop")) "AirClip Agent.lnk"
$programsDir = Join-Path ([Environment]::GetFolderPath("Programs")) "AirClip"
$startupShortcut = Join-Path ([Environment]::GetFolderPath("Startup")) "AirClip Agent.lnk"
New-Item -ItemType Directory -Force -Path $programsDir | Out-Null

# Place shortcuts in the common places a Windows user expects to launch or manage the app.
New-Shortcut -Path $desktopShortcut -TargetPath $agentExe -Arguments $agentArgs -WorkingDirectory $InstallDir -Description "Start AirClip clipboard agent" -IconLocation $iconPath
New-Shortcut -Path (Join-Path $programsDir "AirClip Agent.lnk") -TargetPath $agentExe -Arguments $agentArgs -WorkingDirectory $InstallDir -Description "Start AirClip clipboard agent" -IconLocation $iconPath
if (-not $NoStartup) {
    New-Shortcut -Path $startupShortcut -TargetPath $agentExe -Arguments $agentArgs -WorkingDirectory $InstallDir -Description "Start AirClip clipboard agent at sign-in" -IconLocation $iconPath
}

if (-not $NoLaunch) {
    Write-Host "Starting AirClip"
    Start-Process -FilePath $agentExe -ArgumentList $agentArgs -WorkingDirectory $InstallDir -WindowStyle Hidden
}

Write-Host "Installed. Device name: $Name. Relay name: $RelayName."
