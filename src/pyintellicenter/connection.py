"""Modern asyncio connection for Pentair IntelliCenter.

This module provides a clean, modern asyncio streams-based connection
to Pentair IntelliCenter pool control systems. It replaces the legacy
Protocol-based implementation with simpler async/await patterns.

Features:
- asyncio.open_connection() for TCP streams
- Automatic message framing via readline() (messages end with \\r\\n)
- asyncio.timeout() for clean timeout handling
- asyncio.Lock for flow control (one request at a time)
- Automatic keepalive with configurable interval
- Support for both sync and async notification callbacks
"""

from __future__ import annotations

import asyncio
import contextlib
import inspect
import logging
from typing import TYPE_CHECKING, Any

import orjson

from .exceptions import ICConnectionError, ICResponseError

if TYPE_CHECKING:
    from asyncio import StreamReader, StreamWriter
    from collections.abc import Awaitable, Callable

    # Callback types
    NotificationCallback = Callable[[dict[str, Any]], None | Awaitable[None]]
    DisconnectCallback = Callable[[Exception | None], None]

_LOGGER = logging.getLogger(__name__)

# Connection configuration
DEFAULT_PORT = 6681
RESPONSE_TIMEOUT = 30.0  # seconds to wait for a response
KEEPALIVE_INTERVAL = 90.0  # seconds between keepalive requests
CONNECTION_TIMEOUT = 10.0  # seconds to wait for initial connection


class ICConnection:
    """Modern asyncio connection to IntelliCenter.

    This class manages the TCP connection and provides a simple async interface
    for sending requests and receiving responses/notifications.

    Example:
        async with ICConnection("192.168.1.100") as conn:
            response = await conn.send_request(
                "GetParamList",
                objectList=[{"objnam": "INCR", "keys": ["VER"]}]
            )
            print(response)
    """

    def __init__(
        self,
        host: str,
        port: int = DEFAULT_PORT,
        response_timeout: float = RESPONSE_TIMEOUT,
        keepalive_interval: float = KEEPALIVE_INTERVAL,
    ) -> None:
        """Initialize connection configuration.

        Args:
            host: IP address or hostname of IntelliCenter
            port: TCP port (default: 6681)
            response_timeout: Seconds to wait for response (default: 30)
            keepalive_interval: Seconds between keepalive requests (default: 90)
        """
        self._host = host
        self._port = port
        self._response_timeout = response_timeout
        self._keepalive_interval = keepalive_interval

        # Connection state
        self._reader: StreamReader | None = None
        self._writer: StreamWriter | None = None
        self._connected = False

        # Flow control: one request at a time
        self._request_lock = asyncio.Lock()

        # Message ID counter
        self._message_id = 0

        # Callbacks (support both sync and async)
        self._notification_callback: NotificationCallback | None = None
        self._disconnect_callback: DisconnectCallback | None = None

        # Keepalive task
        self._keepalive_task: asyncio.Task[None] | None = None

    def __repr__(self) -> str:
        """Return a detailed string representation for debugging."""
        return f"ICConnection(host={self._host!r}, port={self._port}, connected={self.connected})"

    @property
    def host(self) -> str:
        """Return the host address."""
        return self._host

    @property
    def port(self) -> int:
        """Return the port number."""
        return self._port

    @property
    def connected(self) -> bool:
        """Return True if connected."""
        return self._connected and self._writer is not None and not self._writer.is_closing()

    def set_notification_callback(self, callback: NotificationCallback | None) -> None:
        """Set callback for NotifyList push notifications.

        The callback can be either sync or async. If async, it will be awaited.

        Args:
            callback: Function to call with notification data, or None to clear.
        """
        self._notification_callback = callback

    def set_disconnect_callback(self, callback: DisconnectCallback | None) -> None:
        """Set callback for disconnection events.

        Args:
            callback: Function to call on disconnect, or None to clear.
        """
        self._disconnect_callback = callback

    async def connect(self) -> None:
        """Establish connection to IntelliCenter.

        Raises:
            ICConnectionError: If connection fails or times out.
        """
        if self.connected:
            return

        try:
            async with asyncio.timeout(CONNECTION_TIMEOUT):
                self._reader, self._writer = await asyncio.open_connection(self._host, self._port)
            self._connected = True
            self._message_id = 0
            _LOGGER.debug("Connected to IC at %s:%s", self._host, self._port)

            # Start keepalive task
            self._keepalive_task = asyncio.create_task(self._keepalive_loop())

        except TimeoutError as err:
            raise ICConnectionError(f"Connection to {self._host}:{self._port} timed out") from err
        except OSError as err:
            raise ICConnectionError(
                f"Failed to connect to {self._host}:{self._port}: {err}"
            ) from err

    async def disconnect(self) -> None:
        """Close the connection gracefully."""
        self._connected = False

        # Cancel keepalive task
        if self._keepalive_task and not self._keepalive_task.done():
            self._keepalive_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._keepalive_task
            self._keepalive_task = None

        # Close writer
        if self._writer:
            self._writer.close()
            with contextlib.suppress(Exception):
                await self._writer.wait_closed()
            self._writer = None
            self._reader = None

        _LOGGER.debug("Disconnected from IC")

    async def __aenter__(self) -> ICConnection:
        """Async context manager entry."""
        await self.connect()
        return self

    async def __aexit__(self, exc_type: Any, exc_val: Any, exc_tb: Any) -> None:
        """Async context manager exit."""
        await self.disconnect()

    def _next_message_id(self) -> str:
        """Generate the next message ID."""
        self._message_id += 1
        return str(self._message_id)

    async def _read_message(self) -> dict[str, Any]:
        """Read a single JSON message from the connection.

        Returns:
            Parsed JSON message as a dictionary.

        Raises:
            ICConnectionError: If connection is closed or read fails.
        """
        if not self._reader:
            raise ICConnectionError("Not connected")

        try:
            line = await self._reader.readline()
            if not line:
                raise ICConnectionError("Connection closed by remote")

            result: dict[str, Any] = orjson.loads(line)
            return result

        except orjson.JSONDecodeError as err:
            _LOGGER.error("Invalid JSON received: %s", err)
            raise ICConnectionError(f"Invalid JSON: {err}") from err

    async def _write_message(self, message: dict[str, Any]) -> None:
        """Write a JSON message to the connection.

        Args:
            message: Dictionary to send as JSON.

        Raises:
            ICConnectionError: If connection is closed or write fails.
        """
        if not self._writer:
            raise ICConnectionError("Not connected")

        try:
            packet = orjson.dumps(message) + b"\r\n"
            self._writer.write(packet)
            await self._writer.drain()
        except OSError as err:
            raise ICConnectionError(f"Write failed: {err}") from err

    async def _invoke_notification_callback(self, msg: dict[str, Any]) -> None:
        """Invoke the notification callback, handling both sync and async callbacks."""
        if not self._notification_callback:
            return

        if inspect.iscoroutinefunction(self._notification_callback):
            await self._notification_callback(msg)
        else:
            self._notification_callback(msg)

    async def send_request(
        self,
        command: str,
        request_timeout: float | None = None,
        **kwargs: Any,
    ) -> dict[str, Any]:
        """Send a request and wait for the response.

        This method handles flow control (one request at a time) and
        processes any notifications received while waiting for the response.

        Args:
            command: The command name (e.g., "GetParamList", "SetParamList")
            request_timeout: Override response timeout (default: use instance timeout)
            **kwargs: Additional fields to include in the request

        Returns:
            The response message dictionary.

        Raises:
            ICConnectionError: If not connected or connection fails.
            ICResponseError: If IntelliCenter returns an error response.
            TimeoutError: If no response received within timeout.
        """
        if not self.connected:
            raise ICConnectionError("Not connected")

        # Build request with message ID
        request: dict[str, Any] = {
            "messageID": self._next_message_id(),
            "command": command,
            **kwargs,
        }

        effective_timeout = (
            request_timeout if request_timeout is not None else self._response_timeout
        )

        # Flow control: one request at a time
        async with self._request_lock:
            await self._write_message(request)
            _LOGGER.debug("Sent request: %s (ID: %s)", command, request["messageID"])

            # Read until we get a response (not a notification)
            try:
                async with asyncio.timeout(effective_timeout):
                    while True:
                        msg = await self._read_message()

                        # Check if this is a response (has "response" field)
                        if "response" in msg:
                            response_code: str = msg.get("response", "unknown")
                            if response_code != "200":
                                raise ICResponseError(response_code)
                            _LOGGER.debug("Received response for %s", msg.get("command"))
                            return dict(msg)

                        # It's a notification (NotifyList) - process and continue
                        if msg.get("command") == "NotifyList":
                            _LOGGER.debug("Received NotifyList notification")
                            await self._invoke_notification_callback(msg)

            except TimeoutError:
                _LOGGER.error("Request %s timed out after %ss", command, effective_timeout)
                raise

    async def send_command(
        self,
        command: str,
        **kwargs: Any,
    ) -> dict[str, Any]:
        """Convenience method for send_request.

        Args:
            command: The command name
            **kwargs: Additional fields for the request

        Returns:
            The response message dictionary.
        """
        return await self.send_request(command, **kwargs)

    async def _keepalive_loop(self) -> None:
        """Send periodic keepalive requests to maintain connection health."""
        try:
            while self.connected:
                await asyncio.sleep(self._keepalive_interval)

                if not self.connected:
                    break

                try:
                    _LOGGER.debug("Sending keepalive request")
                    await self.send_request(
                        "GetParamList",
                        request_timeout=10.0,  # Shorter timeout for keepalive
                        condition="OBJTYP=SYSTEM",
                        objectList=[{"objnam": "INCR", "keys": ["MODE"]}],
                    )
                except TimeoutError:
                    _LOGGER.warning("Keepalive timeout - connection may be dead")
                    await self._handle_connection_lost(ICConnectionError("Keepalive timeout"))
                    break
                except ICConnectionError as err:
                    _LOGGER.warning("Keepalive failed: %s", err)
                    await self._handle_connection_lost(err)
                    break

        except asyncio.CancelledError:
            _LOGGER.debug("Keepalive task cancelled")

    async def _handle_connection_lost(self, exc: Exception | None) -> None:
        """Handle connection loss."""
        self._connected = False

        if self._disconnect_callback:
            self._disconnect_callback(exc)

        await self.disconnect()
