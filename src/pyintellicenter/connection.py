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
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Literal, Protocol, runtime_checkable

import orjson
from websockets.exceptions import WebSocketException

from .exceptions import ICConnectionError, ICResponseError, ICTimeoutError

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable

    # Callback types
    AfterWriteCallback = Callable[[int], None]
    BeforeWriteCallback = Callable[[int, float], None]
    NotificationCallback = Callable[[dict[str, Any]], None | Awaitable[None]]
    NotificationObserver = Callable[[int, dict[str, Any]], None]
    DisconnectCallback = Callable[[Exception | None], None]

_LOGGER = logging.getLogger(__name__)

# Connection configuration
DEFAULT_TCP_PORT = 6681
DEFAULT_WEBSOCKET_PORT = 6680
RESPONSE_TIMEOUT = 30.0  # seconds to wait for a response
KEEPALIVE_INTERVAL = 90.0  # seconds between keepalive requests
KEEPALIVE_TIMEOUT = 10.0  # seconds to wait for a keepalive response
KEEPALIVE_MAX_FAILURES = 3  # consecutive missed keepalives before the link is dead
CONNECTION_TIMEOUT = 10.0  # seconds to wait for initial connection
MAX_BUFFER_SIZE = 1024 * 1024  # 1MB max buffer to prevent DoS
DEFAULT_NOTIFICATION_QUEUE_SIZE = 100  # max queued notifications
NOTIFICATION_DROP_LOG_INTERVAL = 100  # summarize queue-overflow drops every N drops

# Request fields owned by the protocol layer; callers must not override them.
# messageID correlates the response and command routes it - overriding either
# via **kwargs guarantees a timeout or a misrouted request.
_RESERVED_REQUEST_FIELDS = frozenset({"messageID", "command"})

# Backwards compatibility alias
DEFAULT_PORT = DEFAULT_TCP_PORT


async def _await_shutdown_task(task: asyncio.Task[Any] | None) -> None:
    """Await a shutdown task's completion without masking the caller.

    ``asyncio.wait`` never raises the child's outcome, so a CancelledError
    surfacing here can only be the *caller's* own cancellation and must
    propagate - ``await task`` under ``suppress(CancelledError)`` cannot
    make that distinction and would swallow a cancelled ``aclose()``
    caller. The child's outcome is then retrieved explicitly so a failed
    task is logged instead of tripping the event loop's "exception was
    never retrieved" warning.

    A task that *is* the current task is skipped: awaiting yourself is a
    deadlock (and a RuntimeError); such tasks are shut down via the
    notification queue sentinel instead.
    """
    if task is None or task is asyncio.current_task():
        return
    await asyncio.wait((task,))
    if task.cancelled():
        return
    exc = task.exception()
    if exc is not None:
        _LOGGER.debug("Shutdown task %s raised: %r", task.get_name(), exc)


@dataclass(slots=True)
class _NotificationObserverState:
    """Connection-owned sequence and additive raw notification observers."""

    sequence: int = 0
    observers: list[NotificationObserver] = field(default_factory=list)


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
        *,
        _before_write_callback: BeforeWriteCallback | None = None,
        _after_write_callback: AfterWriteCallback | None = None,
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


class ICRequestMixin:
    """Mixin providing shared request/response correlation logic.

    This mixin is used by both ICProtocol and ICWebSocketTransport to avoid
    code duplication for request ID generation and response handling.
    """

    # These are defined in subclasses
    _response_future: asyncio.Future[dict[str, Any]] | None
    _pending_message_id: str | None
    _message_id: int

    def _init_request_mixin(self) -> None:
        """Initialize request/response correlation state."""
        self._response_future = None
        self._pending_message_id = None
        self._message_id = 0

    def _next_message_id(self) -> str:
        """Generate the next message ID."""
        self._message_id += 1
        return str(self._message_id)

    def _build_request(self, command: str, fields: dict[str, Any]) -> tuple[str, dict[str, Any]]:
        """Build a request payload, rejecting protocol-owned fields.

        Raises:
            ValueError: If ``fields`` contains a reserved key
                (``messageID``/``command``); response correlation uses the
                generated ID, so an overridden field would guarantee a
                timeout or a misrouted request.
        """
        reserved = _RESERVED_REQUEST_FIELDS.intersection(fields)
        if reserved:
            raise ValueError(
                f"Reserved request fields cannot be passed as kwargs: {', '.join(sorted(reserved))}"
            )
        msg_id = self._next_message_id()
        return msg_id, {"messageID": msg_id, "command": command, **fields}

    def _handle_response(self, msg: dict[str, Any]) -> None:
        """Handle a response message by resolving the pending Future."""
        msg_id = msg.get("messageID")

        if self._pending_message_id and msg_id == self._pending_message_id:
            if self._response_future and not self._response_future.done():
                self._response_future.set_result(msg)
            return

        _LOGGER.debug("Ignoring response for another client: %s", msg_id)

    def _clear_pending_request(self) -> None:
        """Clear pending request state."""
        self._response_future = None
        self._pending_message_id = None

    def _fail_pending_request(self, exc: Exception) -> None:
        """Fail any pending request with the given exception."""
        if self._response_future and not self._response_future.done():
            self._response_future.set_exception(exc)


class ICNotificationMixin:
    """Mixin providing shared notification handling logic.

    This mixin is used by both ICProtocol and ICWebSocketTransport to avoid
    code duplication for notification queue management and callback handling.
    """

    # These are defined in subclasses
    _notification_callback: NotificationCallback | None
    _notification_queue_size: int
    # ``None`` on the queue is the shutdown sentinel (see
    # _stop_notification_consumer); real notifications are always dicts.
    _notification_queue: asyncio.Queue[dict[str, Any] | None] | None
    _consumer_task: asyncio.Task[None] | None
    _notification_observer_state: _NotificationObserverState
    _notification_drops: int

    def _init_notification_mixin(
        self,
        notification_callback: NotificationCallback | None,
        notification_queue_size: int,
        notification_observer_state: _NotificationObserverState | None,
    ) -> None:
        """Initialize notification handling state."""
        self._notification_callback = notification_callback
        self._notification_queue_size = notification_queue_size
        self._notification_queue = None
        self._consumer_task = None
        self._notification_drops = 0
        self._notification_observer_state = (
            notification_observer_state
            if notification_observer_state is not None
            else _NotificationObserverState()
        )

    def _start_notification_consumer(self) -> None:
        """Start the notification consumer task if not already running."""
        if self._notification_queue is not None:
            return

        self._notification_drops = 0
        self._notification_queue = asyncio.Queue(maxsize=self._notification_queue_size)
        self._consumer_task = asyncio.create_task(
            self._notification_consumer(),
            name="ic-notification-consumer",
        )

    def _stop_notification_consumer(self) -> asyncio.Task[None] | None:
        """Stop the notification consumer task.

        Returns the cancelled task (if any) so async close paths can await
        its completion; sync callers may ignore the return value.

        When the stop is triggered from inside the consumer itself (a
        notification callback awaiting ``disconnect()``), the consumer is
        the *current* task: cancelling it would deliver the CancelledError
        to the disconnect path, where it would be consumed and the
        consumer would resume waiting forever on its detached queue.
        Instead a ``None`` sentinel is enqueued so the loop exits
        deterministically once the callback returns; ``None`` is returned
        because the current task must never await itself.
        """
        task, self._consumer_task = self._consumer_task, None
        queue, self._notification_queue = self._notification_queue, None
        if task is None or task.done():
            return None

        try:
            current = asyncio.current_task()
        except RuntimeError:
            current = None
        if task is current:
            if queue is not None:
                try:
                    queue.put_nowait(None)
                except asyncio.QueueFull:
                    # Drop the oldest queued item to make room; account it
                    # so a future queue.join() cannot hang. put_nowait
                    # cannot fail again: nothing runs between the two.
                    queue.get_nowait()
                    queue.task_done()
                    queue.put_nowait(None)
            return None

        task.cancel()
        return task

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
        state = self._notification_observer_state
        sequence = state.sequence = state.sequence + 1
        if state.observers:
            for observer in tuple(state.observers):
                try:
                    observer(sequence, msg)
                except Exception:
                    _LOGGER.exception("Error in notification observer")

        if not self._notification_callback or self._notification_queue is None:
            return

        try:
            self._notification_queue.put_nowait(msg)
        except asyncio.QueueFull:
            # Log the first drop, then a periodic summary: a warning per
            # dropped message can flood the logs under sustained overflow.
            self._notification_drops += 1
            if (
                self._notification_drops == 1
                or self._notification_drops % NOTIFICATION_DROP_LOG_INTERVAL == 0
            ):
                _LOGGER.warning(
                    "Notification queue full (%d items) - dropped %d message(s) so far, "
                    "keeping newest",
                    self._notification_queue_size,
                    self._notification_drops,
                )
            try:
                self._notification_queue.get_nowait()
                # Account for the discarded item so queue.join() cannot hang.
                self._notification_queue.task_done()
                self._notification_queue.put_nowait(msg)
            except asyncio.QueueEmpty:
                _LOGGER.debug("Notification queue race - message dropped")

    async def _notification_consumer(self) -> None:
        """Process notifications from the queue captured for this consumer.

        The queue is captured in a local because teardown can null out (or a
        fast restart can replace) ``self._notification_queue`` while an async
        callback is suspended; the ``finally`` below must account for the
        item on the queue it actually came from - and cancellation must
        surface as a clean CancelledError, not an AttributeError.
        """
        queue = self._notification_queue
        if queue is None:
            raise RuntimeError("Notification queue not initialized")

        while True:
            try:
                msg = await queue.get()
            except asyncio.CancelledError:
                _LOGGER.debug("Notification consumer cancelled")
                break

            if msg is None:
                # Shutdown sentinel: the consumer stopped itself from
                # inside a notification callback (see
                # _stop_notification_consumer) and must exit its loop
                # instead of waiting forever on the detached queue.
                queue.task_done()
                _LOGGER.debug("Notification consumer stopped")
                break

            try:
                callback = self._notification_callback
                if callback is not None:
                    result = callback(msg)
                    # isawaitable covers coroutine functions, async __call__
                    # objects, and sync callables returning an awaitable;
                    # for a plain sync callback returning None it is a
                    # single cheap check.
                    if inspect.isawaitable(result):
                        await result
            except Exception:
                _LOGGER.exception("Error in notification callback")
            finally:
                queue.task_done()


class ICProtocol(ICRequestMixin, ICNotificationMixin, asyncio.Protocol):
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
        notification_observer_state: _NotificationObserverState | None = None,
    ) -> None:
        """Initialize the protocol.

        Args:
            notification_callback: Called when NotifyList notifications arrive
            disconnect_callback: Called when connection is lost
            notification_queue_size: Max queued notifications (default: 100)
        """
        self._init_request_mixin()
        self._init_notification_mixin(
            notification_callback,
            notification_queue_size,
            notification_observer_state,
        )
        self._disconnect_callback = disconnect_callback

        # Transport (set by connection_made)
        self._transport: asyncio.Transport | None = None

        # Buffer for incomplete messages (bytearray for efficient appending)
        self._buffer = bytearray()

        # How far the buffer has already been searched for a frame
        # terminator (see data_received)
        self._scan_pos = 0

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
        self._scan_pos = 0
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

        # Fail any pending request
        error_msg = f"Connection lost: {exc}" if exc else "Connection closed"
        self._fail_pending_request(ICConnectionError(error_msg))

        _LOGGER.debug("TCP connection lost: %s", exc)

        if self._disconnect_callback:
            self._disconnect_callback(exc)

    def data_received(self, data: bytes) -> None:
        """Called by event loop when data arrives."""
        buffer = self._buffer
        buffer.extend(data)

        if len(buffer) > MAX_BUFFER_SIZE:
            _LOGGER.error("Buffer overflow - closing connection")
            if self._transport:
                self._transport.close()
            return

        # Cursor-based framing: scan with a moving offset and compact the
        # buffer once per call instead of re-scanning from offset 0 and
        # memmoving per message. _scan_pos remembers how far an incomplete
        # frame was already searched, backed off one byte so a \r\n split
        # across two chunks is still found.
        start = 0
        search_from = self._scan_pos
        try:
            while (idx := buffer.find(b"\r\n", search_from)) != -1:
                line = buffer[start:idx]  # bytearray slice: orjson accepts it directly
                start = idx + 2
                search_from = start

                try:
                    decoded: Any = orjson.loads(line)
                except orjson.JSONDecodeError as err:
                    _LOGGER.error("Invalid JSON received: %s", err)
                    continue

                if not isinstance(decoded, dict):
                    # Valid JSON with a non-object root (number, string,
                    # array, null): skip the frame; it must never escape
                    # data_received or asyncio aborts the whole connection.
                    _LOGGER.error("Ignoring non-object JSON frame: %.80s", line)
                    continue

                self._dispatch_message(decoded)
        finally:
            if start:
                del buffer[:start]
            self._scan_pos = max(len(buffer) - 1, 0)

    async def send_request(
        self,
        command: str,
        request_timeout: float = RESPONSE_TIMEOUT,
        *,
        _before_write_callback: BeforeWriteCallback | None = None,
        _after_write_callback: AfterWriteCallback | None = None,
        **kwargs: Any,
    ) -> dict[str, Any]:
        """Send a request and await response via Future."""
        if not self.connected or not self._transport:
            raise ICConnectionError("Not connected")

        msg_id, request = self._build_request(command, kwargs)

        # Create Future for this request (uses running event loop automatically)
        self._response_future = asyncio.Future()
        self._pending_message_id = msg_id

        try:
            packet = orjson.dumps(request) + b"\r\n"
            if _before_write_callback is not None:
                _before_write_callback(
                    self._notification_observer_state.sequence,
                    asyncio.get_running_loop().time(),
                )
            self._transport.write(packet)
            if _after_write_callback is not None:
                _after_write_callback(self._notification_observer_state.sequence)
            _LOGGER.debug("Sent TCP request: %s (ID: %s)", command, msg_id)

            async with asyncio.timeout(request_timeout):
                msg = await self._response_future

            response_code: str = msg.get("response", "unknown")
            if response_code != "200":
                raise ICResponseError(response_code)

            _LOGGER.debug("Received response for %s", msg.get("command"))
            return msg

        except TimeoutError as err:
            _LOGGER.error("Request %s timed out after %ss", command, request_timeout)
            raise ICTimeoutError(f"Request {command} timed out after {request_timeout}s") from err

        finally:
            self._clear_pending_request()

    def close(self) -> None:
        """Close the connection."""
        self._connected = False
        if self._transport:
            self._transport.close()


class ICWebSocketTransport(ICRequestMixin, ICNotificationMixin):
    """WebSocket transport for IntelliCenter communication.

    Uses the websockets library for WebSocket connections to IntelliCenter.
    """

    def __init__(
        self,
        notification_callback: NotificationCallback | None = None,
        disconnect_callback: DisconnectCallback | None = None,
        *,
        notification_queue_size: int = DEFAULT_NOTIFICATION_QUEUE_SIZE,
        notification_observer_state: _NotificationObserverState | None = None,
    ) -> None:
        """Initialize the WebSocket transport.

        Args:
            notification_callback: Called when NotifyList notifications arrive
            disconnect_callback: Called when connection is lost
            notification_queue_size: Max queued notifications (default: 100)
        """
        self._init_request_mixin()
        self._init_notification_mixin(
            notification_callback,
            notification_queue_size,
            notification_observer_state,
        )
        self._disconnect_callback = disconnect_callback

        self._ws: Any = None  # websockets.WebSocketClientProtocol
        self._connected = False

        # Ensures the disconnect path runs at most once per connection
        self._disconnect_handled = False

        # Reader task for incoming messages
        self._reader_task: asyncio.Task[None] | None = None

        # Close task for async cleanup
        self._close_task: asyncio.Task[None] | None = None

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
            self._disconnect_handled = False
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
        """Read messages from WebSocket and dispatch them.

        The websockets iterator ends in one of three ways, and all but
        cancellation mean the connection is no longer being serviced:

        - the server closes cleanly: iteration ends without an exception
        - the link dies: ``ConnectionClosed`` (a ``WebSocketException``,
          *not* an ``OSError``/``ConnectionError``) or an OS-level error
        - the task is cancelled by a deliberate ``close()``/``aclose()``

        Everything except cancellation - including any unexpected
        decode/dispatch error - must run the disconnect path so the
        disconnect callback fires and reconnection logic can take over.
        """
        exc: Exception | None = None
        try:
            async for message in self._ws:
                try:
                    # orjson accepts str directly - no encode() copy needed
                    decoded: Any = orjson.loads(message)
                except orjson.JSONDecodeError as err:
                    _LOGGER.error("Invalid JSON received: %s", err)
                    continue

                if not isinstance(decoded, dict):
                    # Valid JSON with a non-object root (number, string,
                    # array, null): skip the frame instead of letting a
                    # TypeError/AttributeError kill the reader.
                    _LOGGER.error("Ignoring non-object JSON frame: %.80s", message)
                    continue

                self._dispatch_message(decoded)

            _LOGGER.debug("WebSocket closed by server")

        except asyncio.CancelledError:
            # Deliberate close()/aclose(): not a link failure.
            _LOGGER.debug("WebSocket reader cancelled")
            return
        except (WebSocketException, OSError, ConnectionError) as err:
            _LOGGER.debug("WebSocket reader error: %s", err)
            exc = err
        except Exception as err:
            # Defense in depth: a decode/dispatch surprise must still run
            # the disconnect path. A silently dead reader would leave a
            # zombie connection that looks connected but never delivers
            # notifications and blocks every request until timeout.
            _LOGGER.exception("Unexpected error in WebSocket reader")
            exc = err

        self._handle_disconnect(exc)

    def _handle_disconnect(self, exc: Exception | None) -> None:
        """Handle disconnection, firing the disconnect callback exactly once."""
        if self._disconnect_handled:
            return
        self._disconnect_handled = True

        self._connected = False
        ws, self._ws = self._ws, None
        if ws is not None:
            # An unexpected reader error leaves the underlying socket
            # open: schedule (and track) its closure so the panel session
            # is released instead of lingering until GC - IntelliCenter
            # has a small concurrent-client budget.
            self._close_task = asyncio.create_task(
                self._close_websocket(ws),
                name="ic-websocket-close",
            )

        self._stop_notification_consumer()

        # Fail any pending request
        error_msg = f"Connection lost: {exc}" if exc else "Connection closed"
        self._fail_pending_request(ICConnectionError(error_msg))

        _LOGGER.debug("WebSocket connection lost: %s", exc)

        if self._disconnect_callback:
            self._disconnect_callback(exc)

    async def send_request(
        self,
        command: str,
        request_timeout: float = RESPONSE_TIMEOUT,
        *,
        _before_write_callback: BeforeWriteCallback | None = None,
        _after_write_callback: AfterWriteCallback | None = None,
        **kwargs: Any,
    ) -> dict[str, Any]:
        """Send a request and await response."""
        if not self.connected or not self._ws:
            raise ICConnectionError("Not connected")

        msg_id, request = self._build_request(command, kwargs)

        # Create Future for this request (uses running event loop automatically)
        self._response_future = asyncio.Future()
        self._pending_message_id = msg_id

        try:
            # Send as text with \r\n terminator (same framing as TCP)
            packet = orjson.dumps(request).decode() + "\r\n"
            if _before_write_callback is not None:
                _before_write_callback(
                    self._notification_observer_state.sequence,
                    asyncio.get_running_loop().time(),
                )
            await self._ws.send(packet)
            if _after_write_callback is not None:
                _after_write_callback(self._notification_observer_state.sequence)
            _LOGGER.debug("Sent WebSocket request: %s (ID: %s)", command, msg_id)

            async with asyncio.timeout(request_timeout):
                msg = await self._response_future

            response_code: str = msg.get("response", "unknown")
            if response_code != "200":
                raise ICResponseError(response_code)

            _LOGGER.debug("Received response for %s", msg.get("command"))
            return msg

        except TimeoutError as err:
            _LOGGER.error("Request %s timed out after %ss", command, request_timeout)
            raise ICTimeoutError(f"Request {command} timed out after {request_timeout}s") from err

        except (WebSocketException, OSError, ConnectionError) as err:
            # ws.send() raises ConnectionClosed (a WebSocketException) on a
            # dead socket; surface it as the library's connection error.
            _LOGGER.error("Request %s failed - connection lost: %s", command, err)
            raise ICConnectionError(f"Connection lost during request {command}: {err}") from err

        finally:
            self._clear_pending_request()

    def close(self) -> None:
        """Close the connection."""
        self._connected = False

        # A deliberate close must not leave an in-flight request hanging
        # until its timeout: fail it before tearing down the reader (whose
        # cancellation deliberately skips the disconnect path).
        self._fail_pending_request(ICConnectionError("Connection closed"))

        if self._reader_task and not self._reader_task.done():
            self._reader_task.cancel()
            self._reader_task = None

        self._stop_notification_consumer()

        if self._ws:
            # Schedule close in background (can't await in sync method)
            # Track the task to avoid orphaned coroutines
            self._close_task = asyncio.create_task(self._async_close())

    async def _async_close(self) -> None:
        """Close WebSocket connection asynchronously."""
        ws, self._ws = self._ws, None
        if ws is not None:
            await self._close_websocket(ws)

    @staticmethod
    async def _close_websocket(ws: Any) -> None:
        """Close a websocket handle, tolerating an already-dead link."""
        with contextlib.suppress(Exception):
            await ws.close()

    async def aclose(self) -> None:
        """Close the connection asynchronously (preferred for proper cleanup).

        Child tasks are awaited via ``_await_shutdown_task`` so a
        CancelledError raised here always belongs to the *caller* and
        propagates - suppressing it would make a cancelled shutdown look
        successful.
        """
        self._connected = False
        self._fail_pending_request(ICConnectionError("Connection closed"))

        reader_task, self._reader_task = self._reader_task, None
        if reader_task is not None and not reader_task.done():
            reader_task.cancel()
        await _await_shutdown_task(reader_task)

        await _await_shutdown_task(self._stop_notification_consumer())

        # A close() (or a reader-error disconnect) that ran earlier
        # scheduled the handshake in the background; take ownership so
        # the close frame is truly awaited.
        close_task, self._close_task = self._close_task, None
        await _await_shutdown_task(close_task)

        await self._async_close()


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
        self._notification_observer_state = _NotificationObserverState()

        # One-shot lifecycle signal for the current connection generation
        self._closed_future: asyncio.Future[None] | None = None

        # Flow control: one request at a time
        self._request_lock = asyncio.Lock()

        # Connection lifecycle: one generation attempt at a time
        self._connect_lock = asyncio.Lock()

        # Keepalive task
        self._keepalive_task: asyncio.Task[None] | None = None

        # Ensures the disconnect callback fires at most once per connection
        # (the keepalive teardown and the transport's own notification can race)
        self._disconnect_dispatched = False

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
            if callback and self._protocol.connected and self._protocol._notification_queue is None:
                self._protocol._start_notification_consumer()

    def add_notification_observer(
        self,
        observer: NotificationObserver,
    ) -> Callable[[], None]:
        """Add an enqueue-time notification observer and return its remover."""
        state = self._notification_observer_state
        state.observers.append(observer)
        removed = False

        def remove() -> None:
            nonlocal removed
            if removed:
                return
            removed = True
            for index, candidate in enumerate(state.observers):
                if candidate is observer:
                    del state.observers[index]
                    break

        return remove

    def set_disconnect_callback(self, callback: DisconnectCallback | None) -> None:
        """Set callback for disconnection events.

        Args:
            callback: Function to call on disconnect, or None to clear.
        """
        self._disconnect_callback = callback

    def _on_disconnect(self, exc: Exception | None) -> None:
        """Internal disconnect handler that wraps user callback."""
        closed_future = self._closed_future
        if closed_future is not None:
            self._on_generation_disconnect(closed_future, exc)
            return
        self._handle_current_disconnect(exc)

    def _on_generation_disconnect(
        self,
        closed_future: asyncio.Future[None],
        exc: Exception | None,
    ) -> None:
        """Handle a transport close only for the generation that emitted it."""
        self._complete_closed_future(closed_future)
        if closed_future is not self._closed_future:
            return
        self._handle_current_disconnect(exc)

    def _handle_current_disconnect(self, exc: Exception | None) -> None:
        """Cancel current lifecycle work and dispatch an unexpected close."""
        if self._keepalive_task and not self._keepalive_task.done():
            self._keepalive_task.cancel()
            self._keepalive_task = None

        self._dispatch_disconnect(exc)

    def _dispatch_disconnect(self, exc: Exception | None) -> None:
        """Invoke the user disconnect callback at most once per connection."""
        if self._disconnect_dispatched:
            return
        self._disconnect_dispatched = True

        if self._disconnect_callback:
            self._disconnect_callback(exc)

    def _abort_connection(self, exc: Exception | None) -> None:
        """Tear down a connection whose link is dead and run the disconnect path.

        Used when a failure is detected outside the transport's own machinery
        (e.g. a keepalive timeout on a half-open connection). Detaches the
        transport's disconnect callback first so the transport's own teardown
        (e.g. TCP connection_lost after close()) cannot fire it again later.
        """
        self._complete_closed_future()
        protocol, self._protocol = self._protocol, None
        if protocol is not None:
            protocol._disconnect_callback = None
            protocol.close()

        self._dispatch_disconnect(exc)

    async def connect(self) -> None:
        """Establish connection to IntelliCenter.

        Uses the transport type specified at initialization.

        Raises:
            ICConnectionError: If connection fails or times out.
        """
        async with self._connect_lock:
            await self._connect_locked()

    async def _connect_locked(self) -> None:
        """Establish one serialized connection generation."""
        if self.connected:
            return

        closed_future = asyncio.get_running_loop().create_future()
        self._closed_future = closed_future

        def on_disconnect(exc: Exception | None) -> None:
            self._on_generation_disconnect(closed_future, exc)

        try:
            if self._transport_type == "websocket":
                await self._connect_websocket(on_disconnect)
            else:
                await self._connect_tcp(on_disconnect)

            if self._closed_future is not closed_future:
                raise ICConnectionError("Connection generation changed during setup")
            if closed_future.done() or not self.connected:
                protocol, self._protocol = self._protocol, None
                if protocol is not None:
                    protocol._disconnect_callback = None
                    protocol.close()
                raise ICConnectionError("Connection closed during setup")
        except asyncio.CancelledError:
            self._complete_closed_future(closed_future)
            raise
        except Exception:
            self._complete_closed_future(closed_future)
            raise

        # Fresh connection - its disconnect may dispatch (again)
        self._disconnect_dispatched = False

        # Start keepalive task
        self._keepalive_task = asyncio.create_task(self._keepalive_loop())

    async def _connect_tcp(self, disconnect_callback: DisconnectCallback) -> None:
        """Establish TCP connection."""
        try:
            loop = asyncio.get_running_loop()

            async with asyncio.timeout(CONNECTION_TIMEOUT):
                _, protocol = await loop.create_connection(
                    lambda: ICProtocol(
                        notification_callback=self._notification_callback,
                        disconnect_callback=disconnect_callback,
                        notification_queue_size=self._notification_queue_size,
                        notification_observer_state=self._notification_observer_state,
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

    async def _connect_websocket(self, disconnect_callback: DisconnectCallback) -> None:
        """Establish WebSocket connection."""
        transport = ICWebSocketTransport(
            notification_callback=self._notification_callback,
            disconnect_callback=disconnect_callback,
            notification_queue_size=self._notification_queue_size,
            notification_observer_state=self._notification_observer_state,
        )
        await transport.connect(self._host, self._port)
        self._protocol = transport
        _LOGGER.debug("Connected to IC via WebSocket at %s:%s", self._host, self._port)

    async def disconnect(self) -> None:
        """Close the connection gracefully."""
        self._complete_closed_future()
        protocol, self._protocol = self._protocol, None
        if protocol is not None:
            protocol._disconnect_callback = None

        keepalive_task, self._keepalive_task = self._keepalive_task, None
        if keepalive_task is not None and not keepalive_task.done():
            keepalive_task.cancel()
        # Same contract as aclose(): a CancelledError here belongs to the
        # disconnect() caller and must propagate, not be suppressed.
        await _await_shutdown_task(keepalive_task)

        if protocol is not None:
            aclose = getattr(protocol, "aclose", None)
            if inspect.iscoroutinefunction(aclose):
                # WebSocket transport: await the full close handshake
                # instead of firing it off in a background task.
                await aclose()
            else:
                protocol.close()

        _LOGGER.debug("Disconnected from IC")

    def _complete_closed_future(
        self,
        future: asyncio.Future[None] | None = None,
    ) -> None:
        """Complete a generation's close signal once."""
        future = future if future is not None else self._closed_future
        if future is not None and not future.done():
            future.set_result(None)

    def _capture_closed_future(self) -> asyncio.Future[None]:
        """Return the one-shot close future for the current live generation."""
        future = self._closed_future
        if future is None or not self.connected:
            raise ICConnectionError("Connection is not live")
        return future

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
        *,
        _before_write_callback: BeforeWriteCallback | None = None,
        _after_write_callback: AfterWriteCallback | None = None,
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
            ICTimeoutError: If no response is received within the timeout.
            ValueError: If kwargs contain protocol-owned fields
                (``messageID``/``command``).
        """
        protocol = self._protocol
        if protocol is None or not protocol.connected:
            raise ICConnectionError("Not connected")

        effective_timeout = (
            request_timeout if request_timeout is not None else self._response_timeout
        )

        async with self._request_lock:
            # Re-check under the lock: the connection may have been torn
            # down (keepalive abort, disconnect) or replaced by a reconnect
            # while this request waited its turn. Send only on the protocol
            # generation captured at call time.
            if self._protocol is not protocol or not protocol.connected:
                raise ICConnectionError("Connection lost while request was queued")

            return await protocol.send_request(
                command,
                request_timeout=effective_timeout,
                _before_write_callback=_before_write_callback,
                _after_write_callback=_after_write_callback,
                **kwargs,
            )

    async def _keepalive_loop(self) -> None:
        """Send periodic keepalive requests to maintain connection health.

        A keepalive failing with a timeout or connection error means the
        link is dead even though the transport still looks "connected"
        (half-open connection or unresponsive server). Detection alone is
        not enough: the connection must be torn down so the disconnect
        callback fires and reconnection logic can take over - otherwise it
        stays frozen forever.

        Note: send_request raises ICTimeoutError (an ICError, not a
        TimeoutError) on timeout, so both are handled explicitly here.

        A single missed response does not prove death (the panel can be busy
        servicing another client); the link is declared dead after
        ``KEEPALIVE_MAX_FAILURES`` consecutive timeouts - the documented
        design. A connection error, by contrast, is definitive and tears the
        connection down immediately.
        """
        failures = 0
        try:
            while self.connected:
                await asyncio.sleep(self._keepalive_interval)

                if not self.connected:
                    return

                try:
                    _LOGGER.debug("Sending keepalive request")
                    await self.send_request(
                        "GetParamList",
                        request_timeout=KEEPALIVE_TIMEOUT,
                        condition="OBJTYP=SYSTEM",
                        objectList=[{"objnam": "INCR", "keys": ["MODE"]}],
                    )
                    failures = 0
                except (ICTimeoutError, TimeoutError) as err:
                    failures += 1
                    _LOGGER.warning(
                        "Keepalive timeout (%d/%d) - connection may be dead",
                        failures,
                        KEEPALIVE_MAX_FAILURES,
                    )
                    if failures >= KEEPALIVE_MAX_FAILURES:
                        _LOGGER.warning(
                            "Dropping dead connection after %d consecutive keepalive timeouts",
                            failures,
                        )
                        self._abort_connection(err)
                        break
                except (ICConnectionError, OSError, ConnectionError) as err:
                    _LOGGER.warning("Keepalive failed: %s - dropping connection", err)
                    self._abort_connection(err)
                    break
                except ICResponseError as err:
                    # The panel answered - the link is alive - but rejected
                    # the request; keep the connection and keep probing.
                    failures = 0
                    _LOGGER.warning("Keepalive request rejected: %s", err)

        except asyncio.CancelledError:
            _LOGGER.debug("Keepalive task cancelled")
