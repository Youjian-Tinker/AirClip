# AirClip BLE Protocol

## BLE GATT

Service UUID:

```text
7b1f0001-8f5d-4d3a-9f4c-1d76b8f0a901
```

Characteristics:

```text
RX write:   7b1f0002-8f5d-4d3a-9f4c-1d76b8f0a901
TX notify:  7b1f0003-8f5d-4d3a-9f4c-1d76b8f0a901
```

Desktop agents write newline-terminated UTF-8 JSON frames to RX. The ESP32
relays each frame to all subscribed TX clients. Receivers ignore frames from
their own `source`.

## Frame

Each BLE write contains one JSON object plus a trailing newline. The desktop
agent keeps frames below the configured chunk size so the firmware does not need
to understand the message body.

Clipboard text is encoded as UTF-8 and sent as multiple chunk frames. This
preserves plain-text formatting including newlines, indentation, tabs, and
Unicode characters.

```json
{
  "v": 1,
  "type": "clip",
  "source": "pc-a",
  "message_id": "uuid",
  "created_ms": 1790000000000,
  "hash": "sha256 hex",
  "index": 0,
  "total": 3,
  "data": "base64 text chunk"
}
```

Optional control frame:

```json
{
  "v": 1,
  "type": "hello",
  "source": "pc-a",
  "created_ms": 1790000000000
}
```

## Receiver Rules

1. Drop frames whose `source` equals the local device name.
2. Drop clipboard messages whose `hash` was already applied recently.
3. Reassemble chunks by `message_id`.
4. Decode the joined Base64 payload as UTF-8.
5. Add the text to the local history queue and persist it locally for the viewer.
6. Write the text to the local system clipboard only when sharing is enabled.
7. Keep at most 50 history entries and evict the oldest entry when the cap is
   exceeded.
8. Expose the recent queue through the tray "view history" command.

## Loop Prevention

Applying a remote clipboard update changes the local system clipboard, which the
local polling loop will see. The agent records the applied content hash and does
not retransmit that hash. This prevents A -> B -> A echo loops.
