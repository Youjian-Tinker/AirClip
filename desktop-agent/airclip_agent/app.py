"""Main AirClip desktop agent orchestration."""

from __future__ import annotations

import argparse
import asyncio
import contextlib
import os
import socket
import subprocess
import sys
import uuid
from dataclasses import dataclass
from pathlib import Path

from .ble_transport import AirClipBleTransport, DEFAULT_DEVICE_NAME
from .clipboard import ClipboardAdapter, ClipboardAccessError
from .history import ClipboardHistory
from .history_viewer import default_history_path
from .protocol import (
    BinaryClipChunk,
    ClipAck,
    ClipNack,
    ClipboardMessage,
    PendingChunks,
    ProtocolError,
    accept_binary_clip_chunk,
    build_ack_frame,
    build_clip_frames,
    build_hello_frame,
    build_nack_frame,
    missing_chunk_indexes,
    now_ms,
    parse_binary_frame,
    prune_pending,
    text_hash,
    transfer_stats,
)

try:
    from .tray import TrayController
except ImportError:  # pragma: no cover - used when optional tray deps are absent
    TrayController = None  # type: ignore[assignment]


@dataclass
class AgentConfig:
    """Runtime configuration for one desktop agent process."""

    name: str
    peer_id: str
    relay_name: str = DEFAULT_DEVICE_NAME
    poll_seconds: float = 0.5
    history_capacity: int = 50
    frame_bytes_per_frame: int = 200
    frame_delay_seconds: float = 0.002
    ack_timeout_seconds: float = 8.0
    ack_retry_count: int = 2
    nack_delay_seconds: float = 0.15
    enabled: bool = True
    tray: bool = True
    console: bool = True


class AirClipAgent:
    """Coordinates clipboard polling, BLE transport, history, and controls."""

    def __init__(
        self,
        config: AgentConfig,
        clipboard: ClipboardAdapter | None = None,
        transport: AirClipBleTransport | None = None,
    ) -> None:
        """Create an agent with injectable adapters for testing and reuse."""

        self.config = config
        self.clipboard = clipboard or ClipboardAdapter()
        self.transport = transport or AirClipBleTransport(config.relay_name)
        self.history = ClipboardHistory(config.history_capacity, default_history_path())
        self._history_mtime_ns = self.history.persisted_mtime_ns()
        self._pending: dict[str, PendingChunks] = {}
        self._receive_progress: dict[str, int] = {}
        self._receive_nack_tasks: dict[str, asyncio.Task] = {}
        self._sent_frames: dict[str, list[bytes]] = {}
        self._sent_ack_events: dict[str, asyncio.Event] = {}
        self._seen_hashes: set[str] = set()
        self._last_sent_hash: str | None = None
        self._last_clipboard_hash: str | None = None
        self._restore_snapshot: str | None = None
        self._running = asyncio.Event()
        self._stop_requested = asyncio.Event()
        self._loop: asyncio.AbstractEventLoop | None = None
        self._tray = None

    async def run(self) -> None:
        """Start BLE, clipboard polling, and console command handling."""

        self._loop = asyncio.get_running_loop()
        self._running.set()
        self._start_tray_if_requested()
        connected = await self._connect_with_retry()
        if not connected:
            self._stop_tray()
            return
        if self.config.console:
            print("commands: on, off, history, clear, quit")

        poll_task = asyncio.create_task(self._poll_clipboard())
        stop_task = asyncio.create_task(self._stop_requested.wait())
        wait_tasks = {stop_task}
        command_task = None
        if self.config.console:
            command_task = asyncio.create_task(self._read_commands())
            wait_tasks.add(command_task)

        try:
            done, pending = await asyncio.wait(
                wait_tasks,
                return_when=asyncio.FIRST_COMPLETED,
            )
            for task in pending:
                task.cancel()
            for task in pending:
                with contextlib.suppress(asyncio.CancelledError):
                    await task
            for task in done:
                task.result()
        finally:
            self._running.clear()
            poll_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await poll_task
            self._stop_tray()
            await self.transport.disconnect()

    async def _connect_with_retry(self) -> bool:
        """Keep the tray alive while Windows Bluetooth or the relay is not ready."""

        while self._running.is_set() and not self._stop_requested.is_set():
            try:
                await self.transport.connect(self._handle_ble_bytes)
                await self.transport.send(build_hello_frame(self.config.name, self.config.peer_id))
            except Exception as exc:
                print(f"BLE connect failed, retrying in 5 seconds: {exc!r}")
                await self.transport.disconnect()
                try:
                    await asyncio.wait_for(self._stop_requested.wait(), timeout=5.0)
                except asyncio.TimeoutError:
                    continue
                return False
            print(f"connected to {self.config.relay_name} as {self.config.name}")
            return True
        return False

    async def _poll_clipboard(self) -> None:
        """Watch local clipboard changes and publish eligible text updates."""

        while self._running.is_set():
            await asyncio.sleep(self.config.poll_seconds)
            self._sync_external_history_clear()
            if not self.config.enabled:
                continue

            try:
                text = self.clipboard.read_text()
            except ClipboardAccessError as exc:
                print(f"clipboard read failed: {exc}")
                continue

            if not text:
                continue

            digest = text_hash(text)
            if digest == self._last_clipboard_hash:
                continue
            self._last_clipboard_hash = digest

            if digest == self._last_sent_hash:
                print(f"clipboard poll skipped remote echo hash={self._short_hash(digest)}")
                continue

            self.history.add(text, self.config.name, now_ms())
            self._seen_hashes.add(digest)
            self._last_sent_hash = digest
            await self._send_clipboard_text(text)

    async def _send_clipboard_text(self, text: str) -> None:
        """Send compressed binary frames and keep them briefly for retransmission."""

        if not await self._ensure_connected():
            print("clipboard send skipped: BLE relay is not connected")
            return

        frames = build_clip_frames(
            self.config.name,
            text,
            data_bytes_per_frame=self.config.frame_bytes_per_frame,
            sender_id=self.config.peer_id,
        )
        message_id = self._message_id_from_frame(frames[0])
        digest = text_hash(text)
        raw_size, compressed_size, _ = transfer_stats(text, self.config.frame_bytes_per_frame)
        ack_event = asyncio.Event()
        self._sent_frames[message_id] = frames
        self._sent_ack_events[message_id] = ack_event
        print(
            f"sending clipboard text ({len(text)} chars, raw={raw_size} bytes, "
            f"compressed={compressed_size} bytes, frames={len(frames)}, "
            f"frame_bytes={self.config.frame_bytes_per_frame}, "
            f"message={self._short_id(message_id)}, hash={self._short_hash(digest)})"
        )
        try:
            for attempt in range(self.config.ack_retry_count + 1):
                await self._send_frame_batch(frames)
                if ack_event.is_set():
                    break
                retry_left = attempt < self.config.ack_retry_count
                attempt_label = f" attempt {attempt + 1}" if self.config.ack_retry_count else ""
                try:
                    await asyncio.wait_for(ack_event.wait(), timeout=self.config.ack_timeout_seconds)
                except asyncio.TimeoutError:
                    if retry_left:
                        print(f"clipboard ACK timeout for {message_id}{attempt_label}; retrying full message")
                    else:
                        print(f"clipboard ACK timeout for {message_id}; receiver may request retransmit later")
                else:
                    break
            if ack_event.is_set():
                print(f"clipboard ACK received for {self._short_id(message_id)}")
            else:
                # Allow the same unchanged clipboard text to be retried on the next poll.
                self._seen_hashes.discard(digest)
                if self._last_sent_hash == digest:
                    self._last_sent_hash = None
                if self._last_clipboard_hash == digest:
                    self._last_clipboard_hash = None
                print(
                    f"clipboard send incomplete for {self._short_id(message_id)}; "
                    "dedupe cleared so this text can retry"
                )
        except Exception as exc:
            self._seen_hashes.discard(digest)
            if self._last_sent_hash == digest:
                self._last_sent_hash = None
            if self._last_clipboard_hash == digest:
                self._last_clipboard_hash = None
            print(f"clipboard send failed: {exc}")
        finally:
            self._sent_frames.pop(message_id, None)
            self._sent_ack_events.pop(message_id, None)

    async def _handle_ble_bytes(self, data: bytes) -> None:
        """Parse binary relay notifications and handle reliability controls."""

        try:
            parsed = parse_binary_frame(data)
            if parsed is None:
                return
            prune_pending(self._pending)
            if isinstance(parsed, BinaryClipChunk):
                if parsed.sender_id == self.config.peer_id:
                    return
                await self._handle_clip_chunk(parsed)
            elif isinstance(parsed, ClipAck):
                self._handle_ack(parsed)
            elif isinstance(parsed, ClipNack):
                await self._handle_nack(parsed)
        except ProtocolError as exc:
            print(f"dropped malformed BLE frame: {exc}")

    async def _handle_clip_chunk(self, chunk: BinaryClipChunk) -> None:
        """Store one incoming chunk, request missing chunks, and ACK completion."""

        message = accept_binary_clip_chunk(chunk, self._pending)
        self._log_incoming_clip_progress(chunk)
        if message is None:
            self._schedule_missing_chunk_request(chunk.message_id)
            return

        self._receive_progress.pop(message.message_id, None)
        task = self._receive_nack_tasks.pop(message.message_id, None)
        if task is not None:
            task.cancel()
        if await self._apply_remote_clipboard(message):
            await self.transport.send(build_ack_frame(message.message_id, chunk.total, self.config.peer_id))

    def _handle_ack(self, ack: ClipAck) -> None:
        """Mark an outbound clipboard message as complete on the receiver."""

        event = self._sent_ack_events.get(ack.message_id)
        if event is None:
            return
        print(
            f"received ACK for {self._short_id(ack.message_id)} "
            f"from {self._short_id(ack.sender_id)}, frames={ack.total}"
        )
        event.set()

    async def _handle_nack(self, nack: ClipNack) -> None:
        """Retransmit only the chunks that the receiver reports missing."""

        frames = self._sent_frames.get(nack.message_id)
        if not frames:
            return
        resend = [frames[index] for index in nack.missing_indexes if 0 <= index < len(frames)]
        if not resend:
            return
        print(
            f"retransmitting {len(resend)} missing frame(s) for "
            f"{self._short_id(nack.message_id)} from request {self._short_id(nack.sender_id)}"
        )
        await self._send_frame_batch(resend, log_every=25)

    def _log_incoming_clip_progress(self, chunk: BinaryClipChunk) -> None:
        """Print sparse receive progress so partial long transfers are diagnosable."""

        pending = self._pending.get(chunk.message_id)
        received = len(pending.chunks) if pending is not None else chunk.total
        self._receive_progress[chunk.message_id] = received
        if received == 1 or received == chunk.total or received % 25 == 0:
            print(
                f"received frame {received}/{chunk.total} from {chunk.source} "
                f"message={self._short_id(chunk.message_id)} hash={self._short_hash(chunk.text_hash)} "
                f"payload={len(chunk.payload)} bytes"
            )

    def _schedule_missing_chunk_request(self, message_id: str) -> None:
        """Debounce NACKs so missing chunks are requested after receive traffic quiets."""

        existing = self._receive_nack_tasks.get(message_id)
        if existing is not None and not existing.done():
            existing.cancel()
        self._receive_nack_tasks[message_id] = asyncio.create_task(
            self._send_missing_chunk_request_after_delay(message_id)
        )

    async def _send_missing_chunk_request_after_delay(self, message_id: str) -> None:
        """Send a NACK for any gaps left after normal in-order delivery catches up."""

        try:
            await asyncio.sleep(self.config.nack_delay_seconds)
            pending = self._pending.get(message_id)
            if pending is None:
                return
            missing = missing_chunk_indexes(pending)
            if not missing:
                return
            print(
                f"requesting retransmit for {len(missing)} missing frame(s) from {pending.source} "
                f"message={self._short_id(message_id)} first_missing={missing[0]}"
            )
            try:
                await self.transport.send(build_nack_frame(message_id, missing, self.config.peer_id))
            except Exception as exc:
                print(f"missing-frame request failed: {exc}")
        finally:
            self._receive_nack_tasks.pop(message_id, None)

    async def _send_frame_batch(self, frames: list[bytes], log_every: int = 25) -> None:
        """Write a batch of MTU-safe frames with fast pacing."""

        total = len(frames)
        frame_delay = self.config.frame_delay_seconds if total > 1 else 0.0
        for index, frame in enumerate(frames, start=1):
            if not await self._ensure_connected():
                raise RuntimeError("BLE relay is not connected")
            await self.transport.send(frame, response=False)
            if index == 1 or index == total or index % log_every == 0:
                message_id = self._message_id_from_frame(frame)
                print(f"sent frame {index}/{total} ({len(frame)} bytes) message={self._short_id(message_id)}")
            if frame_delay > 0:
                await asyncio.sleep(frame_delay)

    async def _ensure_connected(self) -> bool:
        """Reconnect before sending if Windows dropped the BLE link."""

        if self.transport.is_connected():
            return True
        print("BLE relay disconnected, reconnecting before send")
        await self.transport.disconnect()
        return await self._connect_with_retry()

    def _message_id_from_frame(self, frame: bytes) -> str:
        """Read the message id from the first generated chunk frame."""

        parsed = parse_binary_frame(frame)
        if not isinstance(parsed, BinaryClipChunk):
            raise ProtocolError("first clipboard frame is not a binary chunk")
        return parsed.message_id

    def _short_id(self, value: str) -> str:
        """Return a compact id fragment for correlating logs without noisy UUIDs."""

        return value.split("-")[0] if value else "-"

    def _short_hash(self, value: str) -> str:
        """Return a non-reversible hash prefix instead of logging clipboard text."""

        return value[:12] if value else "-"

    async def _apply_remote_clipboard(self, message: ClipboardMessage) -> bool:
        """Record a remote clipboard update and optionally write it locally."""

        if self._remote_clipboard_already_current(message):
            self._seen_hashes.add(message.text_hash)
            self._last_clipboard_hash = message.text_hash
            return True

        self.history.add(message.text, message.source, message.created_ms)

        if not self.config.enabled:
            self._seen_hashes.add(message.text_hash)
            print(f"received clipboard from {message.source}, sharing is disabled")
            return True

        # Keep one restore point for the first remote overwrite during this session.
        if self._restore_snapshot is None:
            self._capture_share_snapshot()

        try:
            self.clipboard.write_text(message.text)
        except ClipboardAccessError as exc:
            print(
                f"clipboard write failed for {self._short_id(message.message_id)} "
                f"hash={self._short_hash(message.text_hash)} len={len(message.text)}: {exc}"
            )
            return False

        self._seen_hashes.add(message.text_hash)
        self._last_sent_hash = message.text_hash
        self._last_clipboard_hash = message.text_hash
        print(
            f"received clipboard from {message.source} ({len(message.text)} chars, "
            f"message={self._short_id(message.message_id)}, hash={self._short_hash(message.text_hash)})"
        )
        return True

    def _remote_clipboard_already_current(self, message: ClipboardMessage) -> bool:
        """Skip duplicate remote frames only when the local clipboard already matches."""

        if message.text_hash not in self._seen_hashes:
            return False

        try:
            current_text = self.clipboard.read_text()
        except ClipboardAccessError as exc:
            print(
                f"clipboard duplicate check failed for {self._short_id(message.message_id)} "
                f"hash={self._short_hash(message.text_hash)}: {exc}"
            )
            return False

        if text_hash(current_text) != message.text_hash:
            print(
                f"reapplying previously seen clipboard from {message.source} "
                f"message={self._short_id(message.message_id)} hash={self._short_hash(message.text_hash)}"
            )
            return False

        print(
            f"skipped duplicate remote clipboard already current "
            f"message={self._short_id(message.message_id)} hash={self._short_hash(message.text_hash)}"
        )
        return True

    async def _read_commands(self) -> None:
        """Run a small console controller for enable/disable and history."""

        while self._running.is_set():
            try:
                command = await asyncio.to_thread(input, "> ")
            except EOFError:
                return
            normalized = command.strip().lower()
            if normalized in {"quit", "exit", "q"}:
                return
            if normalized in {"on", "enable"}:
                self.set_enabled(True)
            elif normalized in {"off", "disable"}:
                self.set_enabled(False)
            elif normalized == "history":
                self._print_history()
            elif normalized == "clear":
                self.clear_history()
            elif normalized:
                print("unknown command")

    def set_enabled(self, enabled: bool) -> None:
        """Switch clipboard sharing on or off for both tray and console users."""

        was_enabled = self.config.enabled
        if enabled and not was_enabled:
            self._restore_snapshot = None

        self.config.enabled = enabled
        if not enabled and was_enabled:
            # Pausing sharing should also discard any partial remote frames and
            # put back the local clipboard that existed before the first remote overwrite.
            self._pending.clear()
            self._receive_progress.clear()
            for task in self._receive_nack_tasks.values():
                task.cancel()
            self._receive_nack_tasks.clear()
            self._restore_share_snapshot()

        if self._tray is not None:
            self._tray.refresh()
        print("sharing enabled" if enabled else "sharing disabled")

    def clear_history(self) -> None:
        """Clear local history and deduplication state."""

        self.history.clear()
        self._history_mtime_ns = self.history.persisted_mtime_ns()
        self._seen_hashes.clear()
        self._last_sent_hash = None
        self._last_clipboard_hash = None
        print("history cleared")

    def _sync_external_history_clear(self) -> None:
        """Reset in-memory dedupe when the standalone history window clears disk state."""

        current_mtime = self.history.persisted_mtime_ns()
        if current_mtime is None or current_mtime == self._history_mtime_ns:
            return
        self._history_mtime_ns = current_mtime
        if not self.history.is_persisted_empty():
            return

        self.history.clear()
        self._history_mtime_ns = self.history.persisted_mtime_ns()
        self._seen_hashes.clear()
        self._last_sent_hash = None
        self._last_clipboard_hash = None
        print("history cleared externally; dedupe state reset")

    def open_history_window(self) -> None:
        """Open the persistent clipboard queue in a separate viewer window."""

        pythonw = Path(sys.executable).with_name("pythonw.exe")
        viewer_path = Path(__file__).with_name("history_viewer.py")
        subprocess.Popen(
            [str(pythonw if pythonw.exists() else sys.executable), str(viewer_path)],
            cwd=str(Path(__file__).resolve().parents[1]),
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )

    def stop_from_external_control(self) -> None:
        """Stop the async command loop from a tray callback thread."""

        if self._loop is None:
            return
        self._loop.call_soon_threadsafe(self._running.clear)
        self._loop.call_soon_threadsafe(self._stop_requested.set)

    def _print_history(self) -> None:
        """Print the bounded local history without exposing extra metadata."""

        entries = self.history.entries()
        if not entries:
            print("history is empty")
            return
        for index, entry in enumerate(entries, start=1):
            preview = entry.text.replace("\r", " ").replace("\n", " ")
            if len(preview) > 80:
                preview = preview[:77] + "..."
            print(f"{index:02d}. [{entry.source}] {preview}")

    def _start_tray_if_requested(self) -> None:
        """Create the tray icon when dependencies and configuration allow it."""

        if not self.config.tray:
            return
        if TrayController is None:
            print("tray unavailable, continuing with console commands")
            return
        self._tray = TrayController(
            is_enabled=lambda: self.config.enabled,
            set_enabled=self.set_enabled,
            clear_history=self.clear_history,
            open_history=self.open_history_window,
            stop=self.stop_from_external_control,
        )
        self._tray.run_detached()
        self._tray.refresh()

    def _stop_tray(self) -> None:
        """Remove the tray icon during shutdown."""

        if self._tray is None:
            return
        self._tray.stop()
        self._tray = None

    def _capture_share_snapshot(self) -> None:
        """Remember the clipboard contents that should come back after pause."""

        try:
            self._restore_snapshot = self.clipboard.read_text()
        except ClipboardAccessError as exc:
            self._restore_snapshot = None
            print(f"clipboard snapshot failed: {exc}")

    def _restore_share_snapshot(self) -> None:
        """Restore the clipboard that existed when sharing was enabled."""

        if self._restore_snapshot is None:
            return

        try:
            self.clipboard.write_text(self._restore_snapshot)
        except ClipboardAccessError as exc:
            print(f"clipboard restore failed: {exc}")
        else:
            self._last_sent_hash = text_hash(self._restore_snapshot)
            self._last_clipboard_hash = self._last_sent_hash
        finally:
            self._restore_snapshot = None


def parse_args() -> AgentConfig:
    """Parse command-line arguments into an agent configuration."""

    parser = argparse.ArgumentParser(description="AirClip BLE clipboard agent")
    parser.add_argument("--name", default=socket.gethostname(), help="unique local device name")
    parser.add_argument("--peer-id", default=_default_peer_id(), help="persistent unique local agent id")
    parser.add_argument("--relay-name", default=DEFAULT_DEVICE_NAME, help="ESP32 BLE advertising name")
    parser.add_argument("--poll-seconds", type=float, default=0.5, help="clipboard polling interval")
    parser.add_argument("--history-capacity", type=int, default=50, help="max local history entries")
    parser.add_argument(
        "--frame-bytes",
        type=int,
        default=200,
        help="compressed binary payload bytes per BLE frame, clamped to MTU-safe size",
    )
    parser.add_argument(
        "--frame-delay",
        type=float,
        default=0.002,
        help="seconds to wait between BLE frame writes",
    )
    parser.add_argument(
        "--ack-timeout",
        type=float,
        default=8.0,
        help="seconds to wait for receiver ACK before releasing resend state",
    )
    parser.add_argument(
        "--ack-retries",
        type=int,
        default=2,
        help="full-message resend attempts after ACK timeout",
    )
    parser.add_argument(
        "--nack-delay",
        type=float,
        default=0.15,
        help="seconds to wait before asking for missing BLE chunks",
    )
    parser.add_argument("--disabled", action="store_true", help="start with sharing disabled")
    parser.add_argument("--no-tray", action="store_true", help="disable the Windows tray menu")
    parser.add_argument(
        "--no-console",
        action="store_true",
        help="run without reading console commands, intended for shortcut/startup use",
    )
    args = parser.parse_args()
    return AgentConfig(
        name=args.name,
        peer_id=args.peer_id,
        relay_name=args.relay_name,
        poll_seconds=args.poll_seconds,
        history_capacity=args.history_capacity,
        frame_bytes_per_frame=args.frame_bytes,
        frame_delay_seconds=args.frame_delay,
        ack_timeout_seconds=args.ack_timeout,
        ack_retry_count=max(0, args.ack_retries),
        nack_delay_seconds=args.nack_delay,
        enabled=not args.disabled,
        tray=not args.no_tray,
        console=not args.no_console,
    )


def main() -> None:
    """Run the AirClip agent from the command line."""

    config = parse_args()
    if not config.console:
        _redirect_background_logs()
    agent = AirClipAgent(config)
    try:
        asyncio.run(agent.run())
    except KeyboardInterrupt:
        print("stopped")


def _redirect_background_logs() -> None:
    """Write pythonw/background output to a log file because there is no console."""

    log_dir = Path(os.environ.get("LOCALAPPDATA", ".")) / "AirClip"
    log_dir.mkdir(parents=True, exist_ok=True)
    log_file = log_dir / "airclip-agent.log"
    stream = log_file.open("a", encoding="utf-8", buffering=1)
    sys.stdout = stream
    sys.stderr = stream
    print("AirClip background agent starting")


def _default_peer_id() -> str:
    """Load or create the stable id used to ignore only this agent's own frames."""

    data_dir = Path(os.environ.get("LOCALAPPDATA", ".")) / "AirClip"
    peer_file = data_dir / "agent-id.txt"
    try:
        if peer_file.exists():
            return str(uuid.UUID(peer_file.read_text(encoding="utf-8").strip()))
        data_dir.mkdir(parents=True, exist_ok=True)
        peer_id = str(uuid.uuid4())
        peer_file.write_text(peer_id, encoding="utf-8")
        return peer_id
    except (OSError, ValueError):
        return str(uuid.uuid4())
