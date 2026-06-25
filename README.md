# AirClip

AirClip is a Bluetooth Low Energy clipboard bridge for trusted Windows machines
that cannot share a normal network path. It uses an ESP32 as a small relay and a
Python desktop agent on each PC.

The intended topology is:

```text
Windows PC A <-> BLE <-> ESP32 relay <-> BLE <-> Windows PC B
```

The ESP32 firmware is intentionally a small BLE relay. Clipboard history,
deduplication, enable/disable controls, and loop prevention live in the desktop
agent.

## Features

- ESP32 relay firmware built with Arduino and `NimBLE-Arduino`.
- Windows-oriented Python desktop agent with console and tray controls.
- Bidirectional text clipboard synchronization while preserving plain-text
  formatting such as line breaks, indentation, tabs, and Unicode characters.
- Local clipboard history capped at 50 entries by default.
- Runtime enable/disable control from the desktop tray menu or agent console.
- Chunked BLE protocol so clipboard text can exceed a single packet.

Images, files, and rich text styles from Word or browsers are deliberately out
of scope for the first version because they are large, privacy-sensitive, and
unreliable over a low-bandwidth Bluetooth link.

## Repository Layout

```text
desktop-agent/                 Python desktop clipboard agent
desktop-agent/airclip_agent/   Agent source code
desktop-agent/tests/           Desktop agent tests
firmware/airclip_esp32/        Arduino firmware for the ESP32 relay
docs/architecture.md           Component overview
docs/protocol.md               BLE service and message protocol
docs/windows-esp32-s3-runbook.md
```

## Requirements

- Windows 10 or later for the desktop agent.
- Python 3.11 or later.
- An ESP32 board with BLE support. ESP32-S3-N16R8 is the primary tested target.
- Arduino ESP32 board package.
- `NimBLE-Arduino` library.

## Quick Start

### 1. Flash the ESP32 Relay

1. Install the Arduino ESP32 board package.
2. Install the `NimBLE-Arduino` library.
3. Open `firmware/airclip_esp32/airclip_esp32.ino` in Arduino IDE.
4. Select an ESP32-S3 board profile that matches ESP32-S3-N16R8 and upload.

The device advertises as `AirClip-Relay`.

### 2. Install the Desktop Agent

The easiest path on a new Windows PC is the installer:

```powershell
cd desktop-agent
.\install.cmd
```

The installer creates the local virtual environment, installs dependencies,
adds shortcuts that launch `AirClipAgent.exe`, optionally enables startup
launch, and starts the agent once after installation.

If you want a manual run instead:

```powershell
cd desktop-agent
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -e .
python -m airclip_agent --name pc-a
```

Console commands while running:

- `on` enables sharing.
- `off` disables sharing.
- `history` prints the recent text clipboard entries.
- `clear` clears the local history.
- `quit` exits.

The tray icon exposes the same enable, pause, clear-history, and exit controls.
Use `--no-tray` when running in a console-only environment.
Use `--no-console` when launching from a shortcut or startup entry.
The tray menu also has a `查看历史` item that opens the recent clipboard queue.

## Development

Install development dependencies and run tests:

```powershell
cd desktop-agent
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -e .[dev]
pytest
```

The Python package metadata lives in `desktop-agent/pyproject.toml`. The legacy
`requirements.txt` is kept for the Windows installer and simple manual installs.

## Documentation

- [Architecture](docs/architecture.md)
- [BLE protocol](docs/protocol.md)
- [Windows and ESP32-S3 runbook](docs/windows-esp32-s3-runbook.md)

## Uninstall

To remove the desktop agent:

```powershell
cd desktop-agent
.\uninstall.cmd
```

## Security Notes

- Keep the two computer names unique. They are used to prevent clipboard echo
  loops.
- The current implementation does not persist clipboard history to disk, so
  sensitive clipboard contents are not written by default.
- Treat clipboard data as sensitive. Avoid syncing passwords, tokens, private
  keys, production credentials, or data from untrusted machines.
- ESP32-S3-N16R8 has enough memory for this relay design. If the host BLE stack
  cannot maintain two simultaneous connections in practice, the firmware can
  still be reused, but the connection strategy will need to change to a polling
  or reconnect model.

## License

AirClip is released under the [MIT License](LICENSE).
