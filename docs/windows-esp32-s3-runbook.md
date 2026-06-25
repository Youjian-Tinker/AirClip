# Windows + ESP32-S3-N16R8 Runbook

## Hardware

- Board: ESP32-S3-N16R8.
- Firmware: `firmware/airclip_esp32/airclip_esp32.ino`.
- Arduino library: `NimBLE-Arduino`.

The firmware advertises one BLE peripheral named `AirClip-Relay`. Both Windows
agents try to connect to that same peripheral and subscribe to notifications.

ESP32-S3 can support multiple BLE connections, but Windows Bluetooth adapters
and drivers vary. If the second PC cannot connect while the first PC is already
connected, the fallback design is to keep this protocol and change the desktop
agents to reconnect/poll in turns. The current firmware is still the right first
test because it proves whether the actual hardware path supports simultaneous
connections.

## Desktop Startup

On a new PC, run the installer once from the `desktop-agent` folder:

```powershell
cd D:\AI-Workspace\AirClip\desktop-agent
.\install.cmd
```

The installer creates the runtime, installs dependencies, creates shortcuts,
and launches the agent once. It defaults the device name to the current
computer name.

If you want a manual launch instead:

```powershell
cd D:\AI-Workspace\AirClip\desktop-agent
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
python -m airclip_agent --name pc-a
```

On the second PC, use a different name if you launch manually:

```powershell
cd D:\AI-Workspace\AirClip\desktop-agent
.\.venv\Scripts\Activate.ps1
python -m airclip_agent --name pc-b
```

Use unique names. The name is part of loop prevention.

## Text Formatting

The first version preserves plain text exactly as UTF-8:

- Chinese and other Unicode characters.
- Newlines.
- Indentation.
- Tabs.
- Spaces.

It does not preserve rich text styles such as font family, color, bold, tables,
HTML clipboard formats, or Word-specific formatting.

## Operational Controls

The Windows tray menu supports:

- Enable shared clipboard.
- Pause shared clipboard.
- Clear local history.
- Exit.

The console supports the same controls with:

```text
on
off
history
clear
quit
```

When sharing is paused, incoming remote clipboard text is still recorded in the
local in-memory history, but it is not written to the Windows clipboard.

To remove the local install, run `.\uninstall.cmd` from `desktop-agent`.
