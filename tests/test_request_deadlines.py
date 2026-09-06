"""Regression tests for bounded request queue, write, and response waits."""

from __future__ import annotations

import asyncio
import contextlib
import time
from typing import Any
from unittest.mock import MagicMock

import orjson
import pytest

from pyintellicenter import ICConnection, ICTimeoutError
from pyintellicenter import connection as connection_module
from pyintellicenter.connection import ICProtocol, ICWebSocketTransport


def _connected_tcp(
    *, request_total_timeout: float | None = 60.0
) -> tuple[ICConnection, ICProtocol, MagicMock]:
    connection = ICConnection(
        "host",
        keepalive_interval=3600,
        request_total_timeout=request_total_timeout,
    )
    protocol = ICProtocol()
    transport = MagicMock()
    protocol.connection_made(transport)
    connection._protocol = protocol
    return connection, protocol, transport


class _BlockingWebSocket:
    def __init__(self) -> None:
        self.send_started = asyncio.Event()
        self.sent: list[str] = []
        self.close_calls = 0

    async def send(self, packet: str) -> None:
        self.sent.append(packet)
        self.send_started.set()
        await asyncio.Event().wait()

    async def close(self) -> None:
        self.close_calls += 1


def _connected_websocket() -> tuple[ICConnection, ICWebSocketTransport, _BlockingWebSocket]:
    connection = ICConnection("host", transport="websocket", keepalive_interval=3600)
    transport = ICWebSocketTransport(disconnect_callback=connection._on_disconnect)
    websocket = _BlockingWebSocket()
    transport._ws = websocket
    transport._connected = True
    connection._protocol = transport
    return connection, transport, websocket


class TestRequestTotalDeadline:
    @pytest.mark.asyncio
    async def test_connection_default_bounds_request_lock_wait(self):
        connection, _protocol, transport = _connected_tcp(request_total_timeout=0.03)
        await connection._request_lock.acquire()
        started = time.monotonic()

        try:
            with pytest.raises(ICTimeoutError) as exc_info:
                async with asyncio.timeout(0.3):
                    await connection.send_request("GetParamList", request_timeout=0.2)
        finally:
            connection._request_lock.release()

        assert time.monotonic() - started < 0.15
        assert exc_info.value.delivery_uncertain is False
        transport.write.assert_not_called()

    @pytest.mark.asyncio
    async def test_caller_cancellation_during_lock_wait_propagates(self):
        connection, _protocol, transport = _connected_tcp(request_total_timeout=1.0)
        await connection._request_lock.acquire()
        task = asyncio.create_task(connection.send_request("GetParamList"))
        await asyncio.sleep(0)

        task.cancel()
        try:
            with pytest.raises(asyncio.CancelledError):
                await task
        finally:
            connection._request_lock.release()

        assert task.cancelled()
        transport.write.assert_not_called()

    @pytest.mark.asyncio
    async def test_total_deadline_uses_remaining_response_budget_without_replay(self):
        connection, _protocol, transport = _connected_tcp()
        await connection._request_lock.acquire()
        started = time.monotonic()
        task = asyncio.create_task(
            connection.send_request(
                "SetParamList",
                request_timeout=0.2,
                total_timeout=0.08,
            )
        )

        await asyncio.sleep(0.04)
        connection._request_lock.release()

        with pytest.raises(ICTimeoutError) as exc_info:
            async with asyncio.timeout(0.3):
                await task

        assert 0.06 <= time.monotonic() - started < 0.18
        assert exc_info.value.delivery_uncertain is True
        assert transport.write.call_count == 1
        await asyncio.sleep(0.03)
        assert transport.write.call_count == 1

    @pytest.mark.asyncio
    async def test_caller_cancellation_during_response_wait_clears_pending_state(self):
        connection, protocol, transport = _connected_tcp()
        task = asyncio.create_task(
            connection.send_request(
                "GetParamList",
                request_timeout=1.0,
                total_timeout=1.0,
            )
        )
        await asyncio.sleep(0)
        assert protocol._pending_message_id is not None

        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task

        assert protocol._pending_message_id is None
        assert protocol._response_future is None
        packet = orjson.loads(transport.write.call_args.args[0])
        assert "total_timeout" not in packet

    @pytest.mark.asyncio
    async def test_disabled_total_timeout_preserves_response_only_timeout(self):
        connection, _protocol, transport = _connected_tcp(request_total_timeout=0.01)
        await connection._request_lock.acquire()
        started = time.monotonic()
        task = asyncio.create_task(
            connection.send_request(
                "GetParamList",
                request_timeout=0.03,
                total_timeout=None,
            )
        )

        await asyncio.sleep(0.04)
        assert not task.done()
        connection._request_lock.release()

        with pytest.raises(ICTimeoutError) as exc_info:
            async with asyncio.timeout(0.3):
                await task

        assert time.monotonic() - started >= 0.06
        assert exc_info.value.delivery_uncertain is True
        packet = orjson.loads(transport.write.call_args.args[0])
        assert "total_timeout" not in packet


class TestWebSocketWriteDeadline:
    @pytest.mark.asyncio
    async def test_blocked_send_deadline_closes_transport_once(self):
        connection, transport, websocket = _connected_websocket()
        disconnects: list[Exception | None] = []
        connection.set_disconnect_callback(disconnects.append)
        started = time.monotonic()

        with pytest.raises(ICTimeoutError) as exc_info:
            async with asyncio.timeout(0.3):
                await connection.send_request(
                    "SetParamList",
                    request_timeout=0.2,
                    total_timeout=0.03,
                )

        if transport._close_task is not None:
            await transport._close_task

        assert time.monotonic() - started < 0.15
        assert exc_info.value.delivery_uncertain is True
        assert connection.connected is False
        assert websocket.close_calls == 1
        assert len(disconnects) == 1
        assert transport._pending_message_id is None
        assert transport._response_future is None

    @pytest.mark.asyncio
    async def test_caller_cancellation_during_send_closes_transport_once(self):
        connection, transport, websocket = _connected_websocket()
        disconnects: list[Exception | None] = []
        connection.set_disconnect_callback(disconnects.append)
        task = asyncio.create_task(
            connection.send_request(
                "SetParamList",
                request_timeout=1.0,
                total_timeout=1.0,
            )
        )
        await websocket.send_started.wait()

        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        if transport._close_task is not None:
            await transport._close_task

        assert task.cancelled()
        assert connection.connected is False
        assert websocket.close_calls == 1
        assert len(disconnects) == 1
        assert transport._pending_message_id is None
        assert transport._response_future is None


class TestKeepaliveRequestDeadline:
    @pytest.mark.asyncio
    async def test_queued_commands_do_not_delay_dead_link_disconnect(self, monkeypatch):
        monkeypatch.setattr(connection_module, "KEEPALIVE_TIMEOUT", 0.03)
        monkeypatch.setattr(connection_module, "KEEPALIVE_MAX_FAILURES", 1)
        connection, protocol, transport = _connected_tcp(request_total_timeout=None)
        connection._keepalive_interval = 0.01
        disconnects: list[Exception | None] = []
        commands = [
            asyncio.create_task(
                connection.send_request(
                    "SetParamList",
                    request_timeout=0.3,
                    total_timeout=0.3,
                    objectList=[{"objnam": f"C00{index}"}],
                )
            )
            for index in range(3)
        ]
        await asyncio.sleep(0)
        assert protocol._pending_message_id is not None
        keepalive = asyncio.create_task(connection._keepalive_loop())
        connection._keepalive_task = keepalive
        started = time.monotonic()
        disconnected = asyncio.Event()

        def record_disconnect(exc: Exception | None) -> None:
            disconnects.append(exc)
            disconnected.set()

        connection.set_disconnect_callback(record_disconnect)

        try:
            await asyncio.wait_for(disconnected.wait(), timeout=0.2)
        finally:
            for task in commands:
                task.cancel()
            await asyncio.gather(*commands, return_exceptions=True)
            if not keepalive.done():
                keepalive.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await keepalive

        assert time.monotonic() - started < 0.15
        assert len(disconnects) == 1
        assert isinstance(disconnects[0], ICTimeoutError)
        assert connection.connected is False
        assert transport.write.call_count == 1

    @pytest.mark.asyncio
    async def test_successful_command_resets_keepalive_miss_counter(self, monkeypatch):
        monkeypatch.setattr(connection_module, "KEEPALIVE_TIMEOUT", 0.02)
        monkeypatch.setattr(connection_module, "KEEPALIVE_MAX_FAILURES", 2)
        connection, protocol, transport = _connected_tcp()
        connection._keepalive_interval = 0.06
        disconnects: list[Exception | None] = []
        connection.set_disconnect_callback(disconnects.append)
        writes = 0
        first_probe_written = asyncio.Event()
        second_probe_written = asyncio.Event()

        def write(packet: bytes) -> None:
            nonlocal writes
            writes += 1
            request: dict[str, Any] = orjson.loads(packet)
            if writes == 1:
                first_probe_written.set()
            elif request["command"] == "GetFoo":
                protocol._handle_response(
                    {
                        "command": "SendParamList",
                        "messageID": request["messageID"],
                        "response": "200",
                    }
                )
            elif writes == 3:
                second_probe_written.set()

        transport.write.side_effect = write
        keepalive = asyncio.create_task(connection._keepalive_loop())
        connection._keepalive_task = keepalive

        try:
            await asyncio.wait_for(first_probe_written.wait(), timeout=0.2)
            response = await connection.send_request(
                "GetFoo",
                request_timeout=0.1,
                total_timeout=0.1,
            )
            assert response["response"] == "200"
            await asyncio.wait_for(second_probe_written.wait(), timeout=0.2)
            await asyncio.sleep(0.03)

            assert disconnects == []
            assert connection.connected is True
        finally:
            if not keepalive.done():
                keepalive.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await keepalive


def test_timeout_error_defaults_to_certain_non_delivery() -> None:
    error = ICTimeoutError("request expired while queued")

    assert error.delivery_uncertain is False
