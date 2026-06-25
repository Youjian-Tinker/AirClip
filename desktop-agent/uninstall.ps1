param(
    [string]$InstallDir = "$env:LOCALAPPDATA\AirClip"
)

$ErrorActionPreference = "Stop"

# Remove the shortcuts that the installer creates.
$shortcutPaths = @(
    (Join-Path ([Environment]::GetFolderPath("Desktop")) "AirClip Agent.lnk"),
    (Join-Path ([Environment]::GetFolderPath("Programs")) "AirClip\AirClip Agent.lnk"),
    (Join-Path ([Environment]::GetFolderPath("Startup")) "AirClip Agent.lnk")
)

foreach ($path in $shortcutPaths) {
    if (Test-Path -LiteralPath $path) {
        Remove-Item -LiteralPath $path -Force
    }
}

# Clean up empty Start Menu folders left behind after shortcut removal.
$programsDir = Join-Path ([Environment]::GetFolderPath("Programs")) "AirClip"
if ((Test-Path -LiteralPath $programsDir) -and -not (Get-ChildItem -LiteralPath $programsDir -Force)) {
    Remove-Item -LiteralPath $programsDir -Force
}

if (Test-Path -LiteralPath $InstallDir) {
    Remove-Item -LiteralPath $InstallDir -Recurse -Force
}

Write-Host "Removed AirClip shortcuts and install directory."
