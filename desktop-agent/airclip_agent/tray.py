"""Windows tray controller for AirClip."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

from PIL import Image
import pystray


class TrayController:
    """Provides a small system tray menu for clipboard sharing controls."""

    def __init__(
        self,
        is_enabled: Callable[[], bool],
        set_enabled: Callable[[bool], None],
        clear_history: Callable[[], None],
        open_history: Callable[[], None],
        stop: Callable[[], None],
    ) -> None:
        """Create a tray controller backed by callbacks from the agent."""

        self._is_enabled = is_enabled
        self._set_enabled = set_enabled
        self._clear_history = clear_history
        self._open_history = open_history
        self._stop = stop
        self._icon = pystray.Icon(
            "AirClip",
            self._build_icon(True),
            "AirClip",
            menu=pystray.Menu(
                pystray.MenuItem(
                    "启用共享剪贴板",
                    self._enable,
                    checked=lambda _: self._is_enabled(),
                ),
                pystray.MenuItem(
                    "暂停共享剪贴板",
                    self._disable,
                    checked=lambda _: not self._is_enabled(),
                ),
                pystray.MenuItem("查看历史", self._history),
                pystray.MenuItem("清空历史", self._clear),
                pystray.MenuItem("退出", self._quit),
            ),
        )

    def run_detached(self) -> None:
        """Start the tray icon in a background thread."""

        self._icon.run_detached()
        print("tray icon started")

    def stop(self) -> None:
        """Remove the tray icon if it is currently running."""

        self._icon.stop()

    def refresh(self) -> None:
        """Update the tray title and icon to reflect sharing state."""

        enabled = self._is_enabled()
        self._icon.title = "AirClip 已启用" if enabled else "AirClip 已暂停"
        self._icon.icon = self._build_icon(enabled)
        if self._icon.visible:
            self._icon.notify(self._icon.title, "AirClip")

    def _enable(self, *_) -> None:
        """Enable sharing from the tray menu."""

        self._set_enabled(True)
        self.refresh()

    def _disable(self, *_) -> None:
        """Disable sharing from the tray menu."""

        self._set_enabled(False)
        self.refresh()

    def _clear(self, *_) -> None:
        """Clear local history from the tray menu."""

        self._clear_history()

    def _history(self, *_) -> None:
        """Open the clipboard history viewer from the tray menu."""

        self._open_history()

    def _quit(self, *_) -> None:
        """Ask the agent to stop from the tray menu."""

        self._stop()
        self._icon.stop()

    def _build_icon(self, enabled: bool) -> Image.Image:
        """Load the bundled AirClip icon and dim it when sharing is paused."""

        icon_path = Path(__file__).with_name("assets") / "airclip-icon.jpg"
        image = Image.open(icon_path).convert("RGBA").resize((64, 64), Image.Resampling.LANCZOS)
        if not enabled:
            alpha = image.getchannel("A")
            image = image.convert("LA").convert("RGBA")
            image.putalpha(alpha)
        return image
