"""Tests for pyintellicenter connection module (Protocol-based)."""

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from pyintellicenter import ICConnection, ICConnectionError, ICResponseError
from pyintellicenter.connection import (
    CONNECTION_TIMEOUT,
    DEFAULT_PORT,
    ICProtocol,
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
        assert protocol._buffer == b'{"command":"NotifyList"'

        # Complete the message
        protocol.data_received(b',"objectList":[]}\r\n')
        assert len(notifications) == 1
        assert protocol._buffer == b""

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

        assert len(notifications) == 2

    @pytest.mark.asyncio
    async def test_data_received_response_resolves_future(self):
        """Test data_received resolves pending future for response."""
        protocol = ICProtocol()
        mock_transport = MagicMock()
        protocol.connection_made(mock_transport)

        # Create a pending future
        loop = asyncio.get_running_loop()
        protocol._response_future = loop.create_future()

        # Receive response
        data = b'{"command":"SendParamList","messageID":"1","response":"200"}\r\n'
        protocol.data_received(data)

        assert protocol._response_future.done()
        result = protocol._response_future.result()
        assert result["response"] == "200"

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
            protocol._connected = True
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

        with patch("asyncio.AbstractEventLoop.create_connection", side_effect=slow_create_connection):
            with pytest.raises(ICConnectionError):
                await conn.connect()

    @pytest.mark.asyncio
    async def test_connect_refused(self):
        """Test connection refused."""
        conn = ICConnection("192.168.1.100")

        with pytest.raises(ICConnectionError):
            # This will fail because there's no server listening
            # Just verify error handling
            with patch(
                "asyncio.AbstractEventLoop.create_connection",
                side_effect=OSError("Connection refused"),
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

        with pytest.raises(TimeoutError):
            await protocol.send_request("GetParamList", request_timeout=0.1)

    @pytest.mark.asyncio
    async def test_notification_callback_sync(self):
        """Test sync notification callback."""
        notifications = []

        def on_notification(msg):
            notifications.append(msg)

        protocol = ICProtocol(notification_callback=on_notification)
        mock_transport = MagicMock()
        protocol.connection_made(mock_transport)

        notification_data = b'{"command":"NotifyList","objectList":[{"objnam":"PUMP1"}]}\r\n'
        protocol.data_received(notification_data)

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
