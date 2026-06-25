# Contributing

Thanks for improving AirClip. This repository contains both firmware and a
Windows desktop agent, so keep changes scoped to the component they affect.

## Development Setup

Desktop agent:

```powershell
cd desktop-agent
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -e .[dev]
pytest
```

Firmware:

1. Install Arduino IDE or Arduino CLI.
2. Install the ESP32 board package.
3. Install `NimBLE-Arduino`.
4. Open `firmware/airclip_esp32/airclip_esp32.ino` and build for an ESP32 board
   with BLE support.

## Pull Request Guidelines

- Keep generated files, caches, virtual environments, and local logs out of Git.
- Update `README.md` or `docs/` when behavior, setup, or protocol details
  change.
- Add focused tests for desktop-agent protocol, history, and clipboard logic
  when changing those areas.
- Avoid committing private clipboard samples, machine names, tokens, or VPN
  details.
