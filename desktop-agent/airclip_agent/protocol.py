"""Message framing helpers for the AirClip BLE relay protocol."""

from __future__ import annotations

import hashlib
import json
import math
import struct
import time
import uuid
import zlib
from dataclasses import dataclass
from enum import IntEnum

PROTOCOL_VERSION = 3
LEGACY_PROTOCOL_VERSION = 1
DEFAULT_FRAME_DATA_BYTES = 200
MAX_FRAME_DATA_BYTES = 200
MAX_BLE_FRAME_BYTES = 240
MAX_SOURCE_BYTES = 32
MESSAGE_ID_BYTES = 16
TEXT_HASH_BYTES = 32
CHUNK_HEADER = struct.Struct("<2sBB16s16sHH")
META_HEADER = struct.Struct("<HIQ32s")
ACK_HEADER = struct.Struct("<2sBB16s16sI")
NACK_FIXED_HEADER = struct.Struct("<2sBB16s16sH")
MAGIC = b"AC"


class FrameKind(IntEnum):
    """Binary frame kinds exchanged through the BLE relay."""

    CLIP_CHUNK = 1
    CLIP_ACK = 2
    CLIP_NACK = 3
    HELLO = 4


@dataclass(frozen=True)
class ClipboardMessage:
    """Represents a fully reassembled clipboard message."""

    source: str
    message_id: str
    created_ms: int
    text_hash: str
    text: str


@dataclass(frozen=True)
class BinaryClipChunk:
    """One compressed binary clipboard chunk."""

    sender_id: str
    source: str
    message_id: str
    created_ms: int
    text_hash: str
    index: int
    total: int
    original_size: int
    payload: bytes


@dataclass(frozen=True)
class ClipAck:
    """Acknowledges that a full clipboard message was reassembled."""

    sender_id: str
    message_id: str
    total: int


@dataclass(frozen=True)
class ClipNack:
    """Requests retransmission for missing chunks in one clipboard message."""

    sender_id: str
    message_id: str
    missing_indexes: tuple[int, ...]


@dataclass
class PendingChunks:
    """Tracks chunks for one message until every part has arrived."""

    source: str
    message_id: str
    created_ms: int
    text_hash: str
    total: int
    original_size: int
    metadata_ready: bool
    chunks: dict[int, bytes]


class ProtocolError(ValueError):
    """Raised when an incoming frame is malformed or unsupported."""


def now_ms() -> int:
    """Return wall-clock milliseconds for protocol timestamps."""

    return int(time.time() * 1000)


def text_hash(text: str) -> str:
    """Hash clipboard text for deduplication without storing extra copies."""

    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def build_hello_frame(source: str, sender_id: str | None = None) -> bytes:
    """Build a compact binary presence frame sent after BLE connects."""

    source_bytes = source.encode("utf-8")[:220]
    sender = _uuid_bytes(sender_id) if sender_id is not None else bytes(MESSAGE_ID_BYTES)
    return MAGIC + bytes([PROTOCOL_VERSION, FrameKind.HELLO]) + sender + source_bytes


def build_clip_frames(
    source: str,
    text: str,
    data_bytes_per_frame: int = DEFAULT_FRAME_DATA_BYTES,
    sender_id: str | None = None,
) -> list[bytes]:
    """Compress clipboard text and split it into MTU-safe binary frames."""

    if data_bytes_per_frame <= 0:
        raise ValueError("data_bytes_per_frame must be positive")
    raw = text.encode("utf-8")
    compressed = zlib.compress(raw, level=6)
    source_bytes = source.encode("utf-8")[:MAX_SOURCE_BYTES]
    frame_data_bytes = min(data_bytes_per_frame, MAX_BLE_FRAME_BYTES - CHUNK_HEADER.size)
    if frame_data_bytes <= 0:
        raise ValueError("frame header leaves no room for clipboard payload")
    if frame_data_bytes > MAX_FRAME_DATA_BYTES:
        raise ValueError(f"data_bytes_per_frame must be <= {MAX_FRAME_DATA_BYTES}")

    digest = hashlib.sha256(raw).digest()
    created = now_ms()
    metadata = META_HEADER.pack(len(source_bytes), len(raw), created, digest) + source_bytes
    first_data_bytes = frame_data_bytes - len(metadata)
    if first_data_bytes <= 0:
        raise ValueError("source name leaves no room for first clipboard payload")

    chunks = [compressed[:first_data_bytes]]
    chunks.extend(
        compressed[index : index + frame_data_bytes]
        for index in range(first_data_bytes, len(compressed), frame_data_bytes)
    )
    if not chunks:
        chunks = [b""]
    total = len(chunks)
    if total > 65535:
        raise ValueError("clipboard payload is too large for one BLE message")

    message_id = uuid.uuid4().bytes
    sender = _uuid_bytes(sender_id) if sender_id is not None else bytes(MESSAGE_ID_BYTES)
    frames: list[bytes] = []
    for index, chunk in enumerate(chunks):
        header = CHUNK_HEADER.pack(
            MAGIC,
            PROTOCOL_VERSION,
            FrameKind.CLIP_CHUNK,
            sender,
            message_id,
            index,
            total,
        )
        frames.append(header + (metadata if index == 0 else b"") + chunk)
    return frames


def build_ack_frame(message_id: str, total: int, sender_id: str | None = None) -> bytes:
    """Build an ACK after a full clipboard message passes hash validation."""

    sender = _uuid_bytes(sender_id) if sender_id is not None else bytes(MESSAGE_ID_BYTES)
    return ACK_HEADER.pack(MAGIC, PROTOCOL_VERSION, FrameKind.CLIP_ACK, sender, _uuid_bytes(message_id), total)


def build_nack_frame(
    message_id: str,
    missing_indexes: list[int] | tuple[int, ...],
    sender_id: str | None = None,
) -> bytes:
    """Build a retransmission request for missing chunk indexes."""

    indexes = tuple(sorted(set(missing_indexes)))
    if len(indexes) > 100:
        indexes = indexes[:100]
    if any(index < 0 or index > 0xFFFFFFFF for index in indexes):
        raise ValueError("missing chunk index out of range")
    sender = _uuid_bytes(sender_id) if sender_id is not None else bytes(MESSAGE_ID_BYTES)
    payload = b"".join(struct.pack("<I", index) for index in indexes)
    return NACK_FIXED_HEADER.pack(
        MAGIC,
        PROTOCOL_VERSION,
        FrameKind.CLIP_NACK,
        sender,
        _uuid_bytes(message_id),
        len(indexes),
    ) + payload


def parse_binary_frame(data: bytes) -> BinaryClipChunk | ClipAck | ClipNack | None:
    """Parse one BLE notification/write payload into a protocol object."""

    if len(data) < 4 or data[:2] != MAGIC:
        return None

    version = data[2]
    kind = data[3]
    if version != PROTOCOL_VERSION:
        raise ProtocolError(f"unsupported binary protocol version: {version}")

    if kind == FrameKind.HELLO:
        return None
    if kind == FrameKind.CLIP_CHUNK:
        return _parse_clip_chunk(data)
    if kind == FrameKind.CLIP_ACK:
        return _parse_ack(data)
    if kind == FrameKind.CLIP_NACK:
        return _parse_nack(data)
    raise ProtocolError(f"unsupported binary frame kind: {kind}")


def accept_binary_clip_chunk(
    chunk: BinaryClipChunk,
    pending: dict[str, PendingChunks],
) -> ClipboardMessage | None:
    """Store one chunk and decode the clipboard once every chunk arrives."""

    if chunk.total <= 0 or chunk.index < 0 or chunk.index >= chunk.total:
        raise ProtocolError("invalid chunk index")

    existing = pending.get(chunk.message_id)
    if existing is None:
        existing = PendingChunks(
            source=chunk.source,
            message_id=chunk.message_id,
            created_ms=chunk.created_ms,
            text_hash=chunk.text_hash,
            total=chunk.total,
            original_size=chunk.original_size,
            metadata_ready=chunk.index == 0,
            chunks={},
        )
        pending[chunk.message_id] = existing

    if (
        existing.total != chunk.total
        or (chunk.index == 0 and existing.source and existing.source != chunk.source)
        or (chunk.index == 0 and existing.text_hash and existing.text_hash != chunk.text_hash)
    ):
        raise ProtocolError("conflicting chunks for message")

    if chunk.index == 0 and not existing.metadata_ready:
        existing.source = chunk.source
        existing.created_ms = chunk.created_ms
        existing.text_hash = chunk.text_hash
        existing.original_size = chunk.original_size
        existing.metadata_ready = True

    existing.chunks[chunk.index] = chunk.payload
    if len(existing.chunks) != existing.total or not existing.metadata_ready:
        return None

    del pending[chunk.message_id]
    return _decode_binary_message(existing)


def missing_chunk_indexes(chunks: PendingChunks) -> list[int]:
    """Return chunk indexes that have not arrived yet."""

    return [index for index in range(chunks.total) if index not in chunks.chunks]


def transfer_stats(text: str, data_bytes_per_frame: int = DEFAULT_FRAME_DATA_BYTES) -> tuple[int, int, int]:
    """Return raw bytes, compressed bytes, and frame count for diagnostics."""

    raw = text.encode("utf-8")
    compressed = zlib.compress(raw, level=6)
    return len(raw), len(compressed), max(1, math.ceil(len(compressed) / data_bytes_per_frame))


def parse_json_frames(buffer: bytearray, incoming: bytes) -> list[dict]:
    """Append legacy JSON bytes to a buffer and return complete JSON frames."""

    buffer.extend(incoming)
    frames: list[dict] = []

    while b"\n" in buffer:
        line, _, rest = buffer.partition(b"\n")
        buffer[:] = rest
        if not line:
            continue
        try:
            decoded = json.loads(line.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise ProtocolError(f"invalid JSON frame: {exc}") from exc
        frames.append(decoded)

    return frames


def accept_clip_frame(frame: dict, pending: dict[str, PendingChunks]) -> ClipboardMessage | None:
    """Validate a legacy JSON clip frame and return a message when complete."""

    raise ProtocolError("legacy JSON clipboard frames are no longer supported")


def prune_pending(pending: dict[str, PendingChunks], max_age_ms: int = 30000) -> None:
    """Drop stale partial messages so one bad sender cannot grow memory forever."""

    cutoff = now_ms() - max_age_ms
    stale_ids = [
        message_id
        for message_id, chunks in pending.items()
        if chunks.created_ms < cutoff
    ]
    for message_id in stale_ids:
        del pending[message_id]


def _parse_clip_chunk(data: bytes) -> BinaryClipChunk:
    """Decode a binary clipboard chunk and validate its internal lengths."""

    if len(data) < CHUNK_HEADER.size:
        raise ProtocolError("binary clip chunk is too short")
    (
        _magic,
        _version,
        _kind,
        sender_id,
        message_id,
        index,
        total,
    ) = CHUNK_HEADER.unpack_from(data)

    payload_start = CHUNK_HEADER.size
    source = ""
    original_size = 0
    created_ms = 0
    digest = b""
    if index == 0:
        if len(data) < CHUNK_HEADER.size + META_HEADER.size:
            raise ProtocolError("first binary chunk is missing metadata")
        source_len, original_size, created_ms, digest = META_HEADER.unpack_from(data, CHUNK_HEADER.size)
        source_start = CHUNK_HEADER.size + META_HEADER.size
        source_end = source_start + source_len
        if source_end > len(data):
            raise ProtocolError("binary clip source exceeds frame length")
        try:
            source = data[source_start:source_end].decode("utf-8")
        except UnicodeDecodeError as exc:
            raise ProtocolError(f"invalid source name: {exc}") from exc
        payload_start = source_end

    return BinaryClipChunk(
        sender_id=str(uuid.UUID(bytes=sender_id)),
        source=source,
        message_id=str(uuid.UUID(bytes=message_id)),
        created_ms=created_ms,
        text_hash=digest.hex(),
        index=index,
        total=total,
        original_size=original_size,
        payload=data[payload_start:],
    )


def _parse_ack(data: bytes) -> ClipAck:
    """Decode an ACK frame."""

    if len(data) != ACK_HEADER.size:
        raise ProtocolError("ACK frame has invalid length")
    _magic, _version, _kind, sender_id, message_id, total = ACK_HEADER.unpack(data)
    return ClipAck(
        sender_id=str(uuid.UUID(bytes=sender_id)),
        message_id=str(uuid.UUID(bytes=message_id)),
        total=total,
    )


def _parse_nack(data: bytes) -> ClipNack:
    """Decode a NACK frame containing missing chunk indexes."""

    if len(data) < NACK_FIXED_HEADER.size:
        raise ProtocolError("NACK frame is too short")
    _magic, _version, _kind, sender_id, message_id, count = NACK_FIXED_HEADER.unpack_from(data)
    expected = NACK_FIXED_HEADER.size + count * 4
    if len(data) != expected:
        raise ProtocolError("NACK frame has invalid length")
    indexes = tuple(
        struct.unpack_from("<I", data, NACK_FIXED_HEADER.size + offset * 4)[0]
        for offset in range(count)
    )
    return ClipNack(
        sender_id=str(uuid.UUID(bytes=sender_id)),
        message_id=str(uuid.UUID(bytes=message_id)),
        missing_indexes=indexes,
    )


def _decode_binary_message(chunks: PendingChunks) -> ClipboardMessage:
    """Join, decompress, and hash-check one completed binary transfer."""

    payload = b"".join(chunks.chunks[index] for index in range(chunks.total))
    try:
        raw = zlib.decompress(payload)
        text = raw.decode("utf-8")
    except (UnicodeDecodeError, zlib.error) as exc:
        raise ProtocolError(f"invalid compressed clipboard payload: {exc}") from exc

    if len(raw) != chunks.original_size:
        raise ProtocolError("clipboard size mismatch")
    if hashlib.sha256(raw).hexdigest() != chunks.text_hash:
        raise ProtocolError("clipboard hash mismatch")

    return ClipboardMessage(
        source=chunks.source,
        message_id=chunks.message_id,
        created_ms=chunks.created_ms,
        text_hash=chunks.text_hash,
        text=text,
    )


def _uuid_bytes(message_id: str) -> bytes:
    """Convert a printable message id back to its compact binary form."""

    try:
        return uuid.UUID(message_id).bytes
    except ValueError as exc:
        raise ProtocolError(f"invalid message id: {message_id}") from exc
