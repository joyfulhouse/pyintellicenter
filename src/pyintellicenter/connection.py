"""asyncio.Protocol-based connection for Pentair IntelliCenter.

This module provides an event-driven connection to Pentair IntelliCenter pool
control systems using asyncio.Protocol. The Protocol pattern uses callbacks
triggered by the event loop, eliminating the need for reader loops.

Architecture:
- ICProtocol: Low-level asyncio.Protocol handling TCP communication
- ICConnection: High-level wrapper providing async context manager interface

Features:
- Event-driven data handling via data_received() callback
- asyncio.Future for request/response correlation
- Automatic message framing (messages end with \\r\\n)
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
MAX_BUFFER_SIZE = 1024 * 1024  # 1MB max buffer to prevent DoS


class ICProtocol(asyncio.Protocol):
    """asyncio.Protocol implementation for IntelliCenter communication.

    This class handles low-level TCP communication using the event-driven
    Protocol pattern. The event loop calls data_received() when data arrives,
    eliminating the need for reader loops.

    Message handling:
    - Response messages (with "response" field) resolve the pending Future
    - Notification messages (NotifyList) trigger the notification callback
    - Messages are framed by \\r\\n terminator
    """

    def __init__(
        self,
        notification_callback: NotificationCallback | None = None,
        disconnect_callback: DisconnectCallback | None = None,
    ) -> None:
        """Initialize the protocol.

        Args:
            notification_callback: Called when NotifyList notifications arrive
            disconnect_callback: Called when connection is lost
        """
        self._notification_callback = notification_callback
        self._disconnect_callback = disconnect_callback

        # Transport (set by connection_made)
        self._transport: asyncio.Transport | None = None

        # Buffer for incomplete messages
        self._buffer = b""

        # Request/response correlation via Future
        self._response_future: asyncio.Future[dict[str, Any]] | None = None

        # Message ID counter
        self._message_id = 0

        # Connection state
        self._connected = False

        # Event loop reference (for creating Futures)
        self._loop: asyncio.AbstractEventLoop | None = None

    @property
    def connected(self) -> bool:
        """Return True if connected."""
        return self._connected and self._transport is not None

    def connection_made(self, transport: asyncio.BaseTransport) -> None:
        """Called when connection is established.

        Args:
            transport: The transport representing the connection
        """
        self._transport = transport  # type: ignore[assignment]
        self._connected = True
        self._loop = asyncio.get_running_loop()
        self._buffer = b""
        self._message_id = 0
        peername = transport.get_extra_info("peername")
        _LOGGER.debug("Connected to IntelliCenter at %s", peername)

    def connection_lost(self, exc: Exception | None) -> None:
        """Called when connection is lost.

        Args:
            exc: Exception if connection was lost due to error, None if clean close
        """
        self._connected = False
        self._transport = None

        # Cancel any pending request
        if self._response_future and not self._response_future.done():
            if exc:
                self._response_future.set_exception(ICConnectionError(f"Connection lost: {exc}"))
            else:
                self._response_future.set_exception(ICConnectionError("Connection closed"))

        _LOGGER.debug("Connection lost: %s", exc)

        # Notify disconnect callback
        if self._disconnect_callback:
            self._disconnect_callback(exc)

    def data_received(self, data: bytes) -> None:
        """Called by event loop when data arrives - no loop needed.

        This is the core of the Protocol pattern. The event loop triggers
        this callback whenever data is available, eliminating reader loops.

        Args:
            data: Raw bytes received from the connection
        """
        self._buffer += data

        # Protect against buffer overflow (DoS prevention)
        if len(self._buffer) > MAX_BUFFER_SIZE:
            _LOGGER.error("Buffer overflow - closing connection")
            if self._transport:
                self._transport.close()
            return

        # Process complete messages (terminated by \r\n)
        while b"\r\n" in self._buffer:
            line, self._buffer = self._buffer.split(b"\r\n", 1)

            try:
                msg: dict[str, Any] = orjson.loads(line)
            except orjson.JSONDecodeError as err:
                _LOGGER.error("Invalid JSON received: %s", err)
                continue

            # Dispatch based on message type
            if "response" in msg:
                # Response to a request - resolve the pending Future
                self._handle_response(msg)

            elif msg.get("command") == "NotifyList":
                # Push notification from IntelliCenter
                _LOGGER.debug("Received NotifyList notification")
                self._handle_notification(msg)

            else:
                _LOGGER.debug("Received unknown message type: %s", msg.get("command"))

    def _handle_response(self, msg: dict[str, Any]) -> None:
        """Handle a response message by resolving the pending Future.

        Args:
            msg: The parsed response message
        """
        if self._response_future and not self._response_future.done():
            self._response_future.set_result(msg)
        else:
            _LOGGER.warning("Received response with no pending request: %s", msg)

    def _handle_notification(self, msg: dict[str, Any]) -> None:
        """Handle a NotifyList notification.

        Args:
            msg: The parsed notification message
        """
        if not self._notification_callback:
            return

        if inspect.iscoroutinefunction(self._notification_callback):
            # Schedule async callback
            if self._loop:
                self._loop.create_task(self._notification_callback(msg))
        else:
            # Call sync callback directly
            self._notification_callback(msg)

    def _next_message_id(self) -> str:
        """Generate the next message ID."""
        self._message_id += 1
        return str(self._message_id)

    async def send_request(
        self,
        command: str,
        request_timeout: float = RESPONSE_TIMEOUT,
        **kwargs: Any,
    ) -> dict[str, Any]:
        """Send a request and await response via Future.

        This method creates a Future, sends the request, and awaits the Future.
        The data_received() callback resolves the Future when response arrives.

        Args:
            command: The command name (e.g., "GetParamList", "SetParamList")
            request_timeout: Seconds to wait for response
            **kwargs: Additional fields to include in the request

        Returns:
            The response message dictionary.

        Raises:
            ICConnectionError: If not connected or connection fails.
            ICResponseError: If IntelliCenter returns an error response.
            TimeoutError: If no response received within timeout.
        """
        if not self.connected or not self._transport:
            raise ICConnectionError("Not connected")

        if not self._loop:
            self._loop = asyncio.get_running_loop()

        # Build request with message ID
        request: dict[str, Any] = {
            "messageID": self._next_message_id(),
            "command": command,
            **kwargs,
        }

        # Create Future for response
        self._response_future = self._loop.create_future()

        try:
            # Send request
            packet = orjson.dumps(request) + b"\r\n"
            self._transport.write(packet)
            _LOGGER.debug("Sent request: %s (ID: %s)", command, request["messageID"])

            # Await response via Future (resolved by data_received)
            async with asyncio.timeout(request_timeout):
                msg = await self._response_future

            # Check response code
            response_code: str = msg.get("response", "unknown")
            if response_code != "200":
                raise ICResponseError(response_code)

            _LOGGER.debug("Received response for %s", msg.get("command"))
            return dict(msg)

        except TimeoutError:
            _LOGGER.error("Request %s timed out after %ss", command, request_timeout)
            raise

        finally:
            self._response_future = None

    def close(self) -> None:
        """Close the connection."""
        self._connected = False
        if self._transport:
            self._transport.close()


class ICConnection:
    """High-level connection wrapper for IntelliCenter.

    This class provides a convenient async context manager interface
    around the low-level ICProtocol.

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

        # Protocol instance (created on connect)
        self._protocol: ICProtocol | None = None

        # Callbacks
        self._notification_callback: NotificationCallback | None = None
        self._disconnect_callback: DisconnectCallback | None = None

        # Flow control: one request at a time
        self._request_lock = asyncio.Lock()

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
        return self._protocol is not None and self._protocol.connected

    def set_notification_callback(self, callback: NotificationCallback | None) -> None:
        """Set callback for NotifyList push notifications.

        The callback can be either sync or async. If async, it will be scheduled.

        Args:
            callback: Function to call with notification data, or None to clear.
        """
        self._notification_callback = callback
        if self._protocol:
            self._protocol._notification_callback = callback

    def set_disconnect_callback(self, callback: DisconnectCallback | None) -> None:
        """Set callback for disconnection events.

        Args:
            callback: Function to call on disconnect, or None to clear.
        """
        self._disconnect_callback = callback

    def _on_disconnect(self, exc: Exception | None) -> None:
        """Internal disconnect handler that wraps user callback."""
        # Cancel keepalive
        if self._keepalive_task and not self._keepalive_task.done():
            self._keepalive_task.cancel()
            self._keepalive_task = None

        # Call user callback
        if self._disconnect_callback:
            self._disconnect_callback(exc)

    async def connect(self) -> None:
        """Establish connection to IntelliCenter.

        Uses asyncio.create_connection() to establish connection and
        instantiate the ICProtocol.

        Raises:
            ICConnectionError: If connection fails or times out.
        """
        if self.connected:
            return

        try:
            loop = asyncio.get_running_loop()

            async with asyncio.timeout(CONNECTION_TIMEOUT):
                _, protocol = await loop.create_connection(
                    lambda: ICProtocol(
                        notification_callback=self._notification_callback,
                        disconnect_callback=self._on_disconnect,
                    ),
                    self._host,
                    self._port,
                )

            self._protocol = protocol
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
        # Cancel keepalive task
        if self._keepalive_task and not self._keepalive_task.done():
            self._keepalive_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._keepalive_task
            self._keepalive_task = None

        # Close protocol
        if self._protocol:
            self._protocol.close()
            self._protocol = None

        _LOGGER.debug("Disconnected from IC")

    async def __aenter__(self) -> ICConnection:
        """Async context manager entry."""
        await self.connect()
        return self

    async def __aexit__(self, exc_type: Any, exc_val: Any, exc_tb: Any) -> None:
        """Async context manager exit."""
        await self.disconnect()

    async def send_request(
        self,
        command: str,
        request_timeout: float | None = None,
        **kwargs: Any,
    ) -> dict[str, Any]:
        """Send a request and wait for the response.

        This method handles flow control (one request at a time) and
        delegates to the protocol's send_request.

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
        if not self._protocol or not self._protocol.connected:
            raise ICConnectionError("Not connected")

        effective_timeout = (
            request_timeout if request_timeout is not None else self._response_timeout
        )

        # Flow control: one request at a time (IntelliCenter limitation)
        async with self._request_lock:
            return await self._protocol.send_request(
                command, request_timeout=effective_timeout, **kwargs
            )

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
                    break
                except ICConnectionError as err:
                    _LOGGER.warning("Keepalive failed: %s", err)
                    break

        except asyncio.CancelledError:
            _LOGGER.debug("Keepalive task cancelled")
