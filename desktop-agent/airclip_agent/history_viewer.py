"""Tkinter clipboard history window for AirClip."""

from __future__ import annotations

import json
import os
import tkinter as tk
from datetime import datetime
from pathlib import Path
from tkinter import ttk


def default_history_path() -> Path:
    """Return the shared history file used by the background agent and viewer."""

    return Path(os.environ.get("LOCALAPPDATA", ".")) / "AirClip" / "clipboard-history.json"


class ClipboardHistoryWindow:
    """Shows recent clipboard entries in a lightweight desktop window."""

    def __init__(self, history_path: Path | None = None) -> None:
        """Create the history window and load the persisted queue."""

        self.history_path = history_path or default_history_path()
        self.root = tk.Tk()
        self.root.title("AirClip 剪贴板")
        self.root.geometry("460x620")
        self.root.minsize(380, 420)
        self._items: list[dict] = []

        self._build_ui()
        self.refresh()

    def run(self) -> None:
        """Enter the Tkinter event loop."""

        self.root.mainloop()

    def _build_ui(self) -> None:
        """Build a compact history list with clear and refresh controls."""

        self.root.configure(bg="#eef3fb")
        header = tk.Frame(self.root, bg="#eef3fb")
        header.pack(fill=tk.X, padx=14, pady=(14, 8))

        title = tk.Label(
            header,
            text="剪贴板",
            font=("Microsoft YaHei UI", 15, "bold"),
            fg="#1d2733",
            bg="#eef3fb",
        )
        title.pack(side=tk.LEFT)

        clear_button = ttk.Button(header, text="全部清除", command=self.clear)
        clear_button.pack(side=tk.RIGHT)

        refresh_button = ttk.Button(header, text="刷新", command=self.refresh)
        refresh_button.pack(side=tk.RIGHT, padx=(0, 8))

        self.canvas = tk.Canvas(self.root, bg="#eef3fb", highlightthickness=0)
        scrollbar = ttk.Scrollbar(self.root, orient=tk.VERTICAL, command=self.canvas.yview)
        self.list_frame = tk.Frame(self.canvas, bg="#eef3fb")
        self.list_frame.bind(
            "<Configure>",
            lambda _: self.canvas.configure(scrollregion=self.canvas.bbox("all")),
        )
        self.canvas.create_window((0, 0), window=self.list_frame, anchor="nw")
        self.canvas.configure(yscrollcommand=scrollbar.set)
        self.canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=(8, 0), pady=(0, 10))
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y, pady=(0, 10), padx=(0, 8))

    def refresh(self) -> None:
        """Reload the persisted queue and redraw the card list."""

        self._items = self._load_items()
        for child in self.list_frame.winfo_children():
            child.destroy()

        if not self._items:
            empty = tk.Label(
                self.list_frame,
                text="暂无剪贴板记录",
                font=("Microsoft YaHei UI", 12),
                fg="#718096",
                bg="#eef3fb",
            )
            empty.pack(fill=tk.X, padx=12, pady=24)
            return

        for index, entry in enumerate(self._items):
            self._add_card(index, entry)

    def clear(self) -> None:
        """Clear the persisted queue from the viewer."""

        try:
            self.history_path.write_text("[]", encoding="utf-8")
        except OSError:
            return
        self.refresh()

    def _add_card(self, index: int, entry: dict) -> None:
        """Render one clipboard entry card with actions."""

        card = tk.Frame(
            self.list_frame,
            bg="#ffffff",
            highlightbackground="#d7dde7",
            highlightthickness=1,
            padx=12,
            pady=10,
        )
        card.pack(fill=tk.X, padx=10, pady=6)

        top = tk.Frame(card, bg="#ffffff")
        top.pack(fill=tk.X)

        meta = tk.Label(
            top,
            text=f"{entry.get('source', 'unknown')} · {self._format_time(entry.get('created_ms'))}",
            font=("Microsoft YaHei UI", 8),
            fg="#718096",
            bg="#ffffff",
        )
        meta.pack(side=tk.LEFT)

        copy_button = ttk.Button(top, text="复制", command=lambda: self._copy_text(entry))
        copy_button.pack(side=tk.RIGHT)

        text = str(entry.get("text", ""))
        preview = text.strip() or "(空白文本)"
        preview_widget = tk.Label(
            card,
            text=preview,
            justify=tk.LEFT,
            anchor="nw",
            wraplength=390,
            font=("Consolas", 10),
            fg="#18212f",
            bg="#ffffff",
        )
        preview_widget.pack(fill=tk.X, pady=(8, 0))

    def _copy_text(self, entry: dict) -> None:
        """Copy a selected history item back to the system clipboard."""

        self.root.clipboard_clear()
        self.root.clipboard_append(str(entry.get("text", "")))
        self.root.update_idletasks()

    def _load_items(self) -> list[dict]:
        """Read recent clipboard entries from disk in newest-first order."""

        try:
            payload = json.loads(self.history_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return []

        if not isinstance(payload, list):
            return []
        return [item for item in payload if isinstance(item, dict)]

    def _format_time(self, created_ms: object) -> str:
        """Format millisecond timestamps for compact card metadata."""

        if not isinstance(created_ms, int):
            return "--:--:--"
        return datetime.fromtimestamp(created_ms / 1000).strftime("%H:%M:%S")


def main() -> None:
    """Open the standalone clipboard history window."""

    ClipboardHistoryWindow().run()


if __name__ == "__main__":
    main()
