"""Regression tests for bounded request queue, write, and response waits."""

from __future__ import annotations

import asyncio
import contextlib
from typing import Any
from unittest.mock import MagicMock

import orjson
import pytest

from pyintellicenter import ICConnection, ICConnectionError, ICTimeoutError
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


def _record_response_timeouts(monkeypatch: pytest.MonkeyPatch, protocol: ICProtocol) -> list[float]:
    """Capture the response budget ICConnection hands to the protocol."""
    response_timeouts: list[float] = []
    protocol_send_request = protocol.send_request

    async def record_response_timeout(
        command: str, request_timeout: float, **kwargs: Any
    ) -> dict[str, Any]:
        response_timeouts.append(request_timeout)
        return await protocol_send_request(command, request_timeout, **kwargs)

    monkeypatch.setattr(protocol, "send_request", record_response_timeout)
    return response_timeouts


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

        try:
            with pytest.raises(ICTimeoutError) as exc_info:
                async with asyncio.timeout(0.3):
                    await connection.send_request("GetParamList", request_timeout=0.2)
        finally:
            connection._request_lock.release()

        assert exc_info.value.delivery_uncertain is False
        transport.write.assert_not_called()

    @pytest.mark.asyncio
    async def test_deadline_expired_when_lock_granted_never_writes(self, monkeypatch):
        connection, _protocol, transport = _connected_tcp()
        loop = asyncio.get_running_loop()
        loop_time = loop.time
        await connection._request_lock.acquire()
        task = asyncio.create_task(
            connection.send_request("SetParamList", request_timeout=0.2, total_timeout=0.01)
        )
        await asyncio.sleep(0)
        assert not task.done()

        # Move the loop clock past the deadline, then hand the lock over: the
        # lock grant and the expired deadline timer land in the same loop
        # iteration, with the grant running first.
        monkeypatch.setattr(loop, "time", lambda: loop_time() + 1.0)
        connection._request_lock.release()

        with pytest.raises(ICTimeoutError) as exc_info:
            async with asyncio.timeout(1.0):
                await task

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
    async def test_total_deadline_uses_remaining_response_budget_without_replay(self, monkeypatch):
        connection, protocol, transport = _connected_tcp()
        response_timeouts = _record_response_timeouts(monkeypatch, protocol)
        written = asyncio.Event()
        await connection._request_lock.acquire()
        task = asyncio.create_task(
            connection.send_request(
                "SetParamList",
                request_timeout=0.6,
                total_timeout=0.2,
                _after_write_callback=lambda _sequence: written.set(),
            )
        )
        await asyncio.sleep(0)
        assert not written.is_set()

        connection._request_lock.release()
        async with asyncio.timeout(1.0):
            await written.wait()

        # The response stage got what was left of the total budget, not the
        # caller's response-only timeout.
        assert len(response_timeouts) == 1
        assert 0.0 < response_timeouts[0] <= 0.2

        with pytest.raises(ICTimeoutError) as exc_info:
            async with asyncio.timeout(1.0):
                await task

        assert "total timeout of 0.2s" in str(exc_info.value)
        assert exc_info.value.delivery_uncertain is True
        assert transport.write.call_count == 1

    @pytest.mark.asyncio
    async def test_clipped_response_wait_names_total_budget(self, monkeypatch):
        connection, protocol, _transport = _connected_tcp()
        response_timeouts: list[float] = []

        async def expire_response_wait(
            command: str, request_timeout: float, **_kwargs: Any
        ) -> dict[str, Any]:
            response_timeouts.append(request_timeout)
            raise ICTimeoutError(
                f"Request {command} timed out after {request_timeout}s",
                delivery_uncertain=True,
            )

        monkeypatch.setattr(protocol, "send_request", expire_response_wait)
        loop = asyncio.get_running_loop()
        loop_time = loop.time
        await connection._request_lock.acquire()
        task = asyncio.create_task(
            connection.send_request("SetParamList", request_timeout=1.0, total_timeout=0.5)
        )
        await asyncio.sleep(0)
        assert not task.done()

        # Hand the lock over with ~0.2s of the total budget left, so the
        # response window is clipped from 1.0s to what remains. The transport
        # then reports that clipped window expiring.
        monkeypatch.setattr(loop, "time", lambda: loop_time() + 0.3)
        connection._request_lock.release()

        with pytest.raises(ICTimeoutError) as exc_info:
            async with asyncio.timeout(1.0):
                await task

        assert len(response_timeouts) == 1
        assert response_timeouts[0] < 1.0
        message = str(exc_info.value)
        assert "total timeout of 0.5s" in message
        assert "response timeout 1.0s" in message
        assert "timed out after" not in message
        assert exc_info.value.delivery_uncertain is True
        assert isinstance(exc_info.value.__cause__, ICTimeoutError)

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
    async def test_disabled_total_timeout_preserves_response_only_timeout(self, monkeypatch):
        connection, protocol, transport = _connected_tcp(request_total_timeout=0.01)
        response_timeouts = _record_response_timeouts(monkeypatch, protocol)
        loop = asyncio.get_running_loop()
        loop_time = loop.time
        await connection._request_lock.acquire()
        task = asyncio.create_task(
            connection.send_request(
                "GetParamList",
                request_timeout=0.03,
                total_timeout=None,
            )
        )
        await asyncio.sleep(0)
        assert not task.done()

        # Hand the lock over well past the connection default this call opted
        # out of: the request must still go out with its full response budget.
        monkeypatch.setattr(loop, "time", lambda: loop_time() + 1.0)
        connection._request_lock.release()

        with pytest.raises(ICTimeoutError) as exc_info:
            async with asyncio.timeout(1.0):
                await task

        assert response_timeouts == [0.03]
        assert "timed out after 0.03s" in str(exc_info.value)
        assert exc_info.value.delivery_uncertain is True
        packet = orjson.loads(transport.write.call_args.args[0])
        assert "total_timeout" not in packet


class TestWebSocketWriteDeadline:
    @pytest.mark.asyncio
    async def test_blocked_send_deadline_closes_transport_once(self):
        connection, transport, websocket = _connected_websocket()
        disconnects: list[Exception | None] = []
        connection.set_disconnect_callback(disconnects.append)

        with pytest.raises(ICTimeoutError) as exc_info:
            async with asyncio.timeout(0.3):
                await connection.send_request(
                    "SetParamList",
                    request_timeout=0.2,
                    total_timeout=0.03,
                )

        if transport._close_task is not None:
            await transport._close_task

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

    @pytest.mark.asyncio
    async def test_lock_wait_deadline_never_sends(self):
        connection, transport, websocket = _connected_websocket()
        disconnects: list[Exception | None] = []
        connection.set_disconnect_callback(disconnects.append)
        await connection._request_lock.acquire()

        try:
            with pytest.raises(ICTimeoutError) as exc_info:
                async with asyncio.timeout(1.0):
                    await connection.send_request(
                        "SetParamList",
                        request_timeout=0.2,
                        total_timeout=0.03,
                    )
        finally:
            connection._request_lock.release()

        # Nothing reached the socket, so delivery is certainly not underway
        # and the transport stays usable.
        assert exc_info.value.delivery_uncertain is False
        assert websocket.sent == []
        assert websocket.close_calls == 0
        assert connection.connected is True
        assert disconnects == []
        assert transport._pending_message_id is None

    @pytest.mark.asyncio
    async def test_send_cancel_tolerates_cleared_response_future(self):
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

        # A teardown that already dropped the pending-request state must not
        # turn the cancelled send into an AttributeError.
        transport._clear_pending_request()
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        if transport._close_task is not None:
            await transport._close_task

        assert task.cancelled()
        assert connection.connected is False
        assert websocket.close_calls == 1
        assert len(disconnects) == 1
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

        assert len(disconnects) == 1
        assert isinstance(disconnects[0], ICTimeoutError)
        assert connection.connected is False
        assert transport.write.call_count == 1

    @pytest.mark.asyncio
    async def test_successful_command_resets_keepalive_miss_counter(self, monkeypatch):
        monkeypatch.setattr(connection_module, "KEEPALIVE_TIMEOUT", 0.02)
        monkeypatch.setattr(connection_module, "KEEPALIVE_MAX_FAILURES", 2)
        connection, protocol, transport = _connected_tcp()
        connection._keepalive_interval = 0.05
        disconnects: list[Exception | None] = []
        connection.set_disconnect_callback(disconnects.append)
        probe_missed = asyncio.Event()
        send_request = connection.send_request

        async def observe_probe_misses(command: str, **kwargs: Any) -> dict[str, Any]:
            try:
                return await send_request(command, **kwargs)
            except ICTimeoutError:
                if command == "GetParamList":
                    probe_missed.set()
                raise

        monkeypatch.setattr(connection, "send_request", observe_probe_misses)

        def write(packet: bytes) -> None:
            request: dict[str, Any] = orjson.loads(packet)
            if request["command"] == "GetFoo":
                protocol._handle_response(
                    {
                        "command": "SendParamList",
                        "messageID": request["messageID"],
                        "response": "200",
                    }
                )

        transport.write.side_effect = write
        keepalive = asyncio.create_task(connection._keepalive_loop())
        connection._keepalive_task = keepalive

        try:
            # The keepalive loop scores the miss before it suspends again, so
            # the counter is settled by the time this wait returns.
            async with asyncio.timeout(1.0):
                await probe_missed.wait()
            assert connection._keepalive_failures == 1

            response = await connection.send_request(
                "GetFoo",
                request_timeout=0.1,
                total_timeout=0.1,
            )
            assert response["response"] == "200"
            assert connection._keepalive_failures == 0

            probe_missed.clear()
            async with asyncio.timeout(1.0):
                await probe_missed.wait()
            assert connection._keepalive_failures == 1
            assert disconnects == []
            assert connection.connected is True
            assert not keepalive.done()
        finally:
            keepalive.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await keepalive

    @pytest.mark.asyncio
    async def test_websocket_probe_send_deadline_disconnects_once(self, monkeypatch):
        monkeypatch.setattr(connection_module, "KEEPALIVE_TIMEOUT", 0.02)
        connection, transport, websocket = _connected_websocket()
        connection._keepalive_interval = 0.01
        disconnects: list[Exception | None] = []
        connection.set_disconnect_callback(disconnects.append)
        keepalive = asyncio.create_task(connection._keepalive_loop())
        connection._keepalive_task = keepalive

        async with asyncio.timeout(1.0):
            await websocket.send_started.wait()
            await keepalive
        if transport._close_task is not None:
            await transport._close_task

        # The loop must exit through the deadline path, not by swallowing a
        # self-cancel: a cancel request left pending on the finished task
        # would mean _handle_current_disconnect cancelled the very task it
        # was running in.
        assert not keepalive.cancelled()
        assert keepalive.exception() is None
        assert keepalive.cancelling() == 0
        assert connection._keepalive_task is None
        assert connection._keepalive_failures == 0
        assert connection.connected is False
        assert websocket.close_calls == 1
        assert len(disconnects) == 1
        assert isinstance(disconnects[0], ICConnectionError)
        assert transport._pending_message_id is None
        assert transport._response_future is None


def test_timeout_error_defaults_to_certain_non_delivery() -> None:
    error = ICTimeoutError("request expired while queued")

    assert error.delivery_uncertain is False
