from pathlib import Path

from airclip_agent.history import ClipboardHistory
from airclip_agent.protocol import (
    BinaryClipChunk,
    ClipAck,
    ClipNack,
    accept_binary_clip_chunk,
    build_ack_frame,
    build_clip_frames,
    build_nack_frame,
    missing_chunk_indexes,
    parse_binary_frame,
    transfer_stats,
)


def test_protocol_reassembles_chunked_clipboard_text() -> None:
    pending = {}
    text = "政务 VPN clipboard " * 20
    result = None

    for raw in build_clip_frames("pc-a", text, data_bytes_per_frame=80):
        chunk = parse_binary_frame(raw)
        assert isinstance(chunk, BinaryClipChunk)
        result = accept_binary_clip_chunk(chunk, pending)

    assert result is not None
    assert result.source == "pc-a"
    assert result.text == text
    assert pending == {}


def test_protocol_reports_missing_chunks_for_retransmit() -> None:
    pending = {}
    text = "line 001 DEBUG something happened\n" * 200
    frames = build_clip_frames("pc-a", text, data_bytes_per_frame=80)

    for raw in frames[:-1]:
        chunk = parse_binary_frame(raw)
        assert isinstance(chunk, BinaryClipChunk)
        assert accept_binary_clip_chunk(chunk, pending) is None

    chunk = parse_binary_frame(frames[0])
    assert isinstance(chunk, BinaryClipChunk)
    assert missing_chunk_indexes(pending[chunk.message_id]) == [len(frames) - 1]

    last_chunk = parse_binary_frame(frames[-1])
    assert isinstance(last_chunk, BinaryClipChunk)
    result = accept_binary_clip_chunk(last_chunk, pending)
    assert result is not None
    assert result.text == text


def test_protocol_ack_and_nack_frames_round_trip() -> None:
    frames = build_clip_frames("pc-a", "hello", data_bytes_per_frame=80)
    chunk = parse_binary_frame(frames[0])
    assert isinstance(chunk, BinaryClipChunk)

    ack = parse_binary_frame(build_ack_frame(chunk.message_id, chunk.total))
    assert isinstance(ack, ClipAck)
    assert ack.message_id == chunk.message_id

    nack = parse_binary_frame(build_nack_frame(chunk.message_id, [2, 1, 1]))
    assert isinstance(nack, ClipNack)
    assert nack.message_id == chunk.message_id
    assert nack.missing_indexes == (1, 2)


def test_protocol_compresses_log_payload_into_fewer_frames() -> None:
    text = "09:50:50.049 [http-nio-1666-exec-6] DEBUG selectList parameters\n" * 500

    raw_size, compressed_size, frame_count = transfer_stats(text, data_bytes_per_frame=200)

    assert raw_size > 30000
    assert compressed_size < raw_size // 5
    assert frame_count < 50


def test_history_keeps_newest_50_entries() -> None:
    history = ClipboardHistory(capacity=50)

    for index in range(60):
        history.add(f"text-{index}", "local", index)

    entries = history.entries()
    assert len(entries) == 50
    assert entries[0].text == "text-59"
    assert entries[-1].text == "text-10"


def test_history_moves_duplicate_to_front() -> None:
    history = ClipboardHistory(capacity=3)

    history.add("one", "local", 1)
    history.add("two", "local", 2)
    history.add("one", "remote", 3)

    entries = history.entries()
    assert [entry.text for entry in entries] == ["one", "two"]
    assert entries[0].source == "remote"


def test_history_persists_queue(tmp_path: Path) -> None:
    path = tmp_path / "history.json"
    history = ClipboardHistory(capacity=3, persist_path=path)
    history.add("one", "local", 1)
    history.add("two", "remote", 2)

    restored = ClipboardHistory(capacity=3, persist_path=path)
    entries = restored.entries()
    assert [entry.text for entry in entries] == ["two", "one"]


def test_history_detects_external_clear(tmp_path: Path) -> None:
    path = tmp_path / "history.json"
    history = ClipboardHistory(capacity=3, persist_path=path)
    history.add("one", "local", 1)

    path.write_text("[]", encoding="utf-8")

    assert history.is_persisted_empty()
    assert history.persisted_mtime_ns() is not None
