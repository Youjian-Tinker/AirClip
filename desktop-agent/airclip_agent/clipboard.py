"""System clipboard adapter."""

from __future__ import annotations

import time

import pyperclip


class ClipboardAccessError(RuntimeError):
    """Raised when the operating system clipboard cannot be read or written."""


class ClipboardAdapter:
    """Wraps clipboard access so the rest of the agent stays testable."""

    # Retry briefly because Windows commonly locks the clipboard while another
    # process is copying or pasting.
    def read_text(self) -> str:
        """Read the current system clipboard as text."""

        value = self._retry_clipboard_call(pyperclip.paste)
        return value if isinstance(value, str) else ""

    # Retry writes so a transient clipboard lock does not drop a remote update.
    def write_text(self, text: str) -> None:
        """Replace the current system clipboard text."""

        self._retry_clipboard_call(lambda: pyperclip.copy(text))

    # Keep retries local to clipboard I/O so callers still see one clear failure.
    def _retry_clipboard_call(self, operation):
        """Run one clipboard operation with short backoff for transient locks."""

        last_error: pyperclip.PyperclipException | None = None
        for attempt in range(12):
            try:
                return operation()
            except pyperclip.PyperclipException as exc:
                last_error = exc
                if attempt < 11:
                    time.sleep(0.05)
        if last_error is not None:
            raise ClipboardAccessError(str(last_error)) from last_error
        raise ClipboardAccessError("clipboard operation failed")
