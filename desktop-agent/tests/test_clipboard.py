import pyperclip

from airclip_agent.clipboard import ClipboardAdapter


def test_clipboard_read_retries_transient_lock(monkeypatch) -> None:
    attempts = {"count": 0}

    def flaky_paste() -> str:
        attempts["count"] += 1
        if attempts["count"] == 1:
            raise pyperclip.PyperclipException("clipboard busy")
        return "synced text"

    monkeypatch.setattr(pyperclip, "paste", flaky_paste)
    monkeypatch.setattr("airclip_agent.clipboard.time.sleep", lambda _seconds: None)

    assert ClipboardAdapter().read_text() == "synced text"
    assert attempts["count"] == 2


def test_clipboard_write_retries_transient_lock(monkeypatch) -> None:
    attempts = {"count": 0, "value": ""}

    def flaky_copy(text: str) -> None:
        attempts["count"] += 1
        if attempts["count"] == 1:
            raise pyperclip.PyperclipException("clipboard busy")
        attempts["value"] = text

    monkeypatch.setattr(pyperclip, "copy", flaky_copy)
    monkeypatch.setattr("airclip_agent.clipboard.time.sleep", lambda _seconds: None)

    ClipboardAdapter().write_text("remote text")

    assert attempts == {"count": 2, "value": "remote text"}
