param(
    [int]$IntervalMs = 50,
    [int]$QuietMs = 1000,
    [string]$LogPath = ""
)

Add-Type -TypeDefinition @"
using System;
using System.Runtime.InteropServices;
using System.Text;

public static class ClipboardNative {
    [DllImport("user32.dll", SetLastError = true)]
    public static extern bool OpenClipboard(IntPtr hWndNewOwner);

    [DllImport("user32.dll", SetLastError = true)]
    public static extern bool CloseClipboard();

    [DllImport("user32.dll", SetLastError = true)]
    public static extern IntPtr GetOpenClipboardWindow();

    [DllImport("user32.dll", SetLastError = true)]
    public static extern IntPtr GetClipboardOwner();

    [DllImport("user32.dll", SetLastError = true)]
    public static extern uint GetWindowThreadProcessId(IntPtr hWnd, out uint lpdwProcessId);

    [DllImport("user32.dll", CharSet = CharSet.Unicode, SetLastError = true)]
    public static extern int GetWindowText(IntPtr hWnd, StringBuilder lpString, int nMaxCount);
}
"@

function Get-WindowProcessInfo {
    param([IntPtr]$Handle)

    if ($Handle -eq [IntPtr]::Zero) {
        return [pscustomobject]@{
            Hwnd = "0x0"
            Pid = $null
            ProcessName = ""
            Path = ""
            Title = ""
        }
    }

    $pidValue = [uint32]0
    [void][ClipboardNative]::GetWindowThreadProcessId($Handle, [ref]$pidValue)

    $processName = ""
    $processPath = ""
    if ($pidValue -gt 0) {
        try {
            $process = Get-Process -Id ([int]$pidValue) -ErrorAction Stop
            $processName = $process.ProcessName
            try {
                $processPath = $process.Path
            } catch {
                $processPath = ""
            }
        } catch {
            $processName = "<exited>"
        }
    }

    $titleBuilder = [Text.StringBuilder]::new(512)
    [void][ClipboardNative]::GetWindowText($Handle, $titleBuilder, $titleBuilder.Capacity)

    [pscustomobject]@{
        Hwnd = ("0x{0:X}" -f $Handle.ToInt64())
        Pid = if ($pidValue -gt 0) { [int]$pidValue } else { $null }
        ProcessName = $processName
        Path = $processPath
        Title = $titleBuilder.ToString()
    }
}

function Write-LockEvent {
    param(
        [string]$State,
        [object]$Info,
        [int]$Win32Error
    )

    $line = "{0:yyyy-MM-dd HH:mm:ss.fff} {1} hwnd={2} pid={3} process={4} title=""{5}"" path=""{6}"" win32={7}" -f `
        (Get-Date),
        $State,
        $Info.Hwnd,
        $Info.Pid,
        $Info.ProcessName,
        ($Info.Title -replace '"', '""'),
        ($Info.Path -replace '"', '""'),
        $Win32Error

    Write-Host $line
    if ($LogPath) {
        Add-Content -Path $LogPath -Value $line -Encoding utf8
    }
}

Write-Host "Watching clipboard locks. Press Ctrl+C to stop."
Write-Host "IntervalMs=$IntervalMs QuietMs=$QuietMs LogPath=$LogPath"

$lastKey = ""
$lastPrintedAt = Get-Date "2000-01-01"

while ($true) {
    $opened = [ClipboardNative]::OpenClipboard([IntPtr]::Zero)
    if ($opened) {
        [void][ClipboardNative]::CloseClipboard()
        $lastKey = ""
        Start-Sleep -Milliseconds $IntervalMs
        continue
    }

    $errorCode = [Runtime.InteropServices.Marshal]::GetLastWin32Error()
    $openWindow = [ClipboardNative]::GetOpenClipboardWindow()
    $info = Get-WindowProcessInfo -Handle $openWindow
    if ($info.Pid -eq $null) {
        $ownerWindow = [ClipboardNative]::GetClipboardOwner()
        $info = Get-WindowProcessInfo -Handle $ownerWindow
    }

    $key = "{0}|{1}|{2}" -f $info.Hwnd, $info.Pid, $errorCode
    $now = Get-Date
    if ($key -ne $lastKey -or (($now - $lastPrintedAt).TotalMilliseconds -ge $QuietMs)) {
        Write-LockEvent -State "LOCKED" -Info $info -Win32Error $errorCode
        $lastKey = $key
        $lastPrintedAt = $now
    }

    Start-Sleep -Milliseconds $IntervalMs
}
