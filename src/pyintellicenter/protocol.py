"""Protocol for communicating with a Pentair system.

This module implements the low-level TCP protocol for communicating with
Pentair IntelliCenter pool control systems. It handles:
- JSON message framing over TCP (messages terminated with \\r\\n)
- Flow control to prevent overwhelming the IntelliCenter (one request at a time)
- Connection health monitoring via keepalive queries
- Automatic detection and recovery from flow control deadlocks
"""

import asyncio
import logging
from typing import TYPE_CHECKING, Any, cast

import orjson

if TYPE_CHECKING:
    from .controller import BaseController

# Maximum number of requests that can be queued to prevent memory exhaustion
MAX_QUEUE_SIZE = 100

# Maximum size of the message buffer in bytes (1MB)
# Prevents DoS via malformed messages without delimiters
MAX_BUFFER_SIZE = 1_000_000

_LOGGER = logging.getLogger(__name__)
# _LOGGER.setLevel(logging.DEBUG)

# ---------------------------------------------------------------------------

# Connection monitoring configuration constants
# NOTE: IntelliCenter does NOT support ping/pong protocol
# It sends NotifyList push updates when equipment state changes
# We send periodic keepalive queries to maintain connection health
HEARTBEAT_INTERVAL = 30  # Check connection health every 30 seconds
FLOW_CONTROL_TIMEOUT = 45  # Reset flow control if stuck for 45 seconds
KEEPALIVE_INTERVAL = 90  # Send keepalive query every 90 seconds
CONNECTION_IDLE_TIMEOUT = (
    300  # Close connection if no data received for 5 minutes (should never happen with keepalives)
)
MAX_MISSED_KEEPALIVES = 3  # Close connection after this many missed keepalive responses


class ICProtocol(asyncio.Protocol):
    """The ICProtocol handles the low level protocol with a Pentair system.

    In particular, it takes care of the following:
    - generating unique msg ids for outgoing requests
    - receiving data from the transport and combining it into a proper json object
    - managing a 'only-one-request-out-one-the-wire' policy
      (IntelliCenter struggles with concurrent requests)
    - monitoring connection health via idle timeout (IntelliCenter does NOT support ping/pong)
    - detecting flow control deadlocks and automatically recovering
    - relying on IntelliCenter's NotifyList push updates to detect active connections
    """

    def __init__(self, controller: "BaseController", keepalive_interval: int | None = None) -> None:
        """Initialize a protocol for a IntelliCenter system.

        Args:
            controller: The controller instance that manages this protocol.
                       The controller receives callbacks for connection events
                       and message processing.
            keepalive_interval: Optional override for keepalive query interval in seconds.
                              Defaults to KEEPALIVE_INTERVAL if not specified.
        """

        self._controller: BaseController = controller
        self._keepalive_interval = keepalive_interval or KEEPALIVE_INTERVAL

        self._transport: asyncio.Transport | None = None

        # counter used to generate messageIDs
        # IntelliCenter expects each request to have a unique incrementing ID
        self._msgID: int = 1

        # buffer used to accumulate data received before splitting into lines
        # Messages from IntelliCenter are JSON terminated with \r\n
        # We may receive partial messages, so we buffer until complete
        self._lineBuffer: str = ""

        # Flow control state: ensures only one request is on the wire at a time
        # IntelliCenter struggles to parse concurrent requests, so we queue them
        # _out_pending: count of requests sent but not yet responded to
        # _out_queue: asyncio queue of requests waiting to be sent (bounded to prevent memory exhaustion)
        # _flow_control_lock: ensures atomic flow control operations
        self._out_pending: int = 0
        self._out_queue: asyncio.Queue[str] = asyncio.Queue(maxsize=MAX_QUEUE_SIZE)
        self._last_flow_control_activity: float | None = None
        self._flow_control_lock = asyncio.Lock()

        # Track last data received time for connection health monitoring
        # Used to detect idle connections and trigger reconnection
        self._last_data_received: float | None = None

        # Track last keepalive sent time
        # We send periodic queries to keep the connection alive
        self._last_keepalive_sent: float | None = None

        # Track keepalive message ID for response validation
        # Ensures we receive responses to our keepalive queries
        self._pending_keepalive_id: str | None = None
        self._keepalive_response_pending: bool = False
        self._missed_keepalive_responses: int = 0

        # heartbeat task for monitoring connection health
        # Runs periodically to send keepalives and detect deadlocks
        self._heartbeat_task: asyncio.Task[None] | None = None

    def connection_made(self, transport: asyncio.BaseTransport) -> None:
        """Handle the callback for a successful connection.

        Called by asyncio when the TCP connection is established.
        Initializes protocol state and notifies the controller.

        Args:
            transport: The transport instance for this connection.
        """

        # Cast BaseTransport to Transport - we know it's a TCP transport
        # since we're using create_connection() with TCP protocol
        self._transport = cast("asyncio.Transport", transport)
        self._msgID = 1
        current_time = asyncio.get_event_loop().time()
        self._last_flow_control_activity = current_time
        self._last_data_received = current_time
        self._last_keepalive_sent = current_time

        # Start the heartbeat monitoring task
        self._heartbeat_task = asyncio.create_task(self._heartbeat_loop())

        # and notify our controller that we are ready!
        self._controller.connection_made(self, self._transport)

    def connection_lost(self, exc: Exception | None) -> None:
        """Handle the callback for connection lost.

        Called by asyncio when the TCP connection is lost (either
        intentionally or due to error). Cleans up resources and
        notifies the controller.

        Args:
            exc: The exception that caused the connection loss, or None
                if the connection was closed normally.
        """

        # Cancel the heartbeat task and schedule proper cleanup
        if self._heartbeat_task and not self._heartbeat_task.done():
            self._heartbeat_task.cancel()
            # Schedule task cleanup to properly await cancellation
            asyncio.create_task(self._cleanup_heartbeat_task(self._heartbeat_task))
            self._heartbeat_task = None

        self._controller.connection_lost(exc)

    async def _cleanup_heartbeat_task(self, task: asyncio.Task[None]) -> None:
        """Clean up a cancelled heartbeat task.

        Args:
            task: The cancelled task to clean up.
        """
        try:
            await task
        except asyncio.CancelledError:
            _LOGGER.debug("PROTOCOL: heartbeat task cleanup completed")
        except Exception as err:  # noqa: BLE001 - Cleanup must not crash
            _LOGGER.debug(f"PROTOCOL: heartbeat task cleanup error: {err}")

    def data_received(self, data: bytes) -> None:
        """Handle the callback for data received.

        Called by asyncio when data is received from the TCP connection.
        Buffers incoming data until complete lines (messages) are received,
        then processes each message individually.

        The IntelliCenter sends JSON messages terminated with \\r\\n.
        We may receive partial messages or multiple messages in one chunk,
        so we buffer and split appropriately.

        Args:
            data: Raw bytes received from the connection.
        """

        # Update last data received timestamp for connection health monitoring
        self._last_data_received = asyncio.get_event_loop().time()

        try:
            decoded_data = data.decode("utf-8")
        except UnicodeDecodeError as err:
            _LOGGER.error(f"PROTOCOL: failed to decode data as UTF-8: {err}")
            # Close connection to trigger reconnection with clean state
            if self._transport:
                self._transport.close()
            return

        _LOGGER.debug(f"PROTOCOL: received from transport: {decoded_data}")

        # "packets" from Pentair are organized by lines (terminated with \r\n)
        # so wait until at least a full line is received
        self._lineBuffer += decoded_data

        # Check buffer size limit to prevent DoS via large malformed messages
        if len(self._lineBuffer) > MAX_BUFFER_SIZE:
            _LOGGER.error(
                f"PROTOCOL: message buffer exceeded maximum size "
                f"({len(self._lineBuffer)} > {MAX_BUFFER_SIZE}) - closing connection"
            )
            if self._transport:
                self._transport.close()
            self._lineBuffer = ""
            return

        # If we don't have a complete message yet, wait for more data
        if not self._lineBuffer.endswith("\r\n"):
            return

        # Split buffer into individual messages (there might be multiple)
        # The split will create an empty string at the end due to trailing \r\n
        lines = str.split(self._lineBuffer, "\r\n")
        self._lineBuffer = ""

        # Process each complete message
        for line in lines:
            if line:  # Skip empty strings from split
                self.processMessage(line)

    def sendCmd(self, cmd: str, extra: dict[str, Any] | None = None) -> str:
        """Send a command and return a generated message ID.

        Constructs a JSON command message with a unique message ID and
        sends it to the IntelliCenter. The message ID can be used to
        correlate responses.

        Args:
            cmd: The command name (e.g., "GetParamList", "SetParamList").
            extra: Optional dictionary of additional parameters to include
                  in the command message.

        Returns:
            The message ID assigned to this command (as a string).
        """
        msg_id = str(self._msgID)
        message_dict: dict[str, Any] = {"messageID": msg_id, "command": cmd}
        if extra:
            message_dict.update(extra)
        self._msgID = self._msgID + 1
        # orjson.dumps returns bytes, decode to string for protocol
        packet = orjson.dumps(message_dict).decode("utf-8")
        self.sendRequest(packet)

        return str(msg_id)

    def _writeToTransport(self, request: str) -> None:
        """Write a request to the transport.

        Internal method that handles the actual transmission of data
        over the TCP connection.

        Args:
            request: The request string to send (will be encoded to bytes).
        """
        _LOGGER.debug(f"PROTOCOL: writing to transport: (size {len(request)}): {request}")
        if self._transport:
            self._transport.write(request.encode())

    def sendRequest(self, request: str) -> None:
        """Send a request, enforcing flow control.

        The IntelliCenter struggles to parse concurrent requests, so this
        method implements a "one request on the wire at a time" policy.
        If a request is already pending, new requests are queued and sent
        when the previous response is received.

        Flow control prevents overwhelming the IntelliCenter and ensures
        reliable message delivery.

        Note: Flow control is implemented atomically by incrementing
        _out_pending BEFORE writing to transport. This ensures that even
        if called from multiple coroutines, only one request is on the
        wire at a time.

        Args:
            request: The JSON request string to send.
        """

        # IntelliCenter seems to struggle to parse requests coming too fast
        # so we throttle back to one request on the wire at a time
        # see responseReceived() for the other side of the flow control

        # CRITICAL: Increment _out_pending BEFORE checking/writing to prevent
        # race conditions where multiple coroutines could check _out_pending == 0
        # simultaneously and both write to the transport.
        self._out_pending += 1
        self._last_flow_control_activity = asyncio.get_event_loop().time()

        if self._out_pending == 1:
            # Nothing else was in progress, we can transmit immediately
            self._writeToTransport(request)
        else:
            # There is already something on the wire, queue the request
            # It will be sent when we receive the next response
            try:
                self._out_queue.put_nowait(request)
            except asyncio.QueueFull:
                # Undo the increment since we're not actually queuing
                self._out_pending -= 1
                _LOGGER.warning(
                    f"PROTOCOL: request queue full ({MAX_QUEUE_SIZE} pending) - "
                    "dropping request to prevent memory exhaustion"
                )

    def responseReceived(self) -> None:
        """Handle flow control when a response is received.

        This method is called when we receive a response from the IntelliCenter.
        It implements the "other side" of the flow control mechanism by:
        1. Sending the next queued request (if any)
        2. Decrementing the pending request counter

        This ensures only one request is on the wire at a time.
        """

        # We know that a response has been received, so if we have a
        # pending request in the queue, we can write it to our transport
        if not self._out_queue.empty():
            request = self._out_queue.get_nowait()
            self._writeToTransport(request)

        # No matter what, we have now one less request pending
        if self._out_pending:
            self._out_pending -= 1

        # Track flow control activity for deadlock detection
        self._last_flow_control_activity = asyncio.get_event_loop().time()

    def processMessage(self, message: str) -> None:
        """Process a given message from IntelliCenter.

        Parses the JSON message and extracts the message ID, command, and
        response code. Handles both responses (to our requests) and
        notifications (unsolicited messages from IntelliCenter).

        Messages are expected to be JSON objects with at minimum:
        - messageID: A string identifier
        - command: The command name
        - response: (optional) Response code, present only for responses
                   "200" indicates success, other values are error codes

        NOTE: There's a bug in IntelliCenter where the message_id in error
        responses may not match the request message_id, so we don't rely
        on strict correlation.

        Args:
            message: A complete JSON message string from IntelliCenter.
        """

        _LOGGER.debug(f"PROTOCOL: processMessage {message}")

        # Various errors can occur when parsing/processing messages
        # We handle them gracefully to avoid disrupting the protocol

        try:
            # Parse the JSON message (orjson is 2-3x faster than stdlib json)
            msg: dict[str, Any] = orjson.loads(message)

            # Extract required fields: messageID and command
            # NOTE: there seems to be a bug in IntelliCenter where
            # the message_id is different from the one matching the request
            # if an error occurred.. therefore the message_id is not really used
            msg_id: str = msg["messageID"]
            command: str = msg["command"]
            response: str | None = msg.get("response")

            # The response field is only present when the message is a response
            # to a request (as opposed to a 'notification' like NotifyList).
            # If it's a response, handle flow control
            if response:
                self.responseReceived()

            # Check if this is a keepalive response
            if (
                self._pending_keepalive_id
                and msg_id == self._pending_keepalive_id
                and response == "200"
            ):
                _LOGGER.debug("PROTOCOL: keepalive response received")
                self._keepalive_response_pending = False
                self._missed_keepalive_responses = 0
                self._pending_keepalive_id = None

            # Pass the message to the controller for semantic processing
            # The controller will handle command-specific logic
            self._controller.receivedMessage(msg_id, command, response, msg)

        except orjson.JSONDecodeError as err:
            # Invalid JSON - log and continue (recoverable error)
            _LOGGER.error(f"PROTOCOL: invalid JSON received: {message[:100]} - {err}")
        except KeyError as err:
            # Missing required field - log and continue (recoverable error)
            _LOGGER.error(f"PROTOCOL: message missing required field {err}: {message[:100]}")
        except Exception as err:  # noqa: BLE001 - Protocol callback must not crash
            # Unexpected error - close connection to trigger reconnection
            _LOGGER.error(
                f"PROTOCOL: unexpected exception while receiving message: {err}",
                exc_info=True,
            )
            # For unexpected errors, close the connection to trigger reconnection
            if self._transport:
                _LOGGER.warning("PROTOCOL: closing connection due to unexpected error")
                self._transport.close()

    async def _heartbeat_loop(self) -> None:
        """Monitor connection health and send keepalive queries.

        IntelliCenter does not support ping/pong protocol. Instead, we:
        1. Send periodic keepalive queries to ensure data flow
        2. Monitor for flow control deadlocks
        3. Detect idle connections (no data received for extended period)
        4. Rely on IntelliCenter's NotifyList push updates for state changes

        This task runs continuously while the connection is active and
        handles three types of monitoring:

        - Keepalive: Sends lightweight queries every KEEPALIVE_INTERVAL seconds
          to maintain the connection and detect if the system is responsive.

        - Flow Control Deadlock: If requests are pending but no activity
          occurs for FLOW_CONTROL_TIMEOUT seconds, resets flow control state.
          This recovers from situations where the IntelliCenter failed to
          respond to a request.

        - Idle Timeout: If no data is received for CONNECTION_IDLE_TIMEOUT
          seconds, closes the connection. This should never happen with
          keepalives, but provides a safety net.
        """
        try:
            while True:
                await asyncio.sleep(HEARTBEAT_INTERVAL)

                if not self._transport or self._transport.is_closing():
                    _LOGGER.debug("PROTOCOL: heartbeat stopped - transport closed")
                    break

                current_time = asyncio.get_event_loop().time()

                # Check for missed keepalive responses
                if self._keepalive_response_pending:
                    self._missed_keepalive_responses += 1
                    _LOGGER.warning(
                        f"PROTOCOL: keepalive response not received "
                        f"(missed: {self._missed_keepalive_responses}/{MAX_MISSED_KEEPALIVES})"
                    )
                    if self._missed_keepalive_responses >= MAX_MISSED_KEEPALIVES:
                        _LOGGER.error(
                            f"PROTOCOL: {MAX_MISSED_KEEPALIVES} consecutive "
                            "keepalive responses missed - closing connection"
                        )
                        if self._transport:
                            self._transport.close()
                        break

                # Send keepalive query if needed
                if self._last_keepalive_sent:
                    time_since_keepalive = current_time - self._last_keepalive_sent
                    if time_since_keepalive > self._keepalive_interval:
                        _LOGGER.debug(
                            f"PROTOCOL: sending keepalive query ({time_since_keepalive:.1f}s since last)"
                        )
                        # Send a lightweight query to keep the connection alive
                        # Query the SYSTEM object's MODE attribute (always exists)
                        try:
                            keepalive_id = self.sendCmd(
                                "GetParamList",
                                {
                                    "condition": "OBJTYP=SYSTEM",
                                    "objectList": [{"objnam": "INCR", "keys": ["MODE"]}],
                                },
                            )
                            self._pending_keepalive_id = keepalive_id
                            self._keepalive_response_pending = True
                            self._last_keepalive_sent = current_time
                        except (RuntimeError, ConnectionError) as err:
                            _LOGGER.debug(f"PROTOCOL: keepalive query failed: {err}")

                # Check for flow control deadlock
                if self._last_flow_control_activity:
                    time_since_activity = current_time - self._last_flow_control_activity
                    if self._out_pending > 0 and time_since_activity > FLOW_CONTROL_TIMEOUT:
                        # Count dropped messages for logging
                        dropped_count = 0
                        while not self._out_queue.empty():
                            try:
                                self._out_queue.get_nowait()
                                dropped_count += 1
                            except asyncio.QueueEmpty:
                                break

                        _LOGGER.warning(
                            f"PROTOCOL: flow control deadlock detected "
                            f"({self._out_pending} pending, {dropped_count} queued, "
                            f"{time_since_activity:.1f}s since activity) - resetting"
                        )
                        # Reset flow control state
                        self._out_pending = 0

                # Check for connection idle timeout (no data received)
                if self._last_data_received:
                    time_since_data = current_time - self._last_data_received
                    if time_since_data > CONNECTION_IDLE_TIMEOUT:
                        _LOGGER.warning(
                            f"PROTOCOL: no data received for {time_since_data:.1f}s "
                            f"(timeout: {CONNECTION_IDLE_TIMEOUT}s) - closing connection"
                        )
                        if self._transport:
                            self._transport.close()
                        break

        except asyncio.CancelledError:
            _LOGGER.debug("PROTOCOL: heartbeat task cancelled")
        except Exception as err:  # noqa: BLE001 - Background task must not crash
            _LOGGER.error(f"PROTOCOL: heartbeat loop error: {err}", exc_info=True)
