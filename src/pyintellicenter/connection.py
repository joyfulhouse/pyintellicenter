"""Connection module for Pentair IntelliCenter.

This module provides connection classes for communicating with Pentair IntelliCenter
pool control systems. Supports both TCP and WebSocket transports.

Architecture:
- ICTransportProtocol: Interface defining transport contract
- ICNotificationMixin: Shared notification handling logic
- ICProtocol: TCP transport using asyncio.Protocol (port 6681)
- ICWebSocketTransport: WebSocket transport using websockets library (port 6680)
- ICConnection: High-level wrapper with transport selection

Features:
- Dual transport support (TCP and WebSocket)
- Event-driven data handling
- asyncio.Future for request/response correlation
- Queue-based notification processing
- Automatic keepalive with configurable interval
"""

from __future__ import annotations

import asyncio
import contextlib
import inspect
import logging
from typing import TYPE_CHECKING, Any, Literal, Protocol, runtime_checkable

import orjson

from .exceptions import ICConnectionError, ICResponseError

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable

    # Callback types
    NotificationCallback = Callable[[dict[str, Any]], None | Awaitable[None]]
    DisconnectCallback = Callable[[Exception | None], None]

_LOGGER = logging.getLogger(__name__)

# Connection configuration
DEFAULT_TCP_PORT = 6681
DEFAULT_WEBSOCKET_PORT = 6680
RESPONSE_TIMEOUT = 30.0  # seconds to wait for a response
KEEPALIVE_INTERVAL = 90.0  # seconds between keepalive requests
CONNECTION_TIMEOUT = 10.0  # seconds to wait for initial connection
MAX_BUFFER_SIZE = 1024 * 1024  # 1MB max buffer to prevent DoS
DEFAULT_NOTIFICATION_QUEUE_SIZE = 100  # max queued notifications

# Backwards compatibility alias
DEFAULT_PORT = DEFAULT_TCP_PORT


@runtime_checkable
class ICTransportProtocol(Protocol):
    """Protocol defining the transport interface.

    Both TCP and WebSocket transports implement this interface,
    allowing ICConnection to work with either transparently.
    """

    @property
    def connected(self) -> bool:
        """Return True if connected."""
        ...

    async def send_request(
        self,
        command: str,
        request_timeout: float = RESPONSE_TIMEOUT,
        **kwargs: Any,
    ) -> dict[str, Any]:
        """Send a request and await response."""
        ...

    def close(self) -> None:
        """Close the connection."""
        ...

    def _start_notification_consumer(self) -> None:
        """Start the notification consumer task."""
        ...


class ICNotificationMixin:
    """Mixin providing shared notification handling logic.

    This mixin is used by both ICProtocol and ICWebSocketTransport to avoid
    code duplication for notification queue management and callback handling.
    """

    # These are defined in subclasses
    _notification_callback: NotificationCallback | None
    _is_async_callback: bool
    _notification_queue_size: int
    _notification_queue: asyncio.Queue[dict[str, Any]] | None
    _consumer_task: asyncio.Task[None] | None

    def _init_notification_mixin(
        self,
        notification_callback: NotificationCallback | None,
        notification_queue_size: int,
    ) -> None:
        """Initialize notification handling state."""
        self._notification_callback = notification_callback
        self._is_async_callback = (
            inspect.iscoroutinefunction(notification_callback) if notification_callback else False
        )
        self._notification_queue_size = notification_queue_size
        self._notification_queue = None
        self._consumer_task = None

    def _start_notification_consumer(self) -> None:
        """Start the notification consumer task if not already running."""
        if self._notification_queue is not None:
            return

        self._notification_queue = asyncio.Queue(maxsize=self._notification_queue_size)
        self._consumer_task = asyncio.create_task(
            self._notification_consumer(),
            name="ic-notification-consumer",
        )

    def _stop_notification_consumer(self) -> None:
        """Stop the notification consumer task."""
        if self._consumer_task and not self._consumer_task.done():
            self._consumer_task.cancel()
            self._consumer_task = None
        self._notification_queue = None

    def _dispatch_message(self, msg: dict[str, Any]) -> None:
        """Dispatch a parsed message to the appropriate handler."""
        if "response" in msg:
            self._handle_response(msg)
        elif msg.get("command") == "NotifyList":
            _LOGGER.debug("Received NotifyList notification")
            self._handle_notification(msg)
        else:
            _LOGGER.debug("Received unknown message type: %s", msg.get("command"))

    def _handle_response(self, msg: dict[str, Any]) -> None:
        """Handle a response message - implemented by subclasses."""
        raise NotImplementedError

    def _handle_notification(self, msg: dict[str, Any]) -> None:
        """Handle a NotifyList notification by queuing for processing."""
        if not self._notification_callback or self._notification_queue is None:
            return

        try:
            self._notification_queue.put_nowait(msg)
        except asyncio.QueueFull:
            _LOGGER.warning(
                "Notification queue full (%d items), dropping oldest message",
                self._notification_queue_size,
            )
            try:
                self._notification_queue.get_nowait()
                self._notification_queue.put_nowait(msg)
            except asyncio.QueueEmpty:
                _LOGGER.debug("Notification queue race - message dropped")

    async def _notification_consumer(self) -> None:
        """Process notifications from queue."""
        if self._notification_queue is None:
            raise RuntimeError("Notification queue not initialized")

        while True:
            try:
                msg = await self._notification_queue.get()
            except asyncio.CancelledError:
                _LOGGER.debug("Notification consumer cancelled")
                break

            try:
                if self._notification_callback:
                    if self._is_async_callback:
                        result = self._notification_callback(msg)
                        if result is not None:
                            await result
                    else:
                        self._notification_callback(msg)
            except Exception:
                _LOGGER.exception("Error in notification callback")
            finally:
                self._notification_queue.task_done()


class ICProtocol(ICNotificationMixin, asyncio.Protocol):
    """TCP transport using asyncio.Protocol for IntelliCenter communication.

    This class handles low-level TCP communication using the event-driven
    Protocol pattern. The event loop calls data_received() when data arrives.

    Message handling:
    - Response messages (with "response" field) resolve the pending Future
    - Notification messages (NotifyList) are queued for async processing
    - Messages are framed by \\r\\n terminator
    """

    def __init__(
        self,
        notification_callback: NotificationCallback | None = None,
        disconnect_callback: DisconnectCallback | None = None,
        *,
        notification_queue_size: int = DEFAULT_NOTIFICATION_QUEUE_SIZE,
    ) -> None:
        """Initialize the protocol.

        Args:
            notification_callback: Called when NotifyList notifications arrive
            disconnect_callback: Called when connection is lost
            notification_queue_size: Max queued notifications (default: 100)
        """
        self._init_notification_mixin(notification_callback, notification_queue_size)
        self._disconnect_callback = disconnect_callback

        # Transport (set by connection_made)
        self._transport: asyncio.Transport | None = None

        # Buffer for incomplete messages (bytearray for efficient appending)
        self._buffer = bytearray()

        # Request/response correlation via Future
        self._response_future: asyncio.Future[dict[str, Any]] | None = None

        # Message ID for pending request (used to validate responses)
        self._pending_message_id: str | None = None

        # Message ID counter
        self._message_id = 0

        # Connection state
        self._connected = False

    @property
    def connected(self) -> bool:
        """Return True if connected."""
        return self._connected and self._transport is not None

    def connection_made(self, transport: asyncio.BaseTransport) -> None:
        """Called when connection is established."""
        self._transport = transport  # type: ignore[assignment]
        self._connected = True
        self._buffer = bytearray()
        self._message_id = 0
        peername = transport.get_extra_info("peername")
        _LOGGER.debug("TCP connected to IntelliCenter at %s", peername)

        if self._notification_callback:
            self._start_notification_consumer()

    def connection_lost(self, exc: Exception | None) -> None:
        """Called when connection is lost."""
        self._connected = False
        self._transport = None

        self._stop_notification_consumer()

        if self._response_future and not self._response_future.done():
            if exc:
                self._response_future.set_exception(ICConnectionError(f"Connection lost: {exc}"))
            else:
                self._response_future.set_exception(ICConnectionError("Connection closed"))

        _LOGGER.debug("TCP connection lost: %s", exc)

        if self._disconnect_callback:
            self._disconnect_callback(exc)

    def data_received(self, data: bytes) -> None:
        """Called by event loop when data arrives."""
        self._buffer.extend(data)

        if len(self._buffer) > MAX_BUFFER_SIZE:
            _LOGGER.error("Buffer overflow - closing connection")
            if self._transport:
                self._transport.close()
            return

        while b"\r\n" in self._buffer:
            idx = self._buffer.index(b"\r\n")
            line = bytes(self._buffer[:idx])
            del self._buffer[: idx + 2]

            try:
                msg: dict[str, Any] = orjson.loads(line)
            except orjson.JSONDecodeError as err:
                _LOGGER.error("Invalid JSON received: %s", err)
                continue

            self._dispatch_message(msg)

    def _handle_response(self, msg: dict[str, Any]) -> None:
        """Handle a response message by resolving the pending Future."""
        msg_id = msg.get("messageID")

        if self._pending_message_id and msg_id == self._pending_message_id:
            if self._response_future and not self._response_future.done():
                self._response_future.set_result(msg)
            return

        _LOGGER.debug("Ignoring response for another client: %s", msg_id)

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
        """Send a request and await response via Future."""
        if not self.connected or not self._transport:
            raise ICConnectionError("Not connected")

        msg_id = self._next_message_id()
        request: dict[str, Any] = {
            "messageID": msg_id,
            "command": command,
            **kwargs,
        }

        # Create Future for this request (uses running event loop automatically)
        self._response_future = asyncio.Future()
        self._pending_message_id = msg_id

        try:
            packet = orjson.dumps(request) + b"\r\n"
            self._transport.write(packet)
            _LOGGER.debug("Sent TCP request: %s (ID: %s)", command, msg_id)

            async with asyncio.timeout(request_timeout):
                msg = await self._response_future

            response_code: str = msg.get("response", "unknown")
            if response_code != "200":
                raise ICResponseError(response_code)

            _LOGGER.debug("Received response for %s", msg.get("command"))
            return msg

        except TimeoutError:
            _LOGGER.error("Request %s timed out after %ss", command, request_timeout)
            raise

        finally:
            self._response_future = None
            self._pending_message_id = None

    def close(self) -> None:
        """Close the connection."""
        self._connected = False
        if self._transport:
            self._transport.close()


class ICWebSocketTransport(ICNotificationMixin):
    """WebSocket transport for IntelliCenter communication.

    Uses the websockets library for WebSocket connections to IntelliCenter.
    """

    def __init__(
        self,
        notification_callback: NotificationCallback | None = None,
        disconnect_callback: DisconnectCallback | None = None,
        *,
        notification_queue_size: int = DEFAULT_NOTIFICATION_QUEUE_SIZE,
    ) -> None:
        """Initialize the WebSocket transport.

        Args:
            notification_callback: Called when NotifyList notifications arrive
            disconnect_callback: Called when connection is lost
            notification_queue_size: Max queued notifications (default: 100)
        """
        self._init_notification_mixin(notification_callback, notification_queue_size)
        self._disconnect_callback = disconnect_callback

        self._ws: Any = None  # websockets.WebSocketClientProtocol
        self._connected = False
        self._message_id = 0

        # Request/response correlation
        self._response_future: asyncio.Future[dict[str, Any]] | None = None
        self._pending_message_id: str | None = None

        # Reader task for incoming messages
        self._reader_task: asyncio.Task[None] | None = None

    @property
    def connected(self) -> bool:
        """Return True if connected."""
        return self._connected and self._ws is not None

    async def connect(self, host: str, port: int) -> None:
        """Establish WebSocket connection.

        Args:
            host: IP address or hostname
            port: WebSocket port (default: 6680)
        """
        import websockets

        uri = f"ws://{host}:{port}"
        try:
            self._ws = await asyncio.wait_for(
                websockets.connect(uri),
                timeout=CONNECTION_TIMEOUT,
            )
            self._connected = True
            self._message_id = 0
            _LOGGER.debug("WebSocket connected to IntelliCenter at %s:%s", host, port)

            if self._notification_callback:
                self._start_notification_consumer()

            # Start reader task
            self._reader_task = asyncio.create_task(
                self._reader_loop(),
                name="ic-websocket-reader",
            )

        except TimeoutError as err:
            raise ICConnectionError(f"WebSocket connection to {host}:{port} timed out") from err
        except Exception as err:
            raise ICConnectionError(f"WebSocket connection failed: {err}") from err

    async def _reader_loop(self) -> None:
        """Read messages from WebSocket and dispatch them."""
        try:
            async for message in self._ws:
                data = message if isinstance(message, bytes) else message.encode()

                try:
                    msg: dict[str, Any] = orjson.loads(data)
                except orjson.JSONDecodeError as err:
                    _LOGGER.error("Invalid JSON received: %s", err)
                    continue

                self._dispatch_message(msg)

        except asyncio.CancelledError:
            _LOGGER.debug("WebSocket reader cancelled")
        except (OSError, ConnectionError) as err:
            _LOGGER.debug("WebSocket reader error: %s", err)
            self._handle_disconnect(err)

    def _handle_response(self, msg: dict[str, Any]) -> None:
        """Handle a response message by resolving the pending Future."""
        msg_id = msg.get("messageID")

        if self._pending_message_id and msg_id == self._pending_message_id:
            if self._response_future and not self._response_future.done():
                self._response_future.set_result(msg)
            return

        _LOGGER.debug("Ignoring response for another client: %s", msg_id)

    def _handle_disconnect(self, exc: Exception | None) -> None:
        """Handle disconnection."""
        self._connected = False
        self._ws = None

        self._stop_notification_consumer()

        if self._response_future and not self._response_future.done():
            if exc:
                self._response_future.set_exception(ICConnectionError(f"Connection lost: {exc}"))
            else:
                self._response_future.set_exception(ICConnectionError("Connection closed"))

        _LOGGER.debug("WebSocket connection lost: %s", exc)

        if self._disconnect_callback:
            self._disconnect_callback(exc)

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
        """Send a request and await response."""
        if not self.connected or not self._ws:
            raise ICConnectionError("Not connected")

        msg_id = self._next_message_id()
        request: dict[str, Any] = {
            "messageID": msg_id,
            "command": command,
            **kwargs,
        }

        # Create Future for this request (uses running event loop automatically)
        self._response_future = asyncio.Future()
        self._pending_message_id = msg_id

        try:
            # Send as text with \r\n terminator (same framing as TCP)
            packet = orjson.dumps(request).decode() + "\r\n"
            await self._ws.send(packet)
            _LOGGER.debug("Sent WebSocket request: %s (ID: %s)", command, msg_id)

            async with asyncio.timeout(request_timeout):
                msg = await self._response_future

            response_code: str = msg.get("response", "unknown")
            if response_code != "200":
                raise ICResponseError(response_code)

            _LOGGER.debug("Received response for %s", msg.get("command"))
            return msg

        except TimeoutError:
            _LOGGER.error("Request %s timed out after %ss", command, request_timeout)
            raise

        finally:
            self._response_future = None
            self._pending_message_id = None

    def close(self) -> None:
        """Close the connection."""
        self._connected = False

        if self._reader_task and not self._reader_task.done():
            self._reader_task.cancel()
            self._reader_task = None

        self._stop_notification_consumer()

        if self._ws:
            # Schedule close in background (can't await in sync method)
            asyncio.create_task(self._async_close())

    async def _async_close(self) -> None:
        """Close WebSocket connection asynchronously."""
        if self._ws:
            with contextlib.suppress(Exception):
                await self._ws.close()
            self._ws = None


# Type alias for transport selection
TransportType = Literal["tcp", "websocket"]


class ICConnection:
    """High-level connection wrapper for IntelliCenter.

    Supports both TCP and WebSocket transports. Use the `transport` parameter
    to select which protocol to use.

    Example:
        # TCP connection (default)
        async with ICConnection("192.168.1.100") as conn:
            response = await conn.send_request("GetParamList", ...)

        # WebSocket connection
        async with ICConnection("192.168.1.100", transport="websocket") as conn:
            response = await conn.send_request("GetParamList", ...)
    """

    def __init__(
        self,
        host: str,
        port: int | None = None,
        response_timeout: float = RESPONSE_TIMEOUT,
        keepalive_interval: float = KEEPALIVE_INTERVAL,
        notification_queue_size: int = DEFAULT_NOTIFICATION_QUEUE_SIZE,
        *,
        transport: TransportType = "tcp",
    ) -> None:
        """Initialize connection configuration.

        Args:
            host: IP address or hostname of IntelliCenter
            port: Port number (default: 6681 for TCP, 6680 for WebSocket)
            response_timeout: Seconds to wait for response (default: 30)
            keepalive_interval: Seconds between keepalive requests (default: 90)
            notification_queue_size: Max queued notifications (default: 100)
            transport: Transport type - "tcp" or "websocket" (default: "tcp")
        """
        self._host = host
        self._transport_type = transport
        self._port = (
            port
            if port is not None
            else (DEFAULT_WEBSOCKET_PORT if transport == "websocket" else DEFAULT_TCP_PORT)
        )
        self._response_timeout = response_timeout
        self._keepalive_interval = keepalive_interval
        self._notification_queue_size = notification_queue_size

        # Transport instance (created on connect)
        self._protocol: ICProtocol | ICWebSocketTransport | None = None

        # Callbacks
        self._notification_callback: NotificationCallback | None = None
        self._disconnect_callback: DisconnectCallback | None = None

        # Flow control: one request at a time
        self._request_lock = asyncio.Lock()

        # Keepalive task
        self._keepalive_task: asyncio.Task[None] | None = None

    def __repr__(self) -> str:
        """Return a detailed string representation for debugging."""
        return (
            f"ICConnection(host={self._host!r}, port={self._port}, "
            f"transport={self._transport_type!r}, connected={self.connected})"
        )

    @property
    def host(self) -> str:
        """Return the host address."""
        return self._host

    @property
    def port(self) -> int:
        """Return the port number."""
        return self._port

    @property
    def transport_type(self) -> TransportType:
        """Return the transport type."""
        return self._transport_type

    @property
    def connected(self) -> bool:
        """Return True if connected."""
        return self._protocol is not None and self._protocol.connected

    def set_notification_callback(self, callback: NotificationCallback | None) -> None:
        """Set callback for NotifyList push notifications.

        Args:
            callback: Function to call with notification data, or None to clear.
        """
        self._notification_callback = callback
        if self._protocol:
            self._protocol._notification_callback = callback
            self._protocol._is_async_callback = (
                inspect.iscoroutinefunction(callback) if callback else False
            )
            if callback and self._protocol.connected and self._protocol._notification_queue is None:
                self._protocol._start_notification_consumer()

    def set_disconnect_callback(self, callback: DisconnectCallback | None) -> None:
        """Set callback for disconnection events.

        Args:
            callback: Function to call on disconnect, or None to clear.
        """
        self._disconnect_callback = callback

    def _on_disconnect(self, exc: Exception | None) -> None:
        """Internal disconnect handler that wraps user callback."""
        if self._keepalive_task and not self._keepalive_task.done():
            self._keepalive_task.cancel()
            self._keepalive_task = None

        if self._disconnect_callback:
            self._disconnect_callback(exc)

    async def connect(self) -> None:
        """Establish connection to IntelliCenter.

        Uses the transport type specified at initialization.

        Raises:
            ICConnectionError: If connection fails or times out.
        """
        if self.connected:
            return

        if self._transport_type == "websocket":
            await self._connect_websocket()
        else:
            await self._connect_tcp()

        # Start keepalive task
        self._keepalive_task = asyncio.create_task(self._keepalive_loop())

    async def _connect_tcp(self) -> None:
        """Establish TCP connection."""
        try:
            loop = asyncio.get_running_loop()

            async with asyncio.timeout(CONNECTION_TIMEOUT):
                _, protocol = await loop.create_connection(
                    lambda: ICProtocol(
                        notification_callback=self._notification_callback,
                        disconnect_callback=self._on_disconnect,
                        notification_queue_size=self._notification_queue_size,
                    ),
                    self._host,
                    self._port,
                )

            self._protocol = protocol
            _LOGGER.debug("Connected to IC via TCP at %s:%s", self._host, self._port)

        except TimeoutError as err:
            raise ICConnectionError(
                f"TCP connection to {self._host}:{self._port} timed out"
            ) from err
        except OSError as err:
            raise ICConnectionError(
                f"Failed to connect to {self._host}:{self._port}: {err}"
            ) from err

    async def _connect_websocket(self) -> None:
        """Establish WebSocket connection."""
        transport = ICWebSocketTransport(
            notification_callback=self._notification_callback,
            disconnect_callback=self._on_disconnect,
            notification_queue_size=self._notification_queue_size,
        )
        await transport.connect(self._host, self._port)
        self._protocol = transport
        _LOGGER.debug("Connected to IC via WebSocket at %s:%s", self._host, self._port)

    async def disconnect(self) -> None:
        """Close the connection gracefully."""
        if self._keepalive_task and not self._keepalive_task.done():
            self._keepalive_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._keepalive_task
            self._keepalive_task = None

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
                        request_timeout=10.0,
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
