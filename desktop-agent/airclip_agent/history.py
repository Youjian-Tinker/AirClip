"""Bounded clipboard history storage."""

from __future__ import annotations

import json
from collections import deque
from dataclasses import dataclass
from pathlib import Path

from .protocol import text_hash


@dataclass(frozen=True)
class HistoryEntry:
    """One deduplicated clipboard history item."""

    text: str
    text_hash: str
    source: str
    created_ms: int


class ClipboardHistory:
    """Maintains the recent clipboard queue with a fixed capacity."""

    def __init__(self, capacity: int = 50, persist_path: Path | None = None) -> None:
        """Create an empty bounded history queue."""

        self.capacity = capacity
        self._persist_path = persist_path
        self._items: deque[HistoryEntry] = deque(maxlen=capacity)
        self._load_persisted_items()

    def add(self, text: str, source: str, created_ms: int) -> HistoryEntry:
        """Add text as the newest item, moving duplicates to the front."""

        digest = text_hash(text)
        self._items = deque(
            (item for item in self._items if item.text_hash != digest),
            maxlen=self.capacity,
        )
        entry = HistoryEntry(text=text, text_hash=digest, source=source, created_ms=created_ms)
        self._items.appendleft(entry)
        self._persist()
        return entry

    def clear(self) -> None:
        """Remove every locally stored history item."""

        self._items.clear()
        self._persist()

    def contains_hash(self, digest: str) -> bool:
        """Return whether a clipboard hash is already in local history."""

        return any(item.text_hash == digest for item in self._items)

    def newest_hash(self) -> str | None:
        """Return the newest clipboard hash when history is not empty."""

        if not self._items:
            return None
        return self._items[0].text_hash

    def entries(self) -> list[HistoryEntry]:
        """Return newest-first history entries for display."""

        return list(self._items)

    def is_persisted_empty(self) -> bool:
        """Return whether the shared history file was externally cleared."""

        if self._persist_path is None or not self._persist_path.exists():
            return False
        try:
            payload = json.loads(self._persist_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return False
        return payload == []

    def persisted_mtime_ns(self) -> int | None:
        """Return the shared history file mtime for external-change detection."""

        if self._persist_path is None:
            return None
        try:
            return self._persist_path.stat().st_mtime_ns
        except OSError:
            return None

    def _load_persisted_items(self) -> None:
        """Restore the last saved queue so the history window survives restarts."""

        if self._persist_path is None or not self._persist_path.exists():
            return

        try:
            payload = json.loads(self._persist_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return

        if not isinstance(payload, list):
            return

        items: list[HistoryEntry] = []
        for entry in payload:
            if not isinstance(entry, dict):
                continue
            text = entry.get("text")
            source = entry.get("source")
            created_ms = entry.get("created_ms")
            digest = entry.get("text_hash")
            if not all(isinstance(value, str) for value in (text, source, digest)):
                continue
            if not isinstance(created_ms, int):
                continue
            items.append(
                HistoryEntry(
                    text=text,
                    text_hash=digest,
                    source=source,
                    created_ms=created_ms,
                )
            )

        for entry in reversed(items[-self.capacity :]):
            self._items.appendleft(entry)

    def _persist(self) -> None:
        """Write the bounded queue to disk so the viewer can reopen it later."""

        if self._persist_path is None:
            return

        try:
            self._persist_path.parent.mkdir(parents=True, exist_ok=True)
            payload = [
                {
                    "text": entry.text,
                    "text_hash": entry.text_hash,
                    "source": entry.source,
                    "created_ms": entry.created_ms,
                }
                for entry in self._items
            ]
            temp_path = self._persist_path.with_suffix(".tmp")
            temp_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
            temp_path.replace(self._persist_path)
        except OSError:
            return
