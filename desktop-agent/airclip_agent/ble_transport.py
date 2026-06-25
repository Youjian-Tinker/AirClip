"""BLE central transport for the AirClip desktop agent."""

from __future__ import annotations

import asyncio
import contextlib
from collections.abc import Awaitable, Callable

from bleak import BleakClient, BleakScanner

SERVICE_UUID = "7b1f0001-8f5d-4d3a-9f4c-1d76b8f0a901"
RX_UUID = "7b1f0002-8f5d-4d3a-9f4c-1d76b8f0a901"
TX_UUID = "7b1f0003-8f5d-4d3a-9f4c-1d76b8f0a901"
DEFAULT_DEVICE_NAME = "AirClip-Relay"

NotifyHandler = Callable[[bytes], Awaitable[None]]


class AirClipBleTransport:
    """Connects to the ESP32 relay and exposes byte send/read operations."""

    def __init__(self, device_name: str = DEFAULT_DEVICE_NAME) -> None:
        """Create a BLE transport that searches for the named relay."""

        self.device_name = device_name
        self._client: BleakClient | None = None
        self._notify_handler: NotifyHandler | None = None

    async def connect(self, notify_handler: NotifyHandler, timeout: float = 20.0) -> None:
        """Scan for the relay, connect, and subscribe to notifications with retry."""

        device = await BleakScanner.find_device_by_filter(
            lambda found, _: found.name == self.device_name,
            timeout=timeout,
        )
        if device is None:
            raise RuntimeError(f"BLE relay '{self.device_name}' was not found")

        self._notify_handler = notify_handler
        last_error: Exception | None = None

        for attempt in range(3):
            self._client = BleakClient(
                device,
                services=[SERVICE_UUID],
                disconnected_callback=self._on_disconnect,
            )
            try:
                await self._client.connect()
                await asyncio.sleep(1.0)
                services = self._client.services
                self._print_services(services)
                tx_characteristic = services.get_characteristic(TX_UUID)
                if tx_characteristic is None:
                    raise RuntimeError(f"BLE relay is missing TX characteristic {TX_UUID}")
                await self._client.start_notify(tx_characteristic, self._on_notify)
                return
            except Exception as exc:
                last_error = exc
                print(f"BLE connect attempt {attempt + 1} failed: {exc!r}")
                if self._client is not None:
                    with contextlib.suppress(Exception):
                        await self._client.disconnect()
                self._client = None
                await asyncio.sleep(1.0)

        raise RuntimeError(f"failed to connect to BLE relay after retries: {last_error}")

    async def disconnect(self) -> None:
        """Stop notifications and close the BLE connection if it exists."""

        if self._client is None:
            return
        try:
            if self._client.is_connected:
                await self._client.stop_notify(TX_UUID)
                await self._client.disconnect()
        finally:
            self._client = None

    async def send(self, payload: bytes, response: bool = True) -> None:
        """Write one protocol frame, using response writes unless fast mode is requested."""

        if self._client is None or not self._client.is_connected:
            raise RuntimeError("BLE relay is not connected")
        if response:
            await self._client.write_gatt_char(RX_UUID, payload, response=True)
            return
        try:
            await self._client.write_gatt_char(RX_UUID, payload, response=False)
        except Exception:
            await self._client.write_gatt_char(RX_UUID, payload, response=True)

    def is_connected(self) -> bool:
        """Return whether the underlying BLE client is currently connected."""

        return self._client is not None and self._client.is_connected

    def _print_services(self, services) -> None:
        """Print discovered GATT details to diagnose Windows BLE cache issues."""

        print("discovered BLE services:")
        for service in services:
            print(f"  service {service.uuid}")
            for characteristic in service.characteristics:
                properties = ",".join(characteristic.properties)
                print(
                    f"    char {characteristic.uuid} "
                    f"handle={characteristic.handle} properties={properties}"
                )
                for descriptor in characteristic.descriptors:
                    print(f"      desc {descriptor.uuid} handle={descriptor.handle}")

    def _on_notify(self, _: int, data: bytearray) -> None:
        """Forward BLE notification bytes into the async application handler."""

        if self._notify_handler is None:
            return
        asyncio.create_task(self._notify_handler(bytes(data)))

    def _on_disconnect(self, _) -> None:
        """Log unexpected disconnects so relay stability is visible in agent logs."""

        print("BLE relay disconnected")
