"""Regression tests for reconnect/connection-lifecycle hardening.

Complements tests/test_dead_link_detection.py (PR #41): these cover the
handler/controller lifecycle gaps fixed alongside it - stop() racing a
delayed reconnect, connection replacement leaks, stale-connection disconnect
events, and the documented 3-consecutive-miss keepalive policy.
"""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from pyintellicenter import (
    ICBaseController,
    ICConnection,
    ICConnectionError,
    ICConnectionHandler,
    ICConnectionMetrics,
    ICTimeoutError,
)
from pyintellicenter.connection import KEEPALIVE_MAX_FAILURES


class TestStarterStopRecheck:
    """A starter waking from its delay must honour stop()."""

    @pytest.mark.asyncio
    async def test_starter_aborts_when_stopped_during_delay(self):
        """After stop(), a starter waking from its delay must not reconnect."""
        controller = MagicMock()
        controller.start = AsyncMock()
        controller.stop = AsyncMock()
        controller.host = "192.168.1.100"
        controller._metrics = ICConnectionMetrics()
        controller.set_disconnected_callback = MagicMock()

        handler = ICConnectionHandler(controller, time_between_reconnects=1)
        # Simulate the stop flag flipping while the starter slept; the loop
        # must bail out before opening a connection nothing would ever close.
        handler._stopped = True
        await handler._starter(initial_delay=0)
        controller.start.assert_not_called()


class TestConnectionReplacement:
    """ICBaseController.start() must not leak or confuse replaced connections."""

    def _mock_connection(self):
        mock_connection = AsyncMock()
        mock_connection.connected = True
        mock_connection.connect = AsyncMock()
        mock_connection.set_disconnect_callback = MagicMock()
        mock_connection.send_request = AsyncMock(
            return_value={
                "response": "200",
                "objectList": [
                    {
                        "objnam": "INCR",
                        "params": {
                            "PROPNAME": "Test Pool",
                            "VER": "1.0.0",
                            "MODE": "ENGLISH",
                            "SNAME": "TestSystem",
                        },
                    }
                ],
            }
        )
        return mock_connection

    @pytest.mark.asyncio
    async def test_start_disconnects_previous_connection(self):
        """start() must tear down the connection it replaces, not leak it."""
        controller = ICBaseController("192.168.1.100", 6681)
        old_connection = AsyncMock()
        controller._connection = old_connection

        new_connection = self._mock_connection()
        with patch(
            "pyintellicenter.controller.ICConnection",
            return_value=new_connection,
        ):
            await controller.start()

        old_connection.disconnect.assert_awaited_once()
        assert controller._connection is new_connection

    @pytest.mark.asyncio
    async def test_stale_connection_disconnect_is_ignored(self):
        """A replaced connection's late disconnect must not affect the live one."""
        controller = ICBaseController("192.168.1.100", 6681)
        events: list[str] = []
        controller.set_disconnected_callback(lambda ctrl, exc: events.append(str(exc)))

        first = self._mock_connection()
        second = self._mock_connection()
        with patch(
            "pyintellicenter.controller.ICConnection",
            side_effect=[first, second],
        ):
            await controller.start()
            stale_callback = first.set_disconnect_callback.call_args[0][0]
            await controller.start()  # replaces `first` with `second`

        # The stale socket dies late: the controller must ignore it.
        stale_callback(Exception("stale socket died"))
        assert events == []

        # The live connection's events still propagate.
        live_callback = second.set_disconnect_callback.call_args[0][0]
        live_callback(Exception("live drop"))
        assert events == ["live drop"]


class TestKeepaliveMissPolicy:
    """The link is dead after KEEPALIVE_MAX_FAILURES consecutive misses.

    A single missed response does not prove death (the panel can be busy
    servicing another client); teardown must wait for the documented number
    of consecutive misses, and a success in between resets the count.
    """

    def _connection_with_mock_protocol(self) -> ICConnection:
        conn = ICConnection("192.168.1.100", 6681)
        protocol = MagicMock()
        protocol.connected = True
        conn._protocol = protocol
        return conn

    @pytest.mark.asyncio
    async def test_teardown_after_max_consecutive_misses(self):
        conn = self._connection_with_mock_protocol()
        protocol = conn._protocol  # _abort_connection detaches it after closing
        conn.send_request = AsyncMock(side_effect=ICTimeoutError("Request GetParamList timed out"))

        with patch("asyncio.sleep", new=AsyncMock()):
            await conn._keepalive_loop()

        assert conn.send_request.await_count == KEEPALIVE_MAX_FAILURES
        protocol.close.assert_called_once()

    @pytest.mark.asyncio
    async def test_success_resets_the_miss_count(self):
        conn = self._connection_with_mock_protocol()
        protocol = conn._protocol  # _abort_connection detaches it after closing
        conn.send_request = AsyncMock(
            side_effect=[
                ICTimeoutError("timeout 1"),
                ICTimeoutError("timeout 2"),
                {"response": "200"},  # recovery resets the count
                ICTimeoutError("timeout 3"),
                ICTimeoutError("timeout 4"),
                ICTimeoutError("timeout 5"),
            ]
        )

        with patch("asyncio.sleep", new=AsyncMock()):
            await conn._keepalive_loop()

        # All six calls were made: the two early misses did not accumulate
        # with the three post-recovery misses into an early teardown.
        assert conn.send_request.await_count == 6
        protocol.close.assert_called_once()

    @pytest.mark.asyncio
    async def test_connection_error_still_immediate(self):
        """A connection error is definitive - no miss-counting applies."""
        conn = self._connection_with_mock_protocol()
        protocol = conn._protocol  # _abort_connection detaches it after closing
        conn.send_request = AsyncMock(side_effect=ICConnectionError("Not connected"))

        with patch("asyncio.sleep", new=AsyncMock()):
            await conn._keepalive_loop()

        assert conn.send_request.await_count == 1
        protocol.close.assert_called_once()
