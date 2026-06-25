import asyncio

from airclip_agent.app import AgentConfig, AirClipAgent
from airclip_agent.protocol import ClipboardMessage, now_ms, text_hash


class FakeClipboard:
    def __init__(self, text: str = "") -> None:
        self.text = text
        self.writes: list[str] = []

    def read_text(self) -> str:
        return self.text

    def write_text(self, text: str) -> None:
        self.text = text
        self.writes.append(text)


class FakeTransport:
    def __init__(self) -> None:
        self.sent: list[bytes] = []

    async def send(self, payload: bytes, response: bool = True) -> None:
        self.sent.append(payload)

    def is_connected(self) -> bool:
        return True


def test_send_clipboard_text_clears_dedupe_when_ack_never_arrives() -> None:
    asyncio.run(_run_send_clipboard_text_clears_dedupe_when_ack_never_arrives())


async def _run_send_clipboard_text_clears_dedupe_when_ack_never_arrives() -> None:
    config = AgentConfig(
        name="pc-a",
        peer_id="00000000-0000-0000-0000-000000000001",
        ack_timeout_seconds=0.001,
        ack_retry_count=0,
    )
    transport = FakeTransport()
    agent = AirClipAgent(config, transport=transport)
    digest = text_hash("system/King@Base2024!")
    agent._seen_hashes.add(digest)
    agent._last_sent_hash = digest

    await agent._send_clipboard_text("system/King@Base2024!")
    await asyncio.sleep(0)

    assert transport.sent
    assert digest not in agent._seen_hashes
    assert agent._last_sent_hash is None
    assert agent._last_clipboard_hash is None


def test_poll_clipboard_resends_seen_text_after_windows_history_changes_current_clipboard() -> None:
    asyncio.run(_run_poll_clipboard_resends_seen_text_after_windows_history_changes_current_clipboard())


async def _run_poll_clipboard_resends_seen_text_after_windows_history_changes_current_clipboard() -> None:
    config = AgentConfig(
        name="pc-a",
        peer_id="00000000-0000-0000-0000-000000000001",
        poll_seconds=0,
        ack_timeout_seconds=0.001,
        ack_retry_count=0,
    )
    clipboard = FakeClipboard("system/King@Base2024!")
    transport = FakeTransport()
    agent = AirClipAgent(config, clipboard=clipboard, transport=transport)
    digest_a = text_hash("system/King@Base2024!")
    digest_b = text_hash("from-windows-history")
    agent._seen_hashes.add(digest_a)
    agent._last_clipboard_hash = digest_b
    agent._running.set()

    poll_task = asyncio.create_task(agent._poll_clipboard())
    await asyncio.sleep(0.01)
    agent._running.clear()
    poll_task.cancel()
    try:
        await poll_task
    except asyncio.CancelledError:
        pass

    assert transport.sent
    assert agent._last_clipboard_hash in {None, digest_a}


def test_apply_remote_clipboard_reapplies_seen_text_when_current_clipboard_changed() -> None:
    asyncio.run(_run_apply_remote_clipboard_reapplies_seen_text_when_current_clipboard_changed())


async def _run_apply_remote_clipboard_reapplies_seen_text_when_current_clipboard_changed() -> None:
    clipboard = FakeClipboard("from-windows-history")
    agent = AirClipAgent(
        AgentConfig(name="pc-b", peer_id="00000000-0000-0000-0000-000000000002"),
        clipboard=clipboard,
        transport=FakeTransport(),
    )
    text = "system/King@Base2024!"
    digest = text_hash(text)
    agent._seen_hashes.add(digest)
    message = ClipboardMessage(
        source="pc-a",
        message_id="11111111-1111-1111-1111-111111111111",
        created_ms=now_ms(),
        text_hash=digest,
        text=text,
    )

    applied = await agent._apply_remote_clipboard(message)

    assert applied is True
    assert clipboard.writes == [text]
    assert agent._last_clipboard_hash == digest
