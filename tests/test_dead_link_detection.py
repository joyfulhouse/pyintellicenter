"""Regression tests for dead-link detection (WebSocket reader loop + keepalive).

These cover the failure mode where the link to IntelliCenter dies but the
disconnect callback never fires, leaving the connection "connected" with
frozen state until a manual restart:

1. ``ICWebSocketTransport._reader_loop`` only caught ``OSError`` /
   ``ConnectionError``, but the websockets library raises ``ConnectionClosed``
   (a ``WebSocketException``) on abnormal closes - the reader task died
   without running the disconnect path.
2. A clean server-side close ends the reader's ``async for`` without any
   exception - the disconnect path never ran either.
3. ``ICConnection._keepalive_loop`` caught ``TimeoutError``, but
   ``send_request`` raises ``ICTimeoutError`` (an ``ICError``, not a
   ``TimeoutError``) - a keepalive timeout killed the keepalive task with an
   unretrieved exception ("Task exception was never retrieved").
4. When the keepalive loop did catch a failure it only logged and exited:
   detection without recovery - no teardown, no disconnect callback, no
   reconnect.
"""

from __future__ import annotations

import asyncio
import contextlib
from typing import Any

import pytest
import websockets
from websockets.exceptions import ConnectionClosedError

from pyintellicenter import (
    ICBaseController,
    ICConnection,
    ICConnectionError,
    ICConnectionHandler,
    ICResponseError,
    ICTimeoutError,
)
from pyintellicenter import connection as connection_module
from pyintellicenter.connection import ICWebSocketTransport


def make_abnormal_close() -> ConnectionClosedError:
    """Build a 1006-style close: connection lost without a close frame."""
    return ConnectionClosedError(None, None)


class FakeWebSocket:
    """Minimal stand-in for a websockets client connection.

    Yields queued messages, then either ends iteration (clean server close)
    or raises the configured exception (abnormal close). With ``block=True``
    it stalls forever after the queued messages, until cancelled.
    """

    def __init__(
        self,
        messages: list[str] | None = None,
        end_with: Exception | None = None,
        block: bool = False,
    ) -> None:
        self._messages = list(messages or [])
        self._end_with = end_with
        self._block = block
        self.sent: list[str] = []
        self.send_error: Exception | None = None

    def __aiter__(self) -> FakeWebSocket:
        return self

    async def __anext__(self) -> str:
        if self._messages:
            return self._messages.pop(0)
        if self._block:
            await asyncio.Event().wait()
        if self._end_with is not None:
            raise self._end_with
        raise StopAsyncIteration

    async def send(self, data: str) -> None:
        if self.send_error is not None:
            raise self.send_error
        self.sent.append(data)

    async def close(self) -> None:
        return


class FakeDeadLinkProtocol:
    """Transport stand-in for a half-open link.

    ``connected`` stays True (the transport has not noticed anything) but
    every request fails with the configured error - exactly the state the
    keepalive loop exists to detect.
    """

    def __init__(self, error: Exception) -> None:
        self._error = error
        self.connected = True
        self.close_calls = 0
        self._disconnect_callback: Any = None

    async def send_request(
        self, command: str, request_timeout: float = 30.0, **kwargs: Any
    ) -> dict[str, Any]:
        raise self._error

    def close(self) -> None:
        self.close_calls += 1
        self.connected = False


class TestWebSocketReaderDeadLink:
    """The reader loop must run the disconnect path on every link death."""

    @pytest.mark.asyncio
    async def test_abnormal_close_fires_disconnect_callback(self):
        """ConnectionClosed from the websockets iterator must not kill the reader silently."""
        disconnects: list[Exception | None] = []
        transport = ICWebSocketTransport(disconnect_callback=disconnects.append)
        exc = make_abnormal_close()
        transport._ws = FakeWebSocket(messages=['{"command": "NotifyList"}'], end_with=exc)
        transport._connected = True

        await transport._reader_loop()

        assert disconnects == [exc]
        assert transport.connected is False

    @pytest.mark.asyncio
    async def test_abnormal_close_fails_pending_request_fast(self):
        """A request in flight when the link dies must fail, not hang."""
        transport = ICWebSocketTransport()
        transport._ws = FakeWebSocket(end_with=make_abnormal_close())
        transport._connected = True
        future: asyncio.Future[dict[str, Any]] = asyncio.get_running_loop().create_future()
        transport._response_future = future
        transport._pending_message_id = "1"

        await transport._reader_loop()

        assert future.done()
        with pytest.raises(ICConnectionError):
            future.result()

    @pytest.mark.asyncio
    async def test_clean_server_close_fires_disconnect_callback(self):
        """A clean close ends iteration without an exception - still a disconnect."""
        disconnects: list[Exception | None] = []
        transport = ICWebSocketTransport(disconnect_callback=disconnects.append)
        transport._ws = FakeWebSocket(messages=['{"command": "NotifyList"}'])
        transport._connected = True

        await transport._reader_loop()

        assert disconnects == [None]
        assert transport.connected is False

    @pytest.mark.asyncio
    async def test_cancelled_reader_does_not_fire_disconnect(self):
        """Deliberate close() cancels the reader; that is not a link failure."""
        disconnects: list[Exception | None] = []
        transport = ICWebSocketTransport(disconnect_callback=disconnects.append)
        transport._ws = FakeWebSocket(block=True)
        transport._connected = True

        task = asyncio.create_task(transport._reader_loop())
        await asyncio.sleep(0.01)
        task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await task

        assert disconnects == []

    @pytest.mark.asyncio
    async def test_handle_disconnect_fires_callback_exactly_once(self):
        """Racing disconnect paths must collapse into a single callback."""
        disconnects: list[Exception | None] = []
        transport = ICWebSocketTransport(disconnect_callback=disconnects.append)
        transport._connected = True

        transport._handle_disconnect(None)
        transport._handle_disconnect(make_abnormal_close())

        assert disconnects == [None]


class TestWebSocketSendDeadLink:
    """Send failures on a dead socket must surface as library errors."""

    @pytest.mark.asyncio
    async def test_send_on_closed_socket_raises_ic_connection_error(self):
        """ConnectionClosed from ws.send() must become ICConnectionError."""
        transport = ICWebSocketTransport()
        ws = FakeWebSocket(block=True)
        ws.send_error = make_abnormal_close()
        transport._ws = ws
        transport._connected = True

        with pytest.raises(ICConnectionError):
            await transport.send_request("GetParamList", request_timeout=1.0)


class TestKeepaliveDeadLink:
    """A failed keepalive must tear the connection down, not die quietly."""

    @staticmethod
    def _connection_with(
        protocol: FakeDeadLinkProtocol, keepalive_interval: float = 0.01
    ) -> tuple[ICConnection, list[Exception | None]]:
        disconnects: list[Exception | None] = []
        conn = ICConnection("192.168.1.100", keepalive_interval=keepalive_interval)
        conn.set_disconnect_callback(disconnects.append)
        conn._protocol = protocol  # type: ignore[assignment]
        return conn, disconnects

    @pytest.mark.asyncio
    async def test_keepalive_timeout_fires_disconnect_and_tears_down(self):
        """ICTimeoutError (not TimeoutError!) must be handled and trigger teardown."""
        protocol = FakeDeadLinkProtocol(ICTimeoutError("Request GetParamList timed out"))
        conn, disconnects = self._connection_with(protocol)

        task = asyncio.create_task(conn._keepalive_loop())
        conn._keepalive_task = task
        await asyncio.wait_for(task, timeout=2.0)

        assert len(disconnects) == 1
        assert isinstance(disconnects[0], ICTimeoutError)
        assert protocol.close_calls == 1
        assert conn.connected is False
        assert task.exception() is None  # no "Task exception was never retrieved"

    @pytest.mark.asyncio
    async def test_keepalive_connection_error_fires_disconnect(self):
        """Detection without recovery: a caught failure must still tear down."""
        protocol = FakeDeadLinkProtocol(ICConnectionError("Connection lost"))
        conn, disconnects = self._connection_with(protocol)

        task = asyncio.create_task(conn._keepalive_loop())
        conn._keepalive_task = task
        await asyncio.wait_for(task, timeout=2.0)

        assert len(disconnects) == 1
        assert isinstance(disconnects[0], ICConnectionError)
        assert conn.connected is False

    @pytest.mark.asyncio
    async def test_keepalive_response_error_keeps_probing(self):
        """An error response proves the link is alive: keep the connection.

        Previously ICResponseError was uncaught and killed the keepalive task.
        """
        protocol = FakeDeadLinkProtocol(ICResponseError("400"))
        conn, disconnects = self._connection_with(protocol)

        task = asyncio.create_task(conn._keepalive_loop())
        conn._keepalive_task = task
        await asyncio.sleep(0.05)  # several keepalive rounds

        try:
            assert disconnects == []
            assert conn.connected is True
            assert not task.done()  # the keepalive task survived and keeps probing
        finally:
            task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await task

    @pytest.mark.asyncio
    async def test_connection_dispatches_disconnect_at_most_once(self):
        """Racing disconnect paths at the ICConnection level collapse to one callback."""
        protocol = FakeDeadLinkProtocol(ICConnectionError("unused"))
        conn, disconnects = self._connection_with(protocol)

        conn._on_disconnect(None)
        conn._on_disconnect(ICConnectionError("late transport notification"))

        assert disconnects == [None]

    @pytest.mark.asyncio
    async def test_keepalive_exits_quietly_after_transport_disconnect(self):
        """If the transport already handled the disconnect, do not double-fire."""
        protocol = FakeDeadLinkProtocol(ICConnectionError("unused"))
        protocol.connected = False  # transport disconnect path already ran
        conn, disconnects = self._connection_with(protocol)

        task = asyncio.create_task(conn._keepalive_loop())
        conn._keepalive_task = task
        await asyncio.wait_for(task, timeout=2.0)

        assert disconnects == []

    @pytest.mark.asyncio
    async def test_cancelled_keepalive_does_not_fire_disconnect(self):
        """Deliberate disconnect() cancels the keepalive; no callback expected."""
        protocol = FakeDeadLinkProtocol(ICConnectionError("unused"))
        conn, disconnects = self._connection_with(protocol, keepalive_interval=60.0)

        task = asyncio.create_task(conn._keepalive_loop())
        conn._keepalive_task = task
        await asyncio.sleep(0.01)
        task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await task

        assert disconnects == []


class TestHandlerSingleStarter:
    """ICConnectionHandler must never stack a second reconnect loop."""

    @pytest.mark.asyncio
    async def test_concurrent_disconnects_spawn_one_starter(self):
        controller = ICBaseController("192.168.1.100")
        handler = ICConnectionHandler(
            controller, time_between_reconnects=1, disconnect_debounce_time=1
        )

        async def fake_starter(initial_delay: int = 0) -> None:
            await asyncio.Event().wait()  # a reconnect loop that never finishes

        handler._starter = fake_starter  # type: ignore[method-assign]

        handler._on_disconnect(controller, None)
        first = handler._starter_task
        handler._on_disconnect(controller, ConnectionResetError("second disconnect path"))

        try:
            assert first is not None
            assert handler._starter_task is first
        finally:
            for task in (handler._starter_task, handler._disconnect_debounce_task):
                if task:
                    task.cancel()
                    with contextlib.suppress(asyncio.CancelledError):
                        await task


class TestHandlerStarterResilience:
    """The reconnect loop itself must survive request-level timeouts."""

    @pytest.mark.asyncio
    async def test_starter_retries_after_ic_timeout_error(self):
        """ICTimeoutError from controller.start() must not kill reconnection.

        send_request raises ICTimeoutError (an ICError, not a TimeoutError),
        so the retry loop's `except TimeoutError` never matched and a request
        timeout during a reconnect attempt ended reconnection permanently.
        """
        controller = ICBaseController("192.168.1.100")
        attempts = 0

        async def failing_start() -> None:
            nonlocal attempts
            attempts += 1
            raise ICTimeoutError("Request GetParamList timed out")

        controller.start = failing_start  # type: ignore[method-assign]
        handler = ICConnectionHandler(
            controller, time_between_reconnects=0, disconnect_debounce_time=1
        )

        task = asyncio.create_task(handler._starter(initial_delay=0))
        await asyncio.sleep(0.05)

        try:
            assert not task.done()  # previously: task died on the first ICTimeoutError
            assert attempts >= 2  # and it kept retrying
        finally:
            task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await task


class TestWebSocketEndToEnd:
    """End-to-end checks against a real websockets server."""

    @staticmethod
    async def _run_server_close_scenario(code: int) -> tuple[list[Exception | None], ICConnection]:
        """Connect, have the server close with the given code, await the callback."""
        close_now = asyncio.Event()

        async def handler(ws: Any) -> None:
            await close_now.wait()
            await ws.close(code=code)

        disconnected = asyncio.Event()
        disconnects: list[Exception | None] = []

        def on_disconnect(exc: Exception | None) -> None:
            disconnects.append(exc)
            disconnected.set()

        server = await websockets.serve(handler, "127.0.0.1", 0)
        try:
            port = server.sockets[0].getsockname()[1]
            conn = ICConnection("127.0.0.1", port=port, transport="websocket")
            conn.set_disconnect_callback(on_disconnect)
            await conn.connect()
            try:
                close_now.set()
                await asyncio.wait_for(disconnected.wait(), timeout=2.0)
            finally:
                await conn.disconnect()
        finally:
            server.close()
            await server.wait_closed()

        return disconnects, conn

    @pytest.mark.asyncio
    async def test_server_clean_close_triggers_disconnect(self):
        """Close code 1000: iteration ends normally - callback must still fire."""
        disconnects, conn = await self._run_server_close_scenario(code=1000)

        assert disconnects == [None]
        assert conn.connected is False

    @pytest.mark.asyncio
    async def test_server_abnormal_close_triggers_disconnect(self):
        """Close code 4000: websockets raises ConnectionClosedError - callback must fire."""
        disconnects, conn = await self._run_server_close_scenario(code=4000)

        assert len(disconnects) == 1
        assert isinstance(disconnects[0], ConnectionClosedError)
        assert conn.connected is False

    @pytest.mark.asyncio
    async def test_unresponsive_server_keepalive_aborts_connection(self, monkeypatch):
        """Server accepts but never answers: the keepalive must detect and abort."""

        async def handler(ws: Any) -> None:
            with contextlib.suppress(Exception):
                async for _message in ws:
                    pass  # swallow requests, never answer

        monkeypatch.setattr(connection_module, "KEEPALIVE_TIMEOUT", 0.2, raising=False)

        disconnected = asyncio.Event()
        disconnects: list[Exception | None] = []

        def on_disconnect(exc: Exception | None) -> None:
            disconnects.append(exc)
            disconnected.set()

        server = await websockets.serve(handler, "127.0.0.1", 0)
        try:
            port = server.sockets[0].getsockname()[1]
            conn = ICConnection(
                "127.0.0.1", port=port, transport="websocket", keepalive_interval=0.05
            )
            conn.set_disconnect_callback(on_disconnect)
            await conn.connect()
            try:
                await asyncio.wait_for(disconnected.wait(), timeout=2.0)
            finally:
                await conn.disconnect()
        finally:
            server.close()
            await server.wait_closed()

        assert len(disconnects) == 1
        assert isinstance(disconnects[0], ICTimeoutError)
        assert conn.connected is False
