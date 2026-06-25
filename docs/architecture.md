# Architecture

AirClip is split into three deliberately small layers:

```text
Windows desktop agent A
        |
        | BLE GATT frames
        v
ESP32 relay firmware
        |
        | BLE GATT frames
        v
Windows desktop agent B
```

## Components

### Desktop Agent

Location: `desktop-agent/airclip_agent/`

Responsibilities:

- poll the local text clipboard;
- encode clipboard updates into chunked protocol frames;
- send and receive frames over BLE;
- deduplicate locally seen clipboard hashes;
- maintain a capped local history queue;
- expose console and tray controls.

### ESP32 Firmware

Location: `firmware/airclip_esp32/`

Responsibilities:

- advertise the AirClip BLE service;
- accept writes from desktop agents;
- relay frames to subscribed clients;
- avoid parsing clipboard payload semantics.

### Documentation

Location: `docs/`

- `protocol.md` describes the BLE service and message flow.
- `windows-esp32-s3-runbook.md` captures setup and operational steps for a
  Windows plus ESP32-S3 deployment.

## Design Constraints

- Plain text is the first supported clipboard format.
- Rich text, files, images, and browser-specific clipboard formats are out of
  scope for the initial relay.
- The ESP32 stays protocol-light so behavior can evolve mostly in Python.
- Clipboard history is local to each desktop agent.
