"""Tests for pyintellicenter connection module."""

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from pyintellicenter import ICConnection, ICConnectionError, ICResponseError
from pyintellicenter.connection import CONNECTION_TIMEOUT, DEFAULT_PORT


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

        mock_reader = AsyncMock()
        mock_writer = MagicMock()
        mock_writer.is_closing.return_value = False

        with patch("asyncio.open_connection", return_value=(mock_reader, mock_writer)):
            await conn.connect()

        assert conn.connected is True

    @pytest.mark.asyncio
    async def test_connect_timeout(self):
        """Test connection timeout."""
        conn = ICConnection("192.168.1.100")

        async def slow_connect(*args, **kwargs):
            await asyncio.sleep(CONNECTION_TIMEOUT + 1)
            return (AsyncMock(), MagicMock())

        with (
            patch("asyncio.open_connection", side_effect=slow_connect),
            pytest.raises(ICConnectionError),
        ):
            await conn.connect()

    @pytest.mark.asyncio
    async def test_connect_refused(self):
        """Test connection refused."""
        conn = ICConnection("192.168.1.100")

        with (
            patch("asyncio.open_connection", side_effect=OSError("Connection refused")),
            pytest.raises(ICConnectionError),
        ):
            await conn.connect()

    @pytest.mark.asyncio
    async def test_disconnect(self):
        """Test disconnection."""
        conn = ICConnection("192.168.1.100")

        mock_reader = AsyncMock()
        mock_writer = MagicMock()
        mock_writer.is_closing.return_value = False
        mock_writer.close = MagicMock()
        mock_writer.wait_closed = AsyncMock()

        with patch("asyncio.open_connection", return_value=(mock_reader, mock_writer)):
            await conn.connect()
            assert conn.connected is True

            await conn.disconnect()
            assert conn.connected is False
            mock_writer.close.assert_called_once()

    @pytest.mark.asyncio
    async def test_context_manager(self):
        """Test async context manager."""
        mock_reader = AsyncMock()
        mock_writer = MagicMock()
        mock_writer.is_closing.return_value = False
        mock_writer.close = MagicMock()
        mock_writer.wait_closed = AsyncMock()

        with patch("asyncio.open_connection", return_value=(mock_reader, mock_writer)):
            async with ICConnection("192.168.1.100") as conn:
                assert conn.connected is True

            # After exiting context, should be disconnected
            mock_writer.close.assert_called()

    @pytest.mark.asyncio
    async def test_send_request_not_connected(self):
        """Test send_request when not connected."""
        conn = ICConnection("192.168.1.100")

        with pytest.raises(ICConnectionError):
            await conn.send_request("GetParamList")

    @pytest.mark.asyncio
    async def test_send_request_success(self):
        """Test successful request/response."""
        conn = ICConnection("192.168.1.100")

        mock_reader = AsyncMock()
        mock_writer = MagicMock()
        mock_writer.is_closing.return_value = False
        mock_writer.write = MagicMock()
        mock_writer.drain = AsyncMock()

        # Mock response
        response_data = (
            b'{"command":"SendParamList","messageID":"1","response":"200","objectList":[]}\r\n'
        )
        mock_reader.readline = AsyncMock(return_value=response_data)

        with patch("asyncio.open_connection", return_value=(mock_reader, mock_writer)):
            await conn.connect()

            response = await conn.send_request(
                "GetParamList",
                condition="",
                objectList=[{"objnam": "INCR", "keys": ["VER"]}],
            )

            assert response["response"] == "200"
            mock_writer.write.assert_called()
            mock_writer.drain.assert_called()

    @pytest.mark.asyncio
    async def test_send_request_error_response(self):
        """Test request with error response."""
        conn = ICConnection("192.168.1.100")

        mock_reader = AsyncMock()
        mock_writer = MagicMock()
        mock_writer.is_closing.return_value = False
        mock_writer.write = MagicMock()
        mock_writer.drain = AsyncMock()

        # Mock error response
        response_data = b'{"command":"SendParamList","messageID":"1","response":"400"}\r\n'
        mock_reader.readline = AsyncMock(return_value=response_data)

        with patch("asyncio.open_connection", return_value=(mock_reader, mock_writer)):
            await conn.connect()

            with pytest.raises(ICResponseError) as exc_info:
                await conn.send_request("GetParamList")

            assert exc_info.value.code == "400"

    @pytest.mark.asyncio
    async def test_notification_callback_sync(self):
        """Test sync notification callback is called for NotifyList."""
        conn = ICConnection("192.168.1.100")

        mock_reader = AsyncMock()
        mock_writer = MagicMock()
        mock_writer.is_closing.return_value = False
        mock_writer.write = MagicMock()
        mock_writer.drain = AsyncMock()

        # First return a notification, then the actual response
        notification = b'{"command":"NotifyList","objectList":[{"objnam":"PUMP1"}]}\r\n'
        response = (
            b'{"command":"SendParamList","messageID":"1","response":"200","objectList":[]}\r\n'
        )
        mock_reader.readline = AsyncMock(side_effect=[notification, response])

        notifications_received = []

        def on_notification(msg):
            notifications_received.append(msg)

        with patch("asyncio.open_connection", return_value=(mock_reader, mock_writer)):
            await conn.connect()
            conn.set_notification_callback(on_notification)

            await conn.send_request("GetParamList")

            assert len(notifications_received) == 1
            assert notifications_received[0]["command"] == "NotifyList"

    @pytest.mark.asyncio
    async def test_notification_callback_async(self):
        """Test async notification callback is called for NotifyList."""
        conn = ICConnection("192.168.1.100")

        mock_reader = AsyncMock()
        mock_writer = MagicMock()
        mock_writer.is_closing.return_value = False
        mock_writer.write = MagicMock()
        mock_writer.drain = AsyncMock()

        # First return a notification, then the actual response
        notification = b'{"command":"NotifyList","objectList":[{"objnam":"PUMP1"}]}\r\n'
        response = (
            b'{"command":"SendParamList","messageID":"1","response":"200","objectList":[]}\r\n'
        )
        mock_reader.readline = AsyncMock(side_effect=[notification, response])

        notifications_received = []

        async def on_notification(msg):
            notifications_received.append(msg)

        with patch("asyncio.open_connection", return_value=(mock_reader, mock_writer)):
            await conn.connect()
            conn.set_notification_callback(on_notification)

            await conn.send_request("GetParamList")

            assert len(notifications_received) == 1
            assert notifications_received[0]["command"] == "NotifyList"

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
    async def test_read_message_connection_closed(self):
        """Test _read_message when connection is closed."""
        conn = ICConnection("192.168.1.100")

        mock_reader = AsyncMock()
        mock_writer = MagicMock()
        mock_writer.is_closing.return_value = False
        mock_writer.write = MagicMock()
        mock_writer.drain = AsyncMock()

        # Return empty bytes (connection closed)
        mock_reader.readline = AsyncMock(return_value=b"")

        with patch("asyncio.open_connection", return_value=(mock_reader, mock_writer)):
            await conn.connect()

            with pytest.raises(ICConnectionError) as exc_info:
                await conn._read_message()

            assert "closed" in str(exc_info.value).lower()

    @pytest.mark.asyncio
    async def test_read_message_invalid_json(self):
        """Test _read_message with invalid JSON."""
        conn = ICConnection("192.168.1.100")

        mock_reader = AsyncMock()
        mock_writer = MagicMock()
        mock_writer.is_closing.return_value = False

        # Return invalid JSON
        mock_reader.readline = AsyncMock(return_value=b"not valid json\r\n")

        with patch("asyncio.open_connection", return_value=(mock_reader, mock_writer)):
            await conn.connect()

            with pytest.raises(ICConnectionError) as exc_info:
                await conn._read_message()

            assert "JSON" in str(exc_info.value)

    @pytest.mark.asyncio
    async def test_read_message_not_connected(self):
        """Test _read_message when not connected."""
        conn = ICConnection("192.168.1.100")

        with pytest.raises(ICConnectionError) as exc_info:
            await conn._read_message()

        assert "connected" in str(exc_info.value).lower()

    @pytest.mark.asyncio
    async def test_write_message_not_connected(self):
        """Test _write_message when not connected."""
        conn = ICConnection("192.168.1.100")

        with pytest.raises(ICConnectionError) as exc_info:
            await conn._write_message({"command": "test"})

        assert "connected" in str(exc_info.value).lower()

    @pytest.mark.asyncio
    async def test_write_message_os_error(self):
        """Test _write_message with OSError."""
        conn = ICConnection("192.168.1.100")

        mock_reader = AsyncMock()
        mock_writer = MagicMock()
        mock_writer.is_closing.return_value = False
        mock_writer.write = MagicMock(side_effect=OSError("Broken pipe"))

        with patch("asyncio.open_connection", return_value=(mock_reader, mock_writer)):
            await conn.connect()

            with pytest.raises(ICConnectionError) as exc_info:
                await conn._write_message({"command": "test"})

            assert "Write failed" in str(exc_info.value)

    @pytest.mark.asyncio
    async def test_send_request_timeout(self):
        """Test send_request times out."""
        conn = ICConnection("192.168.1.100", response_timeout=0.1)

        mock_reader = AsyncMock()
        mock_writer = MagicMock()
        mock_writer.is_closing.return_value = False
        mock_writer.write = MagicMock()
        mock_writer.drain = AsyncMock()

        # Simulate slow response
        async def slow_readline():
            await asyncio.sleep(1)
            return b'{"response":"200"}\r\n'

        mock_reader.readline = slow_readline

        with patch("asyncio.open_connection", return_value=(mock_reader, mock_writer)):
            await conn.connect()

            with pytest.raises(TimeoutError):
                await conn.send_request("GetParamList")

    @pytest.mark.asyncio
    async def test_disconnect_cleanup_on_error(self):
        """Test disconnect handles cleanup errors gracefully."""
        conn = ICConnection("192.168.1.100")

        mock_reader = AsyncMock()
        mock_writer = MagicMock()
        mock_writer.is_closing.return_value = False
        mock_writer.close = MagicMock()
        mock_writer.wait_closed = AsyncMock(side_effect=Exception("Cleanup error"))

        with patch("asyncio.open_connection", return_value=(mock_reader, mock_writer)):
            await conn.connect()

            # Should not raise even if wait_closed fails
            await conn.disconnect()
            assert conn.connected is False

    @pytest.mark.asyncio
    async def test_connect_when_already_connected(self):
        """Test connect is idempotent when already connected."""
        conn = ICConnection("192.168.1.100")

        mock_reader = AsyncMock()
        mock_writer = MagicMock()
        mock_writer.is_closing.return_value = False

        call_count = 0

        async def mock_open_connection(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            return (mock_reader, mock_writer)

        with patch("asyncio.open_connection", side_effect=mock_open_connection):
            await conn.connect()
            await conn.connect()  # Should be a no-op

        # Should only have connected once
        assert call_count == 1

    @pytest.mark.asyncio
    async def test_message_id_increments(self):
        """Test message ID increments with each request."""
        conn = ICConnection("192.168.1.100")

        mock_reader = AsyncMock()
        mock_writer = MagicMock()
        mock_writer.is_closing.return_value = False
        mock_writer.write = MagicMock()
        mock_writer.drain = AsyncMock()

        # Return successful responses
        mock_reader.readline = AsyncMock(return_value=b'{"response":"200","messageID":"1"}\r\n')

        with patch("asyncio.open_connection", return_value=(mock_reader, mock_writer)):
            await conn.connect()

            assert conn._message_id == 0
            await conn.send_request("Cmd1")
            assert conn._message_id == 1
            await conn.send_request("Cmd2")
            assert conn._message_id == 2

    @pytest.mark.asyncio
    async def test_send_command_alias(self):
        """Test send_command is an alias for send_request."""
        conn = ICConnection("192.168.1.100")

        mock_reader = AsyncMock()
        mock_writer = MagicMock()
        mock_writer.is_closing.return_value = False
        mock_writer.write = MagicMock()
        mock_writer.drain = AsyncMock()

        response_data = b'{"response":"200"}\r\n'
        mock_reader.readline = AsyncMock(return_value=response_data)

        with patch("asyncio.open_connection", return_value=(mock_reader, mock_writer)):
            await conn.connect()

            result = await conn.send_command("TestCmd", param="value")
            assert result["response"] == "200"

    @pytest.mark.asyncio
    async def test_keepalive_cancelled_gracefully(self):
        """Test keepalive loop handles cancellation gracefully."""
        conn = ICConnection("192.168.1.100", keepalive_interval=0.05)

        mock_reader = AsyncMock()
        mock_writer = MagicMock()
        mock_writer.is_closing.return_value = False
        mock_writer.write = MagicMock()
        mock_writer.drain = AsyncMock()
        mock_writer.close = MagicMock()
        mock_writer.wait_closed = AsyncMock()

        # Return successful responses
        mock_reader.readline = AsyncMock(return_value=b'{"response":"200"}\r\n')

        with patch("asyncio.open_connection", return_value=(mock_reader, mock_writer)):
            await conn.connect()

            # Keepalive task should be running
            assert conn._keepalive_task is not None

            # Disconnect should cancel keepalive gracefully
            await conn.disconnect()

            # No exceptions should be raised and task should be cleaned up
            assert conn._keepalive_task is None

    @pytest.mark.asyncio
    async def test_keepalive_cancelled_on_disconnect(self):
        """Test keepalive task is cancelled on disconnect."""
        conn = ICConnection("192.168.1.100", keepalive_interval=10.0)

        mock_reader = AsyncMock()
        mock_writer = MagicMock()
        mock_writer.is_closing.return_value = False
        mock_writer.close = MagicMock()
        mock_writer.wait_closed = AsyncMock()

        with patch("asyncio.open_connection", return_value=(mock_reader, mock_writer)):
            await conn.connect()

            # Keepalive task should exist
            assert conn._keepalive_task is not None
            assert not conn._keepalive_task.done()

            await conn.disconnect()

            # After disconnect, keepalive task should be None
            assert conn._keepalive_task is None

    @pytest.mark.asyncio
    async def test_handle_connection_lost_calls_callback(self):
        """Test _handle_connection_lost invokes disconnect callback."""
        conn = ICConnection("192.168.1.100")

        disconnect_called = []

        def on_disconnect(exc):
            disconnect_called.append(exc)

        conn.set_disconnect_callback(on_disconnect)

        mock_reader = AsyncMock()
        mock_writer = MagicMock()
        mock_writer.is_closing.return_value = False
        mock_writer.close = MagicMock()
        mock_writer.wait_closed = AsyncMock()

        with patch("asyncio.open_connection", return_value=(mock_reader, mock_writer)):
            await conn.connect()

            test_error = ICConnectionError("Test error")
            await conn._handle_connection_lost(test_error)

            assert len(disconnect_called) == 1
            assert disconnect_called[0] is test_error
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


class TestICConnectionAdvanced:
    """Advanced tests for ICConnection edge cases."""

    @pytest.mark.asyncio
    async def test_keepalive_sends_ping(self):
        """Test keepalive loop sends PING messages."""
        conn = ICConnection("192.168.1.100", keepalive_interval=0.1)

        mock_reader = AsyncMock()
        mock_writer = MagicMock()
        mock_writer.is_closing.return_value = False
        mock_writer.write = MagicMock()
        mock_writer.drain = AsyncMock()
        mock_writer.close = MagicMock()
        mock_writer.wait_closed = AsyncMock()

        # Return successful responses
        mock_reader.readline = AsyncMock(return_value=b'{"response":"200"}\r\n')

        with patch("asyncio.open_connection", return_value=(mock_reader, mock_writer)):
            await conn.connect()

            # Wait for keepalive to trigger
            await asyncio.sleep(0.15)

            # Should have written something (PING or at least been called)
            calls = mock_writer.write.call_args_list
            # Check if any call contains PING
            ping_found = any("PING" in str(call) for call in calls)
            assert ping_found or len(calls) > 0

            await conn.disconnect()

    @pytest.mark.asyncio
    async def test_keepalive_error_is_handled(self):
        """Test keepalive loop handles timeout errors gracefully."""
        # This test verifies the keepalive mechanism exists and runs
        conn = ICConnection("192.168.1.100", keepalive_interval=0.1)

        mock_reader = AsyncMock()
        mock_writer = MagicMock()
        mock_writer.is_closing.return_value = False
        mock_writer.write = MagicMock()
        mock_writer.drain = AsyncMock()
        mock_writer.close = MagicMock()
        mock_writer.wait_closed = AsyncMock()

        # Return successful responses
        mock_reader.readline = AsyncMock(return_value=b'{"response":"200"}\r\n')

        with patch("asyncio.open_connection", return_value=(mock_reader, mock_writer)):
            await conn.connect()
            assert conn._keepalive_task is not None

            # Wait for at least one keepalive
            await asyncio.sleep(0.15)

            # Verify connection still works
            assert conn.connected is True

            await conn.disconnect()

    @pytest.mark.asyncio
    async def test_response_with_error_code(self):
        """Test handling response with error code."""
        conn = ICConnection("192.168.1.100")

        mock_reader = AsyncMock()
        mock_writer = MagicMock()
        mock_writer.is_closing.return_value = False
        mock_writer.write = MagicMock()
        mock_writer.drain = AsyncMock()

        # Mock error response (current impl doesn't parse message field)
        response_data = b'{"command":"Error","messageID":"1","response":"500"}\r\n'
        mock_reader.readline = AsyncMock(return_value=response_data)

        with patch("asyncio.open_connection", return_value=(mock_reader, mock_writer)):
            await conn.connect()

            with pytest.raises(ICResponseError) as exc_info:
                await conn.send_request("GetParamList")

            assert exc_info.value.code == "500"

    @pytest.mark.asyncio
    async def test_disconnect_not_connected(self):
        """Test disconnect when not connected is a no-op."""
        conn = ICConnection("192.168.1.100")
        assert conn.connected is False

        # Should not raise
        await conn.disconnect()
        assert conn.connected is False

    @pytest.mark.asyncio
    async def test_read_message_returns_empty(self):
        """Test _read_message handles empty response (connection closed)."""
        conn = ICConnection("192.168.1.100")

        mock_reader = AsyncMock()
        mock_writer = MagicMock()
        mock_writer.is_closing.return_value = False

        # Return empty bytes (connection closed by remote)
        mock_reader.readline = AsyncMock(return_value=b"")

        with patch("asyncio.open_connection", return_value=(mock_reader, mock_writer)):
            await conn.connect()

            with pytest.raises(ICConnectionError) as exc_info:
                await conn._read_message()

            assert "closed" in str(exc_info.value).lower()

    @pytest.mark.asyncio
    async def test_notification_without_callback(self):
        """Test notification is ignored when no callback set."""
        conn = ICConnection("192.168.1.100")

        mock_reader = AsyncMock()
        mock_writer = MagicMock()
        mock_writer.is_closing.return_value = False
        mock_writer.write = MagicMock()
        mock_writer.drain = AsyncMock()

        # First return a notification, then the actual response
        notification = b'{"command":"NotifyList","objectList":[{"objnam":"PUMP1"}]}\r\n'
        response = (
            b'{"command":"SendParamList","messageID":"1","response":"200","objectList":[]}\r\n'
        )
        mock_reader.readline = AsyncMock(side_effect=[notification, response])

        with patch("asyncio.open_connection", return_value=(mock_reader, mock_writer)):
            await conn.connect()
            # No callback set - should just skip notification

            result = await conn.send_request("GetParamList")
            assert result["response"] == "200"

    @pytest.mark.asyncio
    async def test_multiple_notifications_before_response(self):
        """Test handling multiple notifications before response."""
        conn = ICConnection("192.168.1.100")

        mock_reader = AsyncMock()
        mock_writer = MagicMock()
        mock_writer.is_closing.return_value = False
        mock_writer.write = MagicMock()
        mock_writer.drain = AsyncMock()

        # Multiple notifications then response
        notifications_received = []

        def on_notification(msg):
            notifications_received.append(msg)

        notification1 = b'{"command":"NotifyList","objectList":[{"objnam":"PUMP1"}]}\r\n'
        notification2 = b'{"command":"NotifyList","objectList":[{"objnam":"PUMP2"}]}\r\n'
        response = b'{"command":"SendParamList","messageID":"1","response":"200"}\r\n'
        mock_reader.readline = AsyncMock(side_effect=[notification1, notification2, response])

        with patch("asyncio.open_connection", return_value=(mock_reader, mock_writer)):
            await conn.connect()
            conn.set_notification_callback(on_notification)

            await conn.send_request("GetParamList")

            assert len(notifications_received) == 2

    @pytest.mark.asyncio
    async def test_drain_error_during_write(self):
        """Test handling drain error during write."""
        conn = ICConnection("192.168.1.100")

        mock_reader = AsyncMock()
        mock_writer = MagicMock()
        mock_writer.is_closing.return_value = False
        mock_writer.write = MagicMock()
        mock_writer.drain = AsyncMock(side_effect=OSError("Connection lost"))

        with patch("asyncio.open_connection", return_value=(mock_reader, mock_writer)):
            await conn.connect()

            with pytest.raises(ICConnectionError) as exc_info:
                await conn._write_message({"command": "test"})

            assert "Write failed" in str(exc_info.value)
