"""Tests for pyintellicenter connection module (Protocol-based)."""

import asyncio
import logging
from types import SimpleNamespace
from unittest.mock import MagicMock, call, patch

import orjson
import pytest

import pyintellicenter.connection as connection_module
from pyintellicenter import ICConnection, ICConnectionError, ICResponseError, ICTimeoutError
from pyintellicenter.connection import (
    CONNECTION_TIMEOUT,
    DEFAULT_PORT,
    DEFAULT_TCP_PORT,
    DEFAULT_WEBSOCKET_PORT,
    ICProtocol,
    ICWebSocketTransport,
)


class TestICProtocol:
    """Tests for ICProtocol class."""

    def test_init(self):
        """Test protocol initialization."""
        protocol = ICProtocol()
        assert protocol.connected is False
        assert protocol._buffer == b""
        assert protocol._message_id == 0

    def test_init_with_callbacks(self):
        """Test protocol initialization with callbacks."""
        notification_cb = MagicMock()
        disconnect_cb = MagicMock()

        protocol = ICProtocol(
            notification_callback=notification_cb,
            disconnect_callback=disconnect_cb,
        )

        assert protocol._notification_callback is notification_cb
        assert protocol._disconnect_callback is disconnect_cb

    @pytest.mark.asyncio
    async def test_connection_made(self):
        """Test connection_made sets up state correctly."""
        protocol = ICProtocol()
        mock_transport = MagicMock()

        protocol.connection_made(mock_transport)

        assert protocol.connected is True
        assert protocol._transport is mock_transport
        assert protocol._buffer == b""
        assert protocol._message_id == 0

    def test_connection_lost_clean_close(self):
        """Test connection_lost with clean close."""
        disconnect_called = []

        def on_disconnect(exc):
            disconnect_called.append(exc)

        protocol = ICProtocol(disconnect_callback=on_disconnect)
        protocol._connected = True

        protocol.connection_lost(None)

        assert protocol.connected is False
        assert len(disconnect_called) == 1
        assert disconnect_called[0] is None

    def test_connection_lost_with_error(self):
        """Test connection_lost with exception."""
        disconnect_called = []

        def on_disconnect(exc):
            disconnect_called.append(exc)

        protocol = ICProtocol(disconnect_callback=on_disconnect)
        protocol._connected = True

        test_error = ConnectionResetError("Connection reset")
        protocol.connection_lost(test_error)

        assert protocol.connected is False
        assert len(disconnect_called) == 1
        assert disconnect_called[0] is test_error

    @pytest.mark.asyncio
    async def test_connection_lost_cancels_pending_future(self):
        """Test connection_lost cancels pending response future."""
        protocol = ICProtocol()
        mock_transport = MagicMock()
        protocol.connection_made(mock_transport)

        # Simulate a pending request
        loop = asyncio.get_running_loop()
        protocol._response_future = loop.create_future()

        protocol.connection_lost(ConnectionResetError("Reset"))

        assert protocol._response_future.done()
        with pytest.raises(ICConnectionError):
            protocol._response_future.result()

    @pytest.mark.asyncio
    async def test_data_received_complete_message(self):
        """Test data_received with complete message."""
        notifications = []

        def on_notification(msg):
            notifications.append(msg)

        protocol = ICProtocol(notification_callback=on_notification)
        mock_transport = MagicMock()
        protocol.connection_made(mock_transport)

        # Send NotifyList notification
        data = b'{"command":"NotifyList","objectList":[{"objnam":"PUMP1"}]}\r\n'
        protocol.data_received(data)

        # Allow queue consumer task to process (notifications are now async)
        await asyncio.sleep(0.01)

        assert len(notifications) == 1
        assert notifications[0]["command"] == "NotifyList"

    @pytest.mark.asyncio
    async def test_data_received_partial_message(self):
        """Test data_received handles partial messages."""
        notifications = []

        def on_notification(msg):
            notifications.append(msg)

        protocol = ICProtocol(notification_callback=on_notification)
        mock_transport = MagicMock()
        protocol.connection_made(mock_transport)

        # Send partial message
        protocol.data_received(b'{"command":"NotifyList"')
        assert len(notifications) == 0
        assert protocol._buffer == bytearray(b'{"command":"NotifyList"')

        # Complete the message
        protocol.data_received(b',"objectList":[]}\r\n')

        # Allow queue consumer task to process (notifications are now async)
        await asyncio.sleep(0.01)

        assert len(notifications) == 1
        assert protocol._buffer == bytearray()

    @pytest.mark.asyncio
    async def test_data_received_multiple_messages(self):
        """Test data_received handles multiple messages in one buffer."""
        notifications = []

        def on_notification(msg):
            notifications.append(msg)

        protocol = ICProtocol(notification_callback=on_notification)
        mock_transport = MagicMock()
        protocol.connection_made(mock_transport)

        # Send two messages at once
        data = (
            b'{"command":"NotifyList","objectList":[{"objnam":"PUMP1"}]}\r\n'
            b'{"command":"NotifyList","objectList":[{"objnam":"PUMP2"}]}\r\n'
        )
        protocol.data_received(data)

        # Allow queue consumer task to process (notifications are now async)
        await asyncio.sleep(0.01)

        assert len(notifications) == 2

    @pytest.mark.asyncio
    async def test_data_received_response_resolves_future(self):
        """Test data_received resolves pending future for response."""
        protocol = ICProtocol()
        mock_transport = MagicMock()
        protocol.connection_made(mock_transport)

        # Create a pending future with matching message ID
        loop = asyncio.get_running_loop()
        protocol._response_future = loop.create_future()
        protocol._pending_message_id = "1"

        # Receive response with matching messageID
        data = b'{"command":"SendParamList","messageID":"1","response":"200"}\r\n'
        protocol.data_received(data)

        assert protocol._response_future.done()
        result = protocol._response_future.result()
        assert result["response"] == "200"

    @pytest.mark.asyncio
    async def test_data_received_response_ignores_wrong_message_id(self):
        """Test data_received ignores responses with non-matching messageID."""
        protocol = ICProtocol()
        mock_transport = MagicMock()
        protocol.connection_made(mock_transport)

        # Create a pending future expecting messageID "1"
        loop = asyncio.get_running_loop()
        protocol._response_future = loop.create_future()
        protocol._pending_message_id = "1"

        # Receive response with different messageID (from another client)
        data = b'{"command":"WriteParamList","messageID":"uuid-from-another-client","response":"200"}\r\n'
        protocol.data_received(data)

        # Future should NOT be resolved - it doesn't match our messageID
        assert not protocol._response_future.done()

    @pytest.mark.asyncio
    async def test_data_received_invalid_json(self):
        """Test data_received handles invalid JSON gracefully."""
        protocol = ICProtocol()
        mock_transport = MagicMock()
        protocol.connection_made(mock_transport)

        # Send invalid JSON - should not crash
        data = b"not valid json\r\n"
        protocol.data_received(data)

        assert protocol._buffer == b""

    @pytest.mark.asyncio
    async def test_data_received_buffer_overflow_protection(self):
        """Test data_received protects against buffer overflow."""
        protocol = ICProtocol()
        mock_transport = MagicMock()
        protocol.connection_made(mock_transport)

        # Send huge data without terminator
        huge_data = b"x" * (1024 * 1024 + 1)  # Over 1MB
        protocol.data_received(huge_data)

        # Transport should be closed
        mock_transport.close.assert_called_once()

    def test_message_id_increments(self):
        """Test message ID increments."""
        protocol = ICProtocol()

        assert protocol._next_message_id() == "1"
        assert protocol._next_message_id() == "2"
        assert protocol._next_message_id() == "3"

    @pytest.mark.asyncio
    async def test_close(self):
        """Test close method."""
        protocol = ICProtocol()
        mock_transport = MagicMock()
        protocol.connection_made(mock_transport)

        protocol.close()

        assert protocol.connected is False
        mock_transport.close.assert_called_once()


class TestICConnection:
    """Tests for ICConnection class."""

    def test_init_default_values(self):
        """Test default initialization values."""
        conn = ICConnection("192.168.1.100")

        assert conn.host == "192.168.1.100"
        assert conn.port == DEFAULT_PORT
        assert conn.connected is False

    def test_init_custom_values(self):
        """Test initialization with custom values."""
        conn = ICConnection(
            "10.0.0.50",
            port=6680,
            response_timeout=60.0,
            keepalive_interval=120.0,
        )

        assert conn.host == "10.0.0.50"
        assert conn.port == 6680
        assert conn._response_timeout == 60.0
        assert conn._keepalive_interval == 120.0

    def test_not_connected_initially(self):
        """Test that connection is not connected initially."""
        conn = ICConnection("192.168.1.100")
        assert conn.connected is False

    def test_repr(self):
        """Test repr representation."""
        conn = ICConnection("192.168.1.100", port=6680)
        repr_str = repr(conn)
        assert "ICConnection" in repr_str
        assert "192.168.1.100" in repr_str
        assert "6680" in repr_str

    @pytest.mark.asyncio
    async def test_connect_success(self):
        """Test successful connection."""
        conn = ICConnection("192.168.1.100")

        mock_transport = MagicMock()
        mock_protocol = MagicMock(spec=ICProtocol)
        mock_protocol.connected = True

        async def mock_create_connection(protocol_factory, host, port):
            protocol = protocol_factory()
            protocol.connection_made(mock_transport)
            return (mock_transport, protocol)

        with patch.object(
            asyncio.get_event_loop(),
            "create_connection",
            side_effect=mock_create_connection,
        ):
            loop = asyncio.get_event_loop()
            with patch.object(loop, "create_connection", side_effect=mock_create_connection):
                await conn.connect()

        # Protocol should be set (even if mock)
        assert conn._protocol is not None

    @pytest.mark.asyncio
    async def test_connect_timeout(self):
        """Test connection timeout."""
        conn = ICConnection("192.168.1.100")

        async def slow_create_connection(*args, **kwargs):
            await asyncio.sleep(CONNECTION_TIMEOUT + 1)
            return (MagicMock(), ICProtocol())

        with (
            patch(
                "asyncio.AbstractEventLoop.create_connection", side_effect=slow_create_connection
            ),
            pytest.raises(ICConnectionError),
        ):
            await conn.connect()

    @pytest.mark.asyncio
    async def test_connect_refused(self):
        """Test connection refused."""
        conn = ICConnection("192.168.1.100")

        # This will fail because there's no server listening
        # Just verify error handling
        with (
            patch(
                "asyncio.AbstractEventLoop.create_connection",
                side_effect=OSError("Connection refused"),
            ),
            pytest.raises(ICConnectionError),
        ):
            await conn.connect()

    @pytest.mark.asyncio
    async def test_send_request_not_connected(self):
        """Test send_request when not connected."""
        conn = ICConnection("192.168.1.100")

        with pytest.raises(ICConnectionError):
            await conn.send_request("GetParamList")

    def test_set_notification_callback(self):
        """Test setting notification callback."""
        conn = ICConnection("192.168.1.100")

        callback = MagicMock()
        conn.set_notification_callback(callback)
        assert conn._notification_callback is callback

        conn.set_notification_callback(None)
        assert conn._notification_callback is None

    def test_set_disconnect_callback(self):
        """Test setting disconnect callback."""
        conn = ICConnection("192.168.1.100")

        callback = MagicMock()
        conn.set_disconnect_callback(callback)
        assert conn._disconnect_callback is callback

        conn.set_disconnect_callback(None)
        assert conn._disconnect_callback is None

    @pytest.mark.asyncio
    async def test_disconnect_not_connected(self):
        """Test disconnect when not connected is a no-op."""
        conn = ICConnection("192.168.1.100")
        assert conn.connected is False

        # Should not raise
        await conn.disconnect()
        assert conn.connected is False


class TestICResponseError:
    """Tests for ICResponseError exception."""

    def test_init_with_code_only(self):
        """Test initialization with code only."""
        err = ICResponseError("400")
        assert err.code == "400"
        assert "400" in str(err)

    def test_init_with_message(self):
        """Test initialization with code and message."""
        err = ICResponseError("400", "Bad request")
        assert err.code == "400"
        assert err.message == "Bad request"
        assert "400" in str(err)
        assert "Bad request" in str(err)

    def test_repr(self):
        """Test repr representation."""
        err = ICResponseError("400", "Bad request")
        repr_str = repr(err)
        assert "ICResponseError" in repr_str
        assert "400" in repr_str


class TestICConnectionError:
    """Tests for ICConnectionError exception."""

    def test_inheritance(self):
        """Test ICConnectionError is an Exception."""
        from pyintellicenter import ICError

        err = ICConnectionError("Connection failed")
        assert isinstance(err, ICError)
        assert isinstance(err, Exception)
        assert "Connection failed" in str(err)


class TestICProtocolIntegration:
    """Integration tests using ICProtocol directly."""

    @pytest.mark.asyncio
    async def test_send_request_success(self):
        """Test successful request/response through protocol."""
        protocol = ICProtocol()
        mock_transport = MagicMock()
        protocol.connection_made(mock_transport)

        # Start the send_request in a task
        async def do_request():
            return await protocol.send_request("GetParamList", request_timeout=1.0)

        task = asyncio.create_task(do_request())

        # Give it a moment to start
        await asyncio.sleep(0.01)

        # Simulate response arriving
        response_data = b'{"command":"SendParamList","messageID":"1","response":"200"}\r\n'
        protocol.data_received(response_data)

        result = await task
        assert result["response"] == "200"

    @pytest.mark.asyncio
    async def test_send_request_error_response(self):
        """Test request with error response."""
        protocol = ICProtocol()
        mock_transport = MagicMock()
        protocol.connection_made(mock_transport)

        async def do_request():
            return await protocol.send_request("GetParamList", request_timeout=1.0)

        task = asyncio.create_task(do_request())
        await asyncio.sleep(0.01)

        # Simulate error response
        response_data = b'{"command":"SendParamList","messageID":"1","response":"400"}\r\n'
        protocol.data_received(response_data)

        with pytest.raises(ICResponseError) as exc_info:
            await task

        assert exc_info.value.code == "400"

    @pytest.mark.asyncio
    async def test_send_request_timeout(self):
        """Test request timeout."""
        protocol = ICProtocol()
        mock_transport = MagicMock()
        protocol.connection_made(mock_transport)

        with pytest.raises(ICTimeoutError):
            await protocol.send_request("GetParamList", request_timeout=0.1)

    @pytest.mark.asyncio
    async def test_notification_callback_sync(self):
        """Test sync notification callback (processed via queue)."""
        notifications = []

        def on_notification(msg):
            notifications.append(msg)

        protocol = ICProtocol(notification_callback=on_notification)
        mock_transport = MagicMock()
        protocol.connection_made(mock_transport)

        notification_data = b'{"command":"NotifyList","objectList":[{"objnam":"PUMP1"}]}\r\n'
        protocol.data_received(notification_data)

        # Allow queue consumer task to process (sync callbacks are also queued)
        await asyncio.sleep(0.01)

        assert len(notifications) == 1
        assert notifications[0]["command"] == "NotifyList"

    @pytest.mark.asyncio
    async def test_notification_callback_async(self):
        """Test async notification callback."""
        notifications = []

        async def on_notification(msg):
            notifications.append(msg)

        protocol = ICProtocol(notification_callback=on_notification)
        mock_transport = MagicMock()
        protocol.connection_made(mock_transport)

        notification_data = b'{"command":"NotifyList","objectList":[{"objnam":"PUMP1"}]}\r\n'
        protocol.data_received(notification_data)

        # Give async callback time to run
        await asyncio.sleep(0.01)

        assert len(notifications) == 1
        assert notifications[0]["command"] == "NotifyList"

    @pytest.mark.asyncio
    async def test_notification_before_response(self):
        """Test handling notification before response."""
        notifications = []

        def on_notification(msg):
            notifications.append(msg)

        protocol = ICProtocol(notification_callback=on_notification)
        mock_transport = MagicMock()
        protocol.connection_made(mock_transport)

        async def do_request():
            return await protocol.send_request("GetParamList", request_timeout=1.0)

        task = asyncio.create_task(do_request())
        await asyncio.sleep(0.01)

        # Send notification first
        notification = b'{"command":"NotifyList","objectList":[{"objnam":"PUMP1"}]}\r\n'
        protocol.data_received(notification)

        # Then response
        response = b'{"command":"SendParamList","messageID":"1","response":"200"}\r\n'
        protocol.data_received(response)

        result = await task

        assert len(notifications) == 1
        assert result["response"] == "200"

    @pytest.mark.asyncio
    async def test_send_request_not_connected(self):
        """Test send_request when not connected."""
        protocol = ICProtocol()
        # Not calling connection_made

        with pytest.raises(ICConnectionError):
            await protocol.send_request("GetParamList")


class TestICWebSocketTransport:
    """Tests for ICWebSocketTransport class."""

    def test_init(self):
        """Test WebSocket transport initialization."""
        transport = ICWebSocketTransport()
        assert transport.connected is False
        assert transport._ws is None
        assert transport._message_id == 0

    def test_init_with_callbacks(self):
        """Test WebSocket transport initialization with callbacks."""
        notification_cb = MagicMock()
        disconnect_cb = MagicMock()

        transport = ICWebSocketTransport(
            notification_callback=notification_cb,
            disconnect_callback=disconnect_cb,
        )

        assert transport._notification_callback is notification_cb
        assert transport._disconnect_callback is disconnect_cb

    def test_message_id_increments(self):
        """Test message ID generation."""
        transport = ICWebSocketTransport()

        assert transport._next_message_id() == "1"
        assert transport._next_message_id() == "2"
        assert transport._next_message_id() == "3"

    @pytest.mark.asyncio
    async def test_send_request_not_connected(self):
        """Test send_request when not connected."""
        transport = ICWebSocketTransport()

        with pytest.raises(ICConnectionError):
            await transport.send_request("GetParamList")


class TestICConnectionTransport:
    """Tests for ICConnection transport selection."""

    def test_default_transport_is_tcp(self):
        """Test default transport is TCP."""
        conn = ICConnection("192.168.1.100")
        assert conn.transport_type == "tcp"
        assert conn.port == DEFAULT_TCP_PORT

    def test_explicit_tcp_transport(self):
        """Test explicit TCP transport selection."""
        conn = ICConnection("192.168.1.100", transport="tcp")
        assert conn.transport_type == "tcp"
        assert conn.port == DEFAULT_TCP_PORT

    def test_websocket_transport(self):
        """Test WebSocket transport selection."""
        conn = ICConnection("192.168.1.100", transport="websocket")
        assert conn.transport_type == "websocket"
        assert conn.port == DEFAULT_WEBSOCKET_PORT

    def test_custom_port_overrides_default(self):
        """Test custom port overrides transport default."""
        conn = ICConnection("192.168.1.100", port=8080, transport="tcp")
        assert conn.port == 8080

        conn_ws = ICConnection("192.168.1.100", port=9090, transport="websocket")
        assert conn_ws.port == 9090

    def test_repr_includes_transport(self):
        """Test repr includes transport type."""
        conn = ICConnection("192.168.1.100", transport="websocket")
        repr_str = repr(conn)
        assert "websocket" in repr_str
        assert "192.168.1.100" in repr_str

    def test_default_port_constants(self):
        """Test default port constants."""
        assert DEFAULT_PORT == DEFAULT_TCP_PORT
        assert DEFAULT_TCP_PORT == 6681
        assert DEFAULT_WEBSOCKET_PORT == 6680

    @pytest.mark.asyncio
    async def test_websocket_connect_creates_transport(self):
        """Test WebSocket connect creates ICWebSocketTransport."""
        conn = ICConnection("192.168.1.100", transport="websocket")

        mock_ws = MagicMock()
        mock_ws.__aiter__ = lambda self: iter([])

        async def mock_connect(uri):
            return mock_ws

        with patch("websockets.connect", side_effect=mock_connect):
            await conn.connect()

        assert isinstance(conn._protocol, ICWebSocketTransport)
        assert conn._protocol._notification_observer_state is conn._notification_observer_state
        assert conn.connected is True

        await conn.disconnect()

    @pytest.mark.asyncio
    async def test_tcp_connect_creates_protocol(self):
        """Test TCP connect creates ICProtocol."""
        conn = ICConnection("192.168.1.100", transport="tcp")

        mock_transport = MagicMock()

        async def mock_create_connection(protocol_factory, host, port):
            protocol = protocol_factory()
            protocol._connected = True
            protocol._transport = mock_transport
            return (mock_transport, protocol)

        loop = asyncio.get_running_loop()
        with patch.object(loop, "create_connection", side_effect=mock_create_connection):
            await conn.connect()

        assert isinstance(conn._protocol, ICProtocol)
        assert conn._protocol._notification_observer_state is conn._notification_observer_state

        await conn.disconnect()


class TestSequencedNotificationObservers:
    """Tests for connection-owned enqueue-time notification observers."""

    @pytest.mark.asyncio
    async def test_notification_observer_does_not_replace_primary_callback(self):
        """The raw observer runs before the existing queued callback."""
        primary = MagicMock()
        observer = MagicMock()
        connection = ICConnection("host")
        protocol = ICProtocol(
            notification_callback=primary,
            notification_observer_state=connection._notification_observer_state,
        )
        protocol.connection_made(MagicMock())
        connection._protocol = protocol

        remove = connection.add_notification_observer(observer)
        message = {"command": "NotifyList", "objectList": []}
        protocol._handle_notification(message)

        observer.assert_called_once_with(1, message)
        primary.assert_not_called()
        await asyncio.sleep(0)
        primary.assert_called_once_with(message)

        remove()
        protocol.connection_lost(None)

    @pytest.mark.asyncio
    async def test_observer_added_after_enqueue_never_sees_stale_queued_frame(self):
        """Queue consumption cannot replay an old frame through a new observer."""
        primary = MagicMock()
        connection = ICConnection("host")
        protocol = ICProtocol(
            notification_callback=primary,
            notification_observer_state=connection._notification_observer_state,
        )
        protocol.connection_made(MagicMock())
        connection._protocol = protocol
        stale = {
            "command": "NotifyList",
            "objectList": [{"objnam": "OLD", "params": {}}],
        }
        fresh = {
            "command": "NotifyList",
            "objectList": [{"objnam": "NEW", "params": {}}],
        }
        protocol._handle_notification(stale)

        observer = MagicMock()
        connection.add_notification_observer(observer)
        await asyncio.sleep(0)
        observer.assert_not_called()

        protocol._handle_notification(fresh)
        observer.assert_called_once_with(2, fresh)
        protocol.connection_lost(None)

    @pytest.mark.asyncio
    async def test_failing_notification_observer_does_not_block_others_or_primary(self):
        """Observer failures are isolated from fanout and the primary queue."""
        primary = MagicMock()
        failing = MagicMock(side_effect=RuntimeError("observer failed"))
        healthy = MagicMock()
        connection = ICConnection("host")
        protocol = ICProtocol(
            notification_callback=primary,
            notification_observer_state=connection._notification_observer_state,
        )
        protocol.connection_made(MagicMock())
        connection._protocol = protocol
        connection.add_notification_observer(failing)
        connection.add_notification_observer(healthy)
        message = {"command": "NotifyList", "objectList": []}

        protocol._handle_notification(message)

        failing.assert_called_once_with(1, message)
        healthy.assert_called_once_with(1, message)
        await asyncio.sleep(0)
        primary.assert_called_once_with(message)
        protocol.connection_lost(None)

    def test_notification_observer_without_primary_and_idempotent_removal(self):
        """Raw observers need no primary callback and removal is one-shot."""
        connection = ICConnection("host")
        protocol = ICProtocol(
            notification_observer_state=connection._notification_observer_state,
        )
        protocol.connection_made(MagicMock())
        connection._protocol = protocol
        observer = MagicMock()
        remove = connection.add_notification_observer(observer)
        first = {"command": "NotifyList", "objectList": [{"objnam": "ONE"}]}
        second = {"command": "NotifyList", "objectList": [{"objnam": "TWO"}]}

        protocol._handle_notification(first)
        remove()
        remove()
        protocol._handle_notification(second)

        observer.assert_called_once_with(1, first)

    def test_notification_observer_sequence_survives_transport_replacement(self):
        """TCP and WebSocket transports share one connection-owned sequence."""
        connection = ICConnection("host")
        observer = MagicMock()
        connection.add_notification_observer(observer)
        first = {"command": "NotifyList", "objectList": [{"objnam": "TCP"}]}
        second = {"command": "NotifyList", "objectList": [{"objnam": "WS"}]}

        tcp = ICProtocol(
            notification_observer_state=connection._notification_observer_state,
        )
        tcp.connection_made(MagicMock())
        tcp._handle_notification(first)

        websocket = ICWebSocketTransport(
            notification_observer_state=connection._notification_observer_state,
        )
        websocket._connected = True
        websocket._ws = MagicMock()
        websocket._handle_notification(second)

        assert tcp._notification_observer_state is connection._notification_observer_state
        assert websocket._notification_observer_state is connection._notification_observer_state
        assert observer.call_args_list == [call(1, first), call(2, second)]


class TestWriteWatermarks:
    """Tests for request-lock write-time sequence and clock hooks."""

    @pytest.mark.asyncio
    async def test_tcp_before_write_and_after_write_watermark_order(self, monkeypatch):
        """TCP hooks bracket the synchronous write while the request lock is held."""
        connection = ICConnection("host")
        protocol = ICProtocol(
            notification_observer_state=connection._notification_observer_state,
        )
        transport = MagicMock()
        protocol.connection_made(transport)
        connection._protocol = protocol
        observer = MagicMock()
        connection.add_notification_observer(observer)
        events = []
        before_values = []
        after_values = []

        def write(_packet):
            events.append("write")
            protocol._handle_response(
                {
                    "command": "SendParamList",
                    "messageID": protocol._pending_message_id,
                    "response": "200",
                }
            )

        transport.write.side_effect = write

        def before_write(sequence, started_at):
            assert connection._request_lock.locked()
            events.append("before")
            before_values.append((sequence, started_at))

        def after_write(sequence):
            assert connection._request_lock.locked()
            events.append("after")
            after_values.append(sequence)

        await connection._request_lock.acquire()
        request_started = asyncio.Event()

        async def request():
            request_started.set()
            return await connection.send_request(
                "GetParamList",
                request_timeout=1.0,
                _before_write_callback=before_write,
                _after_write_callback=after_write,
            )

        task = asyncio.create_task(request())
        await request_started.wait()
        await asyncio.sleep(0)
        assert not task.done()
        blocked_notification = {"command": "NotifyList", "objectList": []}
        protocol._handle_notification(blocked_notification)

        loop = asyncio.get_running_loop()
        fake_loop_time = 4321.25
        monkeypatch.setattr(
            connection_module,
            "time",
            SimpleNamespace(monotonic=lambda: -987654.0),
            raising=False,
        )
        monkeypatch.setattr(loop, "time", lambda: fake_loop_time)
        connection._request_lock.release()
        result = await task

        assert result["response"] == "200"
        assert events == ["before", "write", "after"]
        assert before_values == [(1, fake_loop_time)]
        assert after_values == [1]
        assert before_values[0][1] != connection_module.time.monotonic()

        later_notification = {"command": "NotifyList", "objectList": [{"objnam": "LATER"}]}
        protocol._handle_notification(later_notification)
        assert observer.call_args_list == [
            call(1, blocked_notification),
            call(2, later_notification),
        ]
        assert after_values[0] < 2

    @pytest.mark.asyncio
    async def test_websocket_suspended_send_updates_after_write_watermark(self, monkeypatch):
        """The WebSocket after hook includes frames accepted while send is suspended."""
        connection = ICConnection("host", transport="websocket")
        websocket = ICWebSocketTransport(
            notification_observer_state=connection._notification_observer_state,
        )
        websocket._connected = True
        connection._protocol = websocket
        observer = MagicMock()
        connection.add_notification_observer(observer)
        send_entered = asyncio.Event()
        release_send = asyncio.Event()
        events = []
        before_values = []
        after_values = []

        class SuspendedWebSocket:
            async def send(self, _packet):
                events.append("send-start")
                send_entered.set()
                await release_send.wait()
                events.append("send-end")
                websocket._handle_response(
                    {
                        "command": "SendParamList",
                        "messageID": websocket._pending_message_id,
                        "response": "200",
                    }
                )

        websocket._ws = SuspendedWebSocket()

        def before_write(sequence, started_at):
            assert connection._request_lock.locked()
            events.append("before")
            before_values.append((sequence, started_at))

        def after_write(sequence):
            assert connection._request_lock.locked()
            events.append("after")
            after_values.append(sequence)

        await connection._request_lock.acquire()
        request_started = asyncio.Event()

        async def request():
            request_started.set()
            return await connection.send_request(
                "GetParamList",
                request_timeout=1.0,
                _before_write_callback=before_write,
                _after_write_callback=after_write,
            )

        task = asyncio.create_task(request())
        await request_started.wait()
        await asyncio.sleep(0)
        assert not task.done()
        blocked_notification = {"command": "NotifyList", "objectList": [{"objnam": "BLOCKED"}]}
        websocket._handle_notification(blocked_notification)

        loop = asyncio.get_running_loop()
        fake_loop_time = 7654.5
        monkeypatch.setattr(
            connection_module,
            "time",
            SimpleNamespace(monotonic=lambda: -123456.0),
            raising=False,
        )
        monkeypatch.setattr(loop, "time", lambda: fake_loop_time)
        connection._request_lock.release()
        await send_entered.wait()
        during_send = {"command": "NotifyList", "objectList": [{"objnam": "DURING"}]}
        websocket._handle_notification(during_send)
        release_send.set()
        result = await task

        assert result["response"] == "200"
        assert events == ["before", "send-start", "send-end", "after"]
        assert before_values == [(1, fake_loop_time)]
        assert after_values == [2]
        assert before_values[0][0] < 2 <= after_values[0]
        assert before_values[0][1] != connection_module.time.monotonic()

        later_notification = {"command": "NotifyList", "objectList": [{"objnam": "LATER"}]}
        websocket._handle_notification(later_notification)
        assert observer.call_args_list == [
            call(1, blocked_notification),
            call(2, during_send),
            call(3, later_notification),
        ]
        assert after_values[0] < 3

    @pytest.mark.asyncio
    @pytest.mark.parametrize("transport_type", ["tcp", "websocket"])
    @pytest.mark.parametrize("failing_hook", ["before", "after"])
    async def test_before_write_or_after_write_failure_cleans_up_request(
        self,
        transport_type,
        failing_hook,
    ):
        """Hook errors clear pending state, release the lock, and permit another request."""
        connection = ICConnection("host", transport=transport_type)
        writes = []

        if transport_type == "tcp":
            protocol = ICProtocol(
                notification_observer_state=connection._notification_observer_state,
            )
            transport = MagicMock()
            protocol.connection_made(transport)

            def write(packet):
                writes.append(packet)
                protocol._handle_response(
                    {
                        "command": "SendParamList",
                        "messageID": protocol._pending_message_id,
                        "response": "200",
                    }
                )

            transport.write.side_effect = write
        else:
            protocol = ICWebSocketTransport(
                notification_observer_state=connection._notification_observer_state,
            )
            protocol._connected = True

            class RespondingWebSocket:
                async def send(self, packet):
                    writes.append(packet)
                    protocol._handle_response(
                        {
                            "command": "SendParamList",
                            "messageID": protocol._pending_message_id,
                            "response": "200",
                        }
                    )

            protocol._ws = RespondingWebSocket()

        connection._protocol = protocol
        after_calls = []

        def before_write(_sequence, _started_at):
            if failing_hook == "before":
                raise RuntimeError("before hook failed")

        def after_write(sequence):
            after_calls.append(sequence)
            if failing_hook == "after":
                raise RuntimeError("after hook failed")

        loop = asyncio.get_running_loop()
        unhandled = []
        previous_handler = loop.get_exception_handler()
        loop.set_exception_handler(lambda _loop, context: unhandled.append(context))
        try:
            with pytest.raises(RuntimeError, match=f"{failing_hook} hook failed"):
                await connection.send_request(
                    "GetParamList",
                    request_timeout=1.0,
                    _before_write_callback=before_write,
                    _after_write_callback=after_write,
                )

            expected_writes = 0 if failing_hook == "before" else 1
            assert len(writes) == expected_writes
            assert len(after_calls) == expected_writes
            assert protocol._pending_message_id is None
            assert protocol._response_future is None
            assert not connection._request_lock.locked()

            response = await connection.send_request("GetParamList", request_timeout=1.0)
            assert response["response"] == "200"
            assert len(writes) == expected_writes + 1
            await asyncio.sleep(0)
        finally:
            loop.set_exception_handler(previous_handler)

        assert unhandled == []


async def _connect_tcp_for_closed_future(connection):
    """Connect a test connection through its real protocol factory."""
    loop = asyncio.get_running_loop()

    async def create_connection(protocol_factory, _host, _port):
        protocol = protocol_factory()
        transport = MagicMock()
        protocol.connection_made(transport)
        return transport, protocol

    with patch.object(loop, "create_connection", side_effect=create_connection):
        await connection.connect()

    assert isinstance(connection._protocol, ICProtocol)
    return connection._protocol


class TestClosedFutureGenerations:
    """Tests for one-shot connection-generation close futures."""

    def test_capture_closed_future_rejects_non_live_connection(self):
        """A caller cannot capture a generation before it is live."""
        connection = ICConnection("host")

        with pytest.raises(ICConnectionError, match="not live"):
            connection._capture_closed_future()

    @pytest.mark.asyncio
    @pytest.mark.parametrize("close_path", ["unexpected", "explicit", "abort"])
    async def test_closed_future_completes_for_every_close_path(self, close_path):
        """Unexpected, deliberate, and abort teardown all close the generation."""
        connection = ICConnection("host", keepalive_interval=3600)
        protocol = await _connect_tcp_for_closed_future(connection)
        closed = connection._capture_closed_future()
        assert not closed.done()

        if close_path == "unexpected":
            protocol.connection_lost(ConnectionResetError("reset"))
        elif close_path == "explicit":
            await connection.disconnect()
        else:
            connection._abort_connection(ICConnectionError("dead link"))

        assert closed.done()
        assert closed.result() is None
        await connection.disconnect()

    @pytest.mark.asyncio
    async def test_explicit_disconnect_does_not_dispatch_unexpected_callback(self):
        """The internal close future is separate from the public failure callback."""
        connection = ICConnection("host", keepalive_interval=3600)
        disconnect_callback = MagicMock()
        connection.set_disconnect_callback(disconnect_callback)
        loop = asyncio.get_running_loop()

        async def create_connection(protocol_factory, _host, _port):
            protocol = protocol_factory()
            transport = MagicMock()
            protocol.connection_made(transport)
            transport.close.side_effect = lambda: protocol.connection_lost(None)
            return transport, protocol

        with patch.object(loop, "create_connection", side_effect=create_connection):
            await connection.connect()

        closed = connection._capture_closed_future()
        await connection.disconnect()

        assert closed.done()
        disconnect_callback.assert_not_called()

    @pytest.mark.asyncio
    @pytest.mark.parametrize("transport_type", ["tcp", "websocket"])
    async def test_failed_connect_completes_closed_future(self, transport_type):
        """Even a connection generation that fails to open has a terminal signal."""
        connection = ICConnection("host", transport=transport_type)

        if transport_type == "tcp":
            loop = asyncio.get_running_loop()
            context = patch.object(
                loop,
                "create_connection",
                side_effect=OSError("connection refused"),
            )
        else:
            context = patch("websockets.connect", side_effect=OSError("connection refused"))

        with context, pytest.raises(ICConnectionError):
            await connection.connect()

        assert connection._closed_future is not None
        assert connection._closed_future.done()
        with pytest.raises(ICConnectionError, match="not live"):
            connection._capture_closed_future()

    @pytest.mark.asyncio
    @pytest.mark.parametrize("transport_type", ["tcp", "websocket"])
    async def test_immediate_disconnect_during_connect_is_failed_generation(self, transport_type):
        """A transport that closes during setup cannot become a live generation."""
        disconnects = []
        connection = ICConnection("host", transport=transport_type)
        connection.set_disconnect_callback(disconnects.append)

        if transport_type == "tcp":
            loop = asyncio.get_running_loop()

            async def create_connection(protocol_factory, _host, _port):
                protocol = protocol_factory()
                transport = MagicMock()
                protocol.connection_made(transport)
                protocol.connection_lost(ConnectionResetError("closed during connect"))
                return transport, protocol

            context = patch.object(loop, "create_connection", side_effect=create_connection)
        else:

            async def connect_and_close(transport, _host, _port):
                transport._ws = MagicMock()
                transport._connected = True
                transport._handle_disconnect(ConnectionResetError("closed during connect"))

            context = patch.object(ICWebSocketTransport, "connect", new=connect_and_close)

        error = None
        try:
            with context:
                try:
                    await connection.connect()
                except ICConnectionError as err:
                    error = err

            assert error is not None
            assert "closed during setup" in str(error)
            assert not connection.connected
            assert connection._closed_future is not None
            assert connection._closed_future.done()
            assert connection._keepalive_task is None
            assert len(disconnects) == 1
            assert isinstance(disconnects[0], ConnectionResetError)
            assert connection._disconnect_dispatched is True
        finally:
            await connection.disconnect()

    @pytest.mark.asyncio
    async def test_concurrent_connects_cannot_cross_complete_closed_futures(self):
        """A second attempt waits and cannot steal the first attempt's close signal."""
        connection = ICConnection("host", keepalive_interval=3600)
        loop = asyncio.get_running_loop()
        first_entered = asyncio.Event()
        release_first = asyncio.Event()
        second_entered = asyncio.Event()
        create_calls = 0

        async def create_connection(protocol_factory, _host, _port):
            nonlocal create_calls
            create_calls += 1
            if create_calls == 1:
                first_entered.set()
                await release_first.wait()
                raise OSError("first attempt failed")

            second_entered.set()
            protocol = protocol_factory()
            transport = MagicMock()
            protocol.connection_made(transport)
            return transport, protocol

        with patch.object(loop, "create_connection", side_effect=create_connection):
            first_task = asyncio.create_task(connection.connect())
            await first_entered.wait()
            first_closed = connection._closed_future
            assert first_closed is not None

            second_task = asyncio.create_task(connection.connect())
            await asyncio.sleep(0)
            second_started_before_release = second_entered.is_set()
            release_first.set()
            first_result, second_result = await asyncio.gather(
                first_task,
                second_task,
                return_exceptions=True,
            )

        try:
            assert not second_started_before_release
            assert isinstance(first_result, ICConnectionError)
            assert second_result is None
            assert first_closed.done()
            second_closed = connection._capture_closed_future()
            assert second_closed is not first_closed
            assert not second_closed.done()
            assert connection.connected
        finally:
            await connection.disconnect()

    @pytest.mark.asyncio
    async def test_closed_future_is_distinct_across_same_instance_reconnect(self):
        """A reconnect cannot clear a previously captured close signal."""
        connection = ICConnection("host", keepalive_interval=3600)
        disconnect_callback = MagicMock()
        connection.set_disconnect_callback(disconnect_callback)
        loop = asyncio.get_running_loop()
        protocols = []

        async def create_connection(protocol_factory, _host, _port):
            protocol = protocol_factory()
            transport = MagicMock()
            protocol.connection_made(transport)
            protocols.append(protocol)
            return transport, protocol

        with patch.object(loop, "create_connection", side_effect=create_connection):
            await connection.connect()
            first_closed = connection._capture_closed_future()
            protocols[0].connection_lost(ConnectionResetError("first generation closed"))
            assert first_closed.done()
            disconnect_callback.assert_called_once()

            await connection.connect()
            second_closed = connection._capture_closed_future()

            protocols[0].connection_lost(ConnectionResetError("late old disconnect"))

        assert second_closed is not first_closed
        assert not second_closed.done()
        assert first_closed.done()
        disconnect_callback.assert_called_once()
        assert protocols[0]._notification_observer_state is connection._notification_observer_state
        assert protocols[1]._notification_observer_state is connection._notification_observer_state

        await connection.disconnect()
        assert second_closed.done()


class _ScriptedWebSocket:
    """Async-iterable WebSocket fake driven by a frame queue.

    Feed str frames to deliver them to the reader, an Exception instance to
    raise it from the iterator, or ``_ScriptedWebSocket.CLOSE`` to end
    iteration (clean server close).
    """

    CLOSE = object()

    def __init__(self) -> None:
        self.frames: asyncio.Queue[object] = asyncio.Queue()
        self.sent: list[str] = []
        self.close_awaited = False
        self.close_calls = 0

    def feed(self, frame: object) -> None:
        self.frames.put_nowait(frame)

    def __aiter__(self) -> "_ScriptedWebSocket":
        return self

    async def __anext__(self) -> object:
        frame = await self.frames.get()
        if frame is self.CLOSE:
            raise StopAsyncIteration
        if isinstance(frame, Exception):
            raise frame
        return frame

    async def send(self, packet: str) -> None:
        self.sent.append(packet)

    async def close(self) -> None:
        await asyncio.sleep(0)
        self.close_calls += 1
        self.close_awaited = True


def _start_ws_transport(ws, **kwargs) -> ICWebSocketTransport:
    """Wire a fake WebSocket into a transport and start its reader loop."""
    transport = ICWebSocketTransport(**kwargs)
    transport._ws = ws
    transport._connected = True
    transport._disconnect_handled = False
    if transport._notification_callback:
        transport._start_notification_consumer()
    transport._reader_task = asyncio.create_task(transport._reader_loop())
    return transport


class TestQueuedRequestDisconnectRace:
    """Issue #57: a request queued behind the lock must fail cleanly.

    A request that passes the connected pre-check and then parks on the
    request lock must raise ICConnectionError - never AttributeError - when
    the connection is torn down (or replaced) before the lock is granted.
    """

    @pytest.mark.asyncio
    async def test_request_queued_during_disconnect_raises_connection_error(self):
        connection = ICConnection("host", keepalive_interval=3600)
        await _connect_tcp_for_closed_future(connection)

        await connection._request_lock.acquire()
        task = asyncio.create_task(connection.send_request("GetParamList", request_timeout=1.0))
        await asyncio.sleep(0)  # passes the pre-check, parks on the lock
        assert not task.done()

        await connection.disconnect()
        connection._request_lock.release()

        with pytest.raises(ICConnectionError):
            await task

    @pytest.mark.asyncio
    async def test_request_queued_during_keepalive_abort_raises_connection_error(self):
        connection = ICConnection("host", keepalive_interval=3600)
        await _connect_tcp_for_closed_future(connection)

        await connection._request_lock.acquire()
        task = asyncio.create_task(connection.send_request("GetParamList", request_timeout=1.0))
        await asyncio.sleep(0)
        assert not task.done()

        connection._abort_connection(ICConnectionError("keepalive declared the link dead"))
        connection._request_lock.release()

        with pytest.raises(ICConnectionError):
            await task
        await connection.disconnect()

    @pytest.mark.asyncio
    async def test_queued_request_is_not_sent_on_a_new_generation(self):
        """A reconnect during the wait must not receive the stale request."""
        connection = ICConnection("host", keepalive_interval=3600)
        loop = asyncio.get_running_loop()
        transports = []

        async def create_connection(protocol_factory, _host, _port):
            protocol = protocol_factory()
            transport = MagicMock()
            protocol.connection_made(transport)
            transports.append(transport)
            return transport, protocol

        with patch.object(loop, "create_connection", side_effect=create_connection):
            await connection.connect()

            await connection._request_lock.acquire()
            task = asyncio.create_task(connection.send_request("GetParamList", request_timeout=1.0))
            await asyncio.sleep(0)
            assert not task.done()

            await connection.disconnect()
            await connection.connect()  # new generation
            connection._request_lock.release()

            with pytest.raises(ICConnectionError):
                await task

        transports[1].write.assert_not_called()
        await connection.disconnect()


class TestNonObjectJsonFrames:
    """Issue #58: valid JSON with a non-object root must be skipped, not fatal."""

    NON_OBJECT_FRAMES = [b"123", b'"response"', b"[]", b"null", b"true"]

    @pytest.mark.asyncio
    async def test_tcp_survives_non_object_frames(self):
        notifications = []
        protocol = ICProtocol(notification_callback=notifications.append)
        transport = MagicMock()
        protocol.connection_made(transport)

        for frame in self.NON_OBJECT_FRAMES:
            protocol.data_received(frame + b"\r\n")

        transport.close.assert_not_called()
        assert protocol.connected is True
        assert protocol._buffer == bytearray()

        # The connection still works: a request round-trips...
        task = asyncio.create_task(protocol.send_request("GetParamList", request_timeout=1.0))
        await asyncio.sleep(0.01)
        protocol.data_received(b'{"command":"SendParamList","messageID":"1","response":"200"}\r\n')
        result = await task
        assert result["response"] == "200"

        # ...and notifications still flow.
        protocol.data_received(b'{"command":"NotifyList","objectList":[]}\r\n')
        await asyncio.sleep(0.01)
        assert len(notifications) == 1
        protocol.connection_lost(None)

    @pytest.mark.asyncio
    async def test_websocket_survives_non_object_frames(self):
        disconnects = []
        ws = _ScriptedWebSocket()
        transport = _start_ws_transport(ws, disconnect_callback=disconnects.append)

        for frame in self.NON_OBJECT_FRAMES:
            ws.feed(frame.decode())
        await asyncio.sleep(0.01)

        assert transport.connected is True
        assert transport._reader_task is not None
        assert not transport._reader_task.done()
        assert disconnects == []

        # A subsequent request still round-trips through the live reader.
        task = asyncio.create_task(transport.send_request("GetParamList", request_timeout=1.0))
        await asyncio.sleep(0.01)
        ws.feed('{"command":"SendParamList","messageID":"1","response":"200"}')
        result = await task
        assert result["response"] == "200"

        await transport.aclose()

    @pytest.mark.asyncio
    async def test_websocket_unexpected_reader_error_runs_disconnect_path(self):
        """A dispatch surprise must not leave a silent zombie connection."""
        disconnects = []
        ws = _ScriptedWebSocket()
        transport = _start_ws_transport(ws, disconnect_callback=disconnects.append)

        error = RuntimeError("dispatch surprise")
        ws.feed(error)
        await asyncio.sleep(0.01)

        assert disconnects == [error]
        assert transport.connected is False


class TestWebSocketShutdown:
    """Issue #59: deliberate close must fail in-flight requests and await close."""

    @pytest.mark.asyncio
    async def test_aclose_fails_in_flight_request_fast(self):
        ws = _ScriptedWebSocket()
        transport = _start_ws_transport(ws)

        task = asyncio.create_task(transport.send_request("GetParamList", request_timeout=30.0))
        await asyncio.sleep(0.01)
        assert transport._pending_message_id is not None

        await transport.aclose()

        with pytest.raises(ICConnectionError):
            await asyncio.wait_for(task, timeout=1.0)
        assert ws.close_awaited is True

    @pytest.mark.asyncio
    async def test_sync_close_fails_in_flight_request_fast(self):
        ws = _ScriptedWebSocket()
        transport = _start_ws_transport(ws)

        task = asyncio.create_task(transport.send_request("GetParamList", request_timeout=30.0))
        await asyncio.sleep(0.01)

        transport.close()

        with pytest.raises(ICConnectionError):
            await asyncio.wait_for(task, timeout=1.0)

        assert transport._close_task is not None
        await transport._close_task
        assert ws.close_awaited is True

    @pytest.mark.asyncio
    async def test_connection_disconnect_awaits_websocket_close(self):
        connection = ICConnection("host", transport="websocket", keepalive_interval=3600)
        ws = _ScriptedWebSocket()

        async def fake_connect(_uri):
            return ws

        with patch("websockets.connect", side_effect=fake_connect):
            await connection.connect()

        assert isinstance(connection._protocol, ICWebSocketTransport)
        task = asyncio.create_task(connection.send_request("GetParamList", request_timeout=30.0))
        await asyncio.sleep(0.01)
        assert not task.done()

        await connection.disconnect()

        with pytest.raises(ICConnectionError):
            await asyncio.wait_for(task, timeout=1.0)
        assert ws.close_awaited is True
        assert connection.connected is False


class TestNotificationConsumerLifecycle:
    """Issue #59: consumer teardown races and async-callable callbacks."""

    @pytest.mark.asyncio
    async def test_cancellation_during_async_callback_is_clean(self):
        """Teardown mid-callback must end in CancelledError, not AttributeError."""
        entered = asyncio.Event()
        release = asyncio.Event()

        async def callback(_msg):
            entered.set()
            await release.wait()

        protocol = ICProtocol(notification_callback=callback)
        protocol.connection_made(MagicMock())
        protocol._handle_notification({"command": "NotifyList", "objectList": []})
        await asyncio.wait_for(entered.wait(), timeout=1.0)

        consumer_task = protocol._consumer_task
        assert consumer_task is not None
        protocol._stop_notification_consumer()

        with pytest.raises(asyncio.CancelledError):
            await consumer_task

    @pytest.mark.asyncio
    async def test_async_callable_object_callback_is_awaited(self):
        received = []

        class AsyncCallable:
            async def __call__(self, msg):
                await asyncio.sleep(0)
                received.append(msg)

        protocol = ICProtocol(notification_callback=AsyncCallable())
        protocol.connection_made(MagicMock())
        protocol._handle_notification({"command": "NotifyList", "objectList": []})
        await asyncio.sleep(0.01)

        assert len(received) == 1
        protocol.connection_lost(None)

    @pytest.mark.asyncio
    async def test_sync_callback_returning_awaitable_is_awaited(self):
        received = []

        async def _record(msg):
            received.append(msg)

        def callback(msg):
            return _record(msg)

        protocol = ICProtocol(notification_callback=callback)
        protocol.connection_made(MagicMock())
        protocol._handle_notification({"command": "NotifyList", "objectList": []})
        await asyncio.sleep(0.01)

        assert len(received) == 1
        protocol.connection_lost(None)


class TestReservedRequestFields:
    """Issue #59: protocol-owned request fields cannot be clobbered via kwargs.

    ``messageID`` is caught by the reserved-field guard (ValueError);
    ``command`` cannot even reach **kwargs because it is a named positional
    parameter, so Python itself rejects the duplicate with TypeError.
    """

    RESERVED_CASES = [({"messageID": "999"}, ValueError), ({"command": "Evil"}, TypeError)]

    @pytest.mark.asyncio
    @pytest.mark.parametrize(("reserved_kwargs", "expected_error"), RESERVED_CASES)
    async def test_tcp_rejects_reserved_kwargs(self, reserved_kwargs, expected_error):
        protocol = ICProtocol()
        transport = MagicMock()
        protocol.connection_made(transport)

        with pytest.raises(expected_error):
            await protocol.send_request("GetParamList", request_timeout=1.0, **reserved_kwargs)

        transport.write.assert_not_called()
        assert protocol._pending_message_id is None
        assert protocol._response_future is None

    @pytest.mark.asyncio
    @pytest.mark.parametrize(("reserved_kwargs", "expected_error"), RESERVED_CASES)
    async def test_websocket_rejects_reserved_kwargs(self, reserved_kwargs, expected_error):
        transport = ICWebSocketTransport()
        ws = _ScriptedWebSocket()
        transport._ws = ws
        transport._connected = True

        with pytest.raises(expected_error):
            await transport.send_request("GetParamList", request_timeout=1.0, **reserved_kwargs)

        assert ws.sent == []
        assert transport._pending_message_id is None

    @pytest.mark.asyncio
    async def test_connection_rejects_reserved_kwargs_and_releases_lock(self):
        connection = ICConnection("host", keepalive_interval=3600)
        protocol = await _connect_tcp_for_closed_future(connection)

        def write(_packet):
            protocol._handle_response(
                {
                    "command": "SendParamList",
                    "messageID": protocol._pending_message_id,
                    "response": "200",
                }
            )

        protocol._transport.write.side_effect = write

        with pytest.raises(ValueError, match="eserved"):
            await connection.send_request("GetParamList", request_timeout=1.0, messageID="7")

        assert not connection._request_lock.locked()
        response = await connection.send_request("GetParamList", request_timeout=1.0)
        assert response["response"] == "200"
        await connection.disconnect()


class TestTcpFraming:
    """Issue #60: cursor-based framing must stay correct across chunk boundaries."""

    @staticmethod
    def _protocol_with_notifications():
        notifications = []
        protocol = ICProtocol(notification_callback=notifications.append)
        protocol.connection_made(MagicMock())
        return protocol, notifications

    @pytest.mark.asyncio
    async def test_crlf_split_across_chunks(self):
        protocol, notifications = self._protocol_with_notifications()

        protocol.data_received(b'{"command":"NotifyList","objectList":[]}\r')
        await asyncio.sleep(0)
        assert notifications == []

        protocol.data_received(b"\n")
        await asyncio.sleep(0.01)
        assert len(notifications) == 1
        assert protocol._buffer == bytearray()
        protocol.connection_lost(None)

    @pytest.mark.asyncio
    async def test_message_delivered_byte_by_byte(self):
        protocol, notifications = self._protocol_with_notifications()
        message = b'{"command":"NotifyList","objectList":[{"objnam":"PUMP1"}]}\r\n'

        for i in range(len(message)):
            protocol.data_received(message[i : i + 1])

        await asyncio.sleep(0.01)
        assert len(notifications) == 1
        assert notifications[0]["objectList"] == [{"objnam": "PUMP1"}]
        assert protocol._buffer == bytearray()
        protocol.connection_lost(None)

    @pytest.mark.asyncio
    async def test_message_split_at_every_boundary(self):
        message = b'{"command":"NotifyList","objectList":[{"objnam":"PUMP1"}]}\r\n'
        for split in range(1, len(message)):
            protocol, notifications = self._protocol_with_notifications()
            protocol.data_received(message[:split])
            protocol.data_received(message[split:])
            await asyncio.sleep(0.01)
            assert len(notifications) == 1, f"failed at split {split}"
            assert protocol._buffer == bytearray()
            protocol.connection_lost(None)

    @pytest.mark.asyncio
    async def test_batched_messages_with_trailing_partial(self):
        protocol, notifications = self._protocol_with_notifications()
        partial = b'{"command":"NotifyList","objectList":[{"objnam":"P3"'

        protocol.data_received(
            b'{"command":"NotifyList","objectList":[{"objnam":"P1"}]}\r\n'
            b'{"command":"NotifyList","objectList":[{"objnam":"P2"}]}\r\n' + partial
        )
        await asyncio.sleep(0.01)
        assert len(notifications) == 2
        assert protocol._buffer == bytearray(partial)

        protocol.data_received(b"}]}\r\n")
        await asyncio.sleep(0.01)
        assert len(notifications) == 3
        assert [n["objectList"][0]["objnam"] for n in notifications] == ["P1", "P2", "P3"]
        assert protocol._buffer == bytearray()
        protocol.connection_lost(None)

    @pytest.mark.asyncio
    async def test_large_frame_across_many_chunks(self):
        protocol, notifications = self._protocol_with_notifications()
        objects = [{"objnam": f"OBJ{i:05d}", "params": {"SNAME": "x" * 50}} for i in range(500)]
        message = orjson.dumps({"command": "NotifyList", "objectList": objects}) + b"\r\n"

        chunk_size = 1024
        for offset in range(0, len(message), chunk_size):
            protocol.data_received(message[offset : offset + chunk_size])

        await asyncio.sleep(0.01)
        assert len(notifications) == 1
        assert len(notifications[0]["objectList"]) == 500
        assert protocol._buffer == bytearray()
        protocol.connection_lost(None)


class TestNotificationQueueOverflow:
    """Issue #60: overflow drops keep task_done accounting and do not spam logs."""

    @pytest.mark.asyncio
    async def test_dropped_items_are_accounted_for_queue_join(self):
        entered = asyncio.Event()
        release = asyncio.Event()
        processed = []

        async def callback(msg):
            entered.set()
            await release.wait()
            processed.append(msg)

        protocol = ICProtocol(notification_callback=callback, notification_queue_size=1)
        protocol.connection_made(MagicMock())
        queue = protocol._notification_queue
        assert queue is not None

        def notify(objnam):
            protocol._handle_notification(
                {"command": "NotifyList", "objectList": [{"objnam": objnam}]}
            )

        notify("N1")
        await asyncio.wait_for(entered.wait(), timeout=1.0)  # consumer holds N1
        notify("N2")  # queued
        notify("N3")  # overflow: drops N2
        notify("N4")  # overflow: drops N3

        release.set()
        await asyncio.wait_for(queue.join(), timeout=1.0)

        assert [m["objectList"][0]["objnam"] for m in processed] == ["N1", "N4"]
        protocol.connection_lost(None)

    @pytest.mark.asyncio
    async def test_overflow_logging_is_summarized(self, caplog):
        entered = asyncio.Event()
        release = asyncio.Event()

        async def callback(_msg):
            entered.set()
            await release.wait()

        protocol = ICProtocol(notification_callback=callback, notification_queue_size=1)
        protocol.connection_made(MagicMock())

        protocol._handle_notification({"command": "NotifyList", "objectList": []})
        await asyncio.wait_for(entered.wait(), timeout=1.0)

        with caplog.at_level(logging.WARNING, logger="pyintellicenter.connection"):
            for _ in range(10):
                protocol._handle_notification({"command": "NotifyList", "objectList": []})

        drop_warnings = [r for r in caplog.records if "queue full" in r.getMessage()]
        assert len(drop_warnings) == 1

        release.set()
        protocol.connection_lost(None)


class _SlowCancelWebSocket(_ScriptedWebSocket):
    """WebSocket whose reader takes a moment to unwind after cancellation.

    Holds the reader task in its cancellation path until ``cancel_release``
    is set, keeping ``aclose()`` parked on its await of the reader long
    enough for the test to cancel the ``aclose()`` caller itself.
    """

    def __init__(self) -> None:
        super().__init__()
        self.cancel_started = asyncio.Event()
        self.cancel_release = asyncio.Event()

    async def __anext__(self) -> object:
        try:
            return await super().__anext__()
        except asyncio.CancelledError:
            self.cancel_started.set()
            await self.cancel_release.wait()
            raise


class TestAcloseCallerCancellation:
    """Issue #75: aclose() must not swallow its caller's own cancellation.

    Suppressing CancelledError while awaiting the reader/consumer/close
    tasks cannot distinguish "child finished cancelled" from "the aclose()
    caller was cancelled" - a cancelled HA unload must report cancelled,
    not falsely succeed.
    """

    @pytest.mark.asyncio
    async def test_cancelling_aclose_caller_propagates(self):
        ws = _SlowCancelWebSocket()
        transport = _start_ws_transport(ws)
        reader = transport._reader_task

        caller = asyncio.create_task(transport.aclose())
        await asyncio.wait_for(ws.cancel_started.wait(), timeout=1.0)

        caller.cancel()
        outcome = None
        try:
            await caller
        except asyncio.CancelledError:
            outcome = "cancelled"
        finally:
            ws.cancel_release.set()
            await asyncio.wait((reader,))

        assert outcome == "cancelled"
        assert caller.cancelled() is True

    @pytest.mark.asyncio
    async def test_timeout_around_aclose_converts_to_timeout_error(self):
        ws = _SlowCancelWebSocket()
        transport = _start_ws_transport(ws)
        reader = transport._reader_task
        await asyncio.sleep(0)  # let the reader park on the frame queue

        try:
            with pytest.raises(TimeoutError):
                async with asyncio.timeout(0.05):
                    await transport.aclose()
        finally:
            ws.cancel_release.set()
            await asyncio.wait((reader,))


class TestSelfDisconnectFromNotificationCallback:
    """Issue #75: a callback calling disconnect() must not orphan the consumer.

    The consumer task runs the callback; stopping it must never
    cancel-and-await the currently executing task - the self-cancellation
    would be consumed by the close path and the consumer would resume,
    waiting forever on its detached queue.
    """

    @pytest.mark.asyncio
    async def test_async_callback_disconnect_completes_cleanly(self):
        connection = ICConnection("host", transport="websocket", keepalive_interval=3600)
        ws = _ScriptedWebSocket()
        callback_done = asyncio.Event()

        async def callback(_msg):
            await connection.disconnect()
            callback_done.set()

        connection.set_notification_callback(callback)

        async def fake_connect(_uri):
            return ws

        with patch("websockets.connect", side_effect=fake_connect):
            await connection.connect()

        transport = connection._protocol
        assert isinstance(transport, ICWebSocketTransport)
        consumer_task = transport._consumer_task
        assert consumer_task is not None

        ws.feed('{"command":"NotifyList","objectList":[]}')

        await asyncio.wait_for(callback_done.wait(), timeout=1.0)
        # The consumer must exit deterministically instead of resuming a
        # wait on its now-detached queue.
        await asyncio.wait_for(consumer_task, timeout=1.0)
        assert consumer_task.done() is True
        assert connection.connected is False
        assert ws.close_calls == 1


class TestWebSocketReaderErrorClosesSocket:
    """Issue #75: an unexpected reader error must close the websocket.

    _handle_disconnect() used to discard the handle without closing it,
    leaving the panel session alive until GC (IntelliCenter has a small
    concurrent-client budget).
    """

    @pytest.mark.asyncio
    async def test_dispatch_error_closes_websocket_exactly_once(self):
        disconnects = []
        ws = _ScriptedWebSocket()
        transport = _start_ws_transport(ws, disconnect_callback=disconnects.append)
        transport._dispatch_message = MagicMock(side_effect=RuntimeError("dispatch surprise"))

        ws.feed('{"command":"NotifyList","objectList":[]}')
        await asyncio.sleep(0.01)

        assert transport.connected is False
        assert len(disconnects) == 1

        close_task = transport._close_task
        assert close_task is not None
        await close_task
        assert ws.close_calls == 1

        # A later aclose() must not close the discarded socket again.
        await transport.aclose()
        assert ws.close_calls == 1
