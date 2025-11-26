"""Controller classes for Pentair Intellicenter.

This module provides three controller classes that manage communication
with the Pentair IntelliCenter system:

1. BaseController: Basic TCP connection and command handling
   - Manages connection lifecycle
   - Sends commands and correlates responses
   - Provides access to system information

2. ModelController: Extends BaseController with object model management
   - Maintains a PoolModel of equipment state
   - Tracks attribute changes via RequestParamList
   - Processes NotifyList push updates from IntelliCenter

3. ConnectionHandler: Manages reconnection logic
   - Automatic reconnection with exponential backoff
   - Debounced disconnect notifications to avoid flapping
   - Callbacks for connection state changes
"""

from __future__ import annotations

import asyncio
import logging
import time
from asyncio import AbstractEventLoop, Future, Transport
from dataclasses import dataclass, field
from hashlib import blake2b
from typing import TYPE_CHECKING, Any, ClassVar

from .attributes import (
    MODE_ATTR,
    OBJTYP_ATTR,
    PARENT_ATTR,
    PROPNAME_ATTR,
    SNAME_ATTR,
    SUBTYP_ATTR,
    SYSTEM_TYPE,
    VER_ATTR,
)
from .protocol import ICProtocol

if TYPE_CHECKING:
    from collections.abc import Callable

    from .model import PoolModel

_LOGGER = logging.getLogger(__name__)

# Connection configuration constants
CONNECTION_TIMEOUT = 30.0  # Timeout for initial connection in seconds
MAX_ATTRIBUTES_PER_QUERY = 50  # Maximum attributes to request in a single query
RESPONSE_TIMEOUT = 60.0  # Timeout for individual command responses in seconds
REQUEST_CLEANUP_INTERVAL = 60.0  # Interval for cleaning up orphaned requests


class CommandError(Exception):
    """Represents an error in response to a Pentair request.

    Raised when the IntelliCenter responds with an error code
    other than "200" (success).
    """

    def __init__(self, errorCode: str) -> None:
        """Initialize from a Pentair errorCode.

        Args:
            errorCode: The error code string from IntelliCenter
                      (e.g., "400" for bad request).
        """
        self._errorCode = errorCode
        super().__init__(f"IntelliCenter error: {errorCode}")

    @property
    def errorCode(self) -> str:
        """Return the error code."""
        return self._errorCode


@dataclass
class PendingRequest:
    """Tracks a pending request with its creation time for timeout handling.

    Attributes:
        future: The Future that will be resolved with the response
        created_at: Monotonic time when the request was created
    """

    future: Future[dict[str, Any]] | None
    created_at: float = field(default_factory=time.monotonic)


@dataclass
class ConnectionMetrics:
    """Tracks connection and request metrics for observability.

    These metrics are useful for diagnostics and understanding
    the health and performance of the IntelliCenter connection.

    Attributes:
        requests_sent: Total number of requests sent
        requests_completed: Number of requests that received responses
        requests_failed: Number of requests that resulted in errors
        requests_timed_out: Number of requests that timed out
        requests_dropped: Number of requests dropped (queue full)
        reconnect_attempts: Number of reconnection attempts
        successful_connects: Number of successful connections
        last_request_time: Monotonic time of last request
        last_response_time: Monotonic time of last response
        total_response_time: Sum of all response times (for averaging)
    """

    requests_sent: int = 0
    requests_completed: int = 0
    requests_failed: int = 0
    requests_timed_out: int = 0
    requests_dropped: int = 0
    reconnect_attempts: int = 0
    successful_connects: int = 0
    last_request_time: float = 0.0
    last_response_time: float = 0.0
    total_response_time: float = 0.0

    @property
    def average_response_time(self) -> float:
        """Calculate average response time in seconds."""
        if self.requests_completed == 0:
            return 0.0
        return self.total_response_time / self.requests_completed

    def to_dict(self) -> dict[str, Any]:
        """Return metrics as a dictionary for diagnostics."""
        return {
            "requests_sent": self.requests_sent,
            "requests_completed": self.requests_completed,
            "requests_failed": self.requests_failed,
            "requests_timed_out": self.requests_timed_out,
            "requests_dropped": self.requests_dropped,
            "reconnect_attempts": self.reconnect_attempts,
            "successful_connects": self.successful_connects,
            "average_response_time_ms": round(self.average_response_time * 1000, 2),
        }


# -------------------------------------------------------------------------------------


class SystemInfo:
    """Represents minimal information about a Pentair IntelliCenter system.

    Contains basic system metadata like software version, temperature units,
    and a unique identifier derived from the system name.
    """

    # Attributes to fetch from the SYSTEM object
    ATTRIBUTES_LIST: ClassVar[list[str]] = [
        PROPNAME_ATTR,  # Property/location name
        VER_ATTR,  # Software version
        MODE_ATTR,  # Temperature units (METRIC or ENGLISH)
        SNAME_ATTR,  # System name (used to generate unique_id)
    ]

    def __init__(self, objnam: str, params: dict[str, Any]) -> None:
        """Initialize from a dictionary of system attributes.

        Args:
            objnam: The object name (e.g., "INCR" for IntelliCenter).
            params: Dictionary of system attributes fetched from IntelliCenter.
        """
        self._objnam: str = objnam
        self._propName: str = params[PROPNAME_ATTR]
        self._sw_version: str = params[VER_ATTR]
        self._mode: str = params[MODE_ATTR]

        # Generate a unique ID by hashing the system name
        # This ensures a stable identifier even if IP/hostname changes
        h = blake2b(digest_size=8)
        h.update(params[SNAME_ATTR].encode())
        self._unique_id: str = h.hexdigest()

    @property
    def propName(self) -> str:
        """Return the name of the 'property' where the system is located."""
        return self._propName

    @property
    def swVersion(self) -> str:
        """Return the software version of the IntelliCenter system."""
        return self._sw_version

    @property
    def usesMetric(self) -> bool:
        """Return True if the system uses metric units for temperature."""
        return self._mode == "METRIC"

    @property
    def uniqueID(self) -> str:
        """Return a unique identifier for this system.

        Generated by hashing the system name, ensuring stability
        across network changes.
        """
        return self._unique_id

    @property
    def objnam(self) -> str:
        """Return the object name for this system."""
        return self._objnam

    def update(self, updates: dict[str, Any]) -> None:
        """Update the system info from a set of key/value pairs.

        Used when attribute changes are received via NotifyList.

        Args:
            updates: Dictionary of attribute updates.
        """
        _LOGGER.debug(f"updating system info with {updates}")
        self._propName = updates.get(PROPNAME_ATTR, self._propName)
        self._sw_version = updates.get(VER_ATTR, self._sw_version)
        self._mode = updates.get(MODE_ATTR, self._mode)


# -------------------------------------------------------------------------------------


def prune(obj: Any) -> Any:
    """Cleanup a full object tree from undefined parameters.

    Pentair returns undefined parameters as key==value pairs.
    This function recursively removes such entries from dictionaries.

    Args:
        obj: The object to prune (dict, list, or primitive value)

    Returns:
        The pruned object with undefined parameters removed
    """
    # undefined meaning key == value which is what Pentair returns
    if isinstance(obj, list):
        return [prune(item) for item in obj]
    elif isinstance(obj, dict):
        result = {}
        for key, value in obj.items():
            if key != value:
                result[key] = prune(value)
        return result
    return obj


class BaseController:
    """A basic controller connecting to a Pentair system.

    This controller manages the TCP connection to the IntelliCenter and handles
    request/response correlation. It provides basic command sending capabilities
    and retrieves system information.
    """

    def __init__(
        self,
        host: str,
        port: int = 6681,
        loop: AbstractEventLoop | None = None,
        keepalive_interval: int | None = None,
    ) -> None:
        """Initialize the controller.

        Args:
            host: IP address or hostname of the IntelliCenter
            port: TCP port for connection (default: 6681)
            loop: Event loop to use (default: current event loop)
            keepalive_interval: Optional override for keepalive query interval in seconds.
                              Defaults to protocol's KEEPALIVE_INTERVAL if not specified.
        """
        self._host = host
        self._port = port
        self._keepalive_interval = keepalive_interval
        # Use provided loop, running loop, or create new one
        if loop is not None:
            self._loop = loop
        else:
            try:
                self._loop = asyncio.get_running_loop()
            except RuntimeError:
                self._loop = asyncio.get_event_loop()

        self._transport: Transport | None = None
        self._protocol: ICProtocol | None = None
        self._systemInfo: SystemInfo | None = None

        self._disconnected_callback: Callable[[BaseController, Exception | None], None] | None = (
            None
        )

        # Track pending requests with creation time for timeout handling
        self._requests: dict[str, PendingRequest] = {}
        # Task for cleaning up orphaned/timed-out requests
        self._cleanup_task: asyncio.Task[None] | None = None
        # Metrics for observability
        self._metrics = ConnectionMetrics()

    @property
    def host(self) -> str:
        """Return the host the controller is connected to."""
        return self._host

    @property
    def metrics(self) -> ConnectionMetrics:
        """Return connection metrics for observability."""
        return self._metrics

    def connection_made(self, protocol: ICProtocol, transport: Transport) -> None:
        """Handle the callback from the protocol when connection is established.

        Args:
            protocol: The protocol instance for this connection
            transport: The transport instance for this connection
        """
        _LOGGER.debug(f"Connection established to {self._host}")
        self._metrics.successful_connects += 1

    def connection_lost(self, exc: Exception | None) -> None:
        """Handle the callback from the protocol when connection is lost.

        Args:
            exc: The exception that caused the disconnection, or None if clean
        """
        self.stop()
        if self._disconnected_callback:
            self._disconnected_callback(self, exc)

    async def start(self) -> None:
        """Connect to the Pentair system and retrieve system information.

        This method establishes a TCP connection to the IntelliCenter and
        fetches basic system information to validate the connection.

        Raises:
            asyncio.TimeoutError: If connection times out
            ConnectionRefusedError: If connection is refused
            RuntimeError: If internal state is inconsistent
            Exception: For other connection failures
        """
        # Create connection with timeout to prevent indefinite hangs
        self._transport, self._protocol = await asyncio.wait_for(
            self._loop.create_connection(
                lambda: ICProtocol(self, self._keepalive_interval),
                self._host,
                self._port,
            ),
            timeout=CONNECTION_TIMEOUT,
        )

        # Start the cleanup task for orphaned requests
        self._cleanup_task = asyncio.create_task(self._cleanup_stale_requests())

        # Request a few attributes from the SYSTEM object to validate
        # that the connected system is indeed an IntelliCenter
        future = self.sendCmd(
            "GetParamList",
            {
                "condition": f"{OBJTYP_ATTR}={SYSTEM_TYPE}",
                "objectList": [
                    {
                        "objnam": "INCR",
                        "keys": SystemInfo.ATTRIBUTES_LIST,
                    }
                ],
            },
        )
        if future is None:
            raise RuntimeError("sendCmd returned None when waitForResponse=True - internal error")
        msg = await future

        info = msg["objectList"][0]
        self._systemInfo = SystemInfo(info["objnam"], info["params"])

    def stop(self) -> None:
        """Stop all activities from this controller and disconnect."""
        # Cancel the cleanup task
        if self._cleanup_task and not self._cleanup_task.done():
            self._cleanup_task.cancel()
            self._cleanup_task = None

        if self._transport:
            # Cancel all pending request futures
            for pending in self._requests.values():
                if pending.future is not None and not pending.future.done():
                    pending.future.cancel()
            self._requests.clear()
            self._transport.close()
            self._transport = None
            self._protocol = None

    async def _cleanup_stale_requests(self) -> None:
        """Periodically clean up orphaned/timed-out requests.

        This coroutine runs in the background and removes requests that
        have been pending for longer than RESPONSE_TIMEOUT. This prevents
        memory leaks from requests that never receive responses.
        """
        try:
            while True:
                await asyncio.sleep(REQUEST_CLEANUP_INTERVAL)

                current_time = time.monotonic()
                stale_ids: list[str] = []

                for msg_id, pending in self._requests.items():
                    age = current_time - pending.created_at
                    if age > RESPONSE_TIMEOUT:
                        stale_ids.append(msg_id)
                        if pending.future and not pending.future.done():
                            pending.future.set_exception(
                                TimeoutError(f"Request {msg_id} timed out after {age:.1f}s")
                            )

                # Remove stale requests
                for msg_id in stale_ids:
                    del self._requests[msg_id]

                if stale_ids:
                    _LOGGER.warning(
                        f"CONTROLLER: cleaned up {len(stale_ids)} stale request(s): {stale_ids}"
                    )

        except asyncio.CancelledError:
            _LOGGER.debug("CONTROLLER: request cleanup task cancelled")
        except Exception as err:  # noqa: BLE001 - Background task must not crash
            _LOGGER.error(f"CONTROLLER: request cleanup error: {err}", exc_info=True)

    def sendCmd(
        self,
        cmd: str,
        extra: dict[str, Any] | None = None,
        waitForResponse: bool = True,
    ) -> Future[dict[str, Any]] | None:
        """Send a command with optional extra parameters to the system.

        Args:
            cmd: The command name to send (e.g., "GetParamList", "SetParamList")
            extra: Optional dictionary of additional parameters
            waitForResponse: If True, returns a Future for the response

        Returns:
            A Future that resolves to the response dict, or None if
            waitForResponse is False

        Example:
            resp = await controller.sendCmd("GetParamList", {...})
            or
            controller.sendCmd("SetParamList", {...}, waitForResponse=False)
        """
        _LOGGER.debug(f"CONTROLLER: sendCmd: {cmd} {extra} {waitForResponse}")
        future: Future[dict[str, Any]] | None = Future() if waitForResponse else None

        if self._protocol:
            msg_id = self._protocol.sendCmd(cmd, extra)
            # Track request with creation time for timeout handling
            self._requests[msg_id] = PendingRequest(future=future)
            # Update metrics
            self._metrics.requests_sent += 1
            self._metrics.last_request_time = time.monotonic()
        elif future:
            future.set_exception(Exception("controller disconnected"))

        return future

    def requestChanges(
        self,
        objnam: str,
        changes: dict[str, Any],
        waitForResponse: bool = True,
    ) -> Future[dict[str, Any]] | None:
        """Submit a change for a given object.

        Args:
            objnam: The object name to modify
            changes: Dictionary of attribute changes to apply
            waitForResponse: If True, returns a Future for the response

        Returns:
            A Future that resolves to the response, or None if waitForResponse is False
        """
        return self.sendCmd(
            "SETPARAMLIST",
            {"objectList": [{"objnam": objnam, "params": changes}]},
            waitForResponse=waitForResponse,
        )

    async def getAllObjects(self, attributeList: list[str]) -> list[dict[str, Any]]:
        """Return the values of given attributes for all objects in the system.

        Args:
            attributeList: List of attribute names to fetch

        Returns:
            List of object dictionaries with their attribute values
        """
        future = self.sendCmd(
            "GetParamList",
            {
                "condition": "",
                "objectList": [{"objnam": "INCR", "keys": attributeList}],
            },
        )
        if future is None:
            raise RuntimeError("sendCmd returned None when waitForResponse=True - internal error")
        result = await future

        # Since we might have asked for more attributes than any given object
        # might define, we prune the resulting tree from these 'undefined' values
        object_list: list[dict[str, Any]] = prune(result["objectList"])
        return object_list

    async def getQuery(self, queryName: str, arguments: str = "") -> list[dict[str, Any]]:
        """Return the result of a Query.

        Args:
            queryName: Name of the query to execute
            arguments: Optional arguments string

        Returns:
            The query answer as a list of dictionaries
        """
        future = self.sendCmd("GetQuery", {"queryName": queryName, "arguments": arguments})
        if future is None:
            raise RuntimeError("sendCmd returned None when waitForResponse=True - internal error")
        result = await future
        answer: list[dict[str, Any]] = result["answer"]
        return answer

    async def getCircuitNames(self) -> list[dict[str, Any]]:
        """Return the list of circuit names."""
        return await self.getQuery("GetCircuitNames")

    async def getCircuitTypes(self) -> dict[str, str]:
        """Return a dictionary: key: circuit's SUBTYP, value: 'friendly' readable string."""
        return {
            v["systemValue"]: v["readableValue"] for v in await self.getQuery("GetCircuitTypes")
        }

    async def getHardwareDefinition(self) -> list[dict[str, Any]]:
        """Return the full hardware definition of the system."""
        result: list[dict[str, Any]] = prune(await self.getQuery("GetHardwareDefinition"))
        return result

    async def getConfiguration(self) -> list[dict[str, Any]]:
        """Return the current 'configuration' of the system."""
        return await self.getQuery("GetConfiguration")

    def receivedMessage(
        self,
        msg_id: str,
        command: str,
        response: str | None,
        msg: dict[str, Any],
    ) -> None:
        """Handle the callback for an incoming message.

        Args:
            msg_id: The id of the incoming message
            command: The command name from the message
            response: The success (200) or error code, or None for notifications
            msg: The full message as a dictionary (parsed JSON object)
        """
        pending = self._requests.pop(msg_id, None)

        # Extract the future from the pending request
        # pending can be None if there was no corresponding request (e.g., notification)
        future = pending.future if pending else None

        _LOGGER.debug(f"CONTROLLER: receivedMessage: {msg_id} {command} {response} {future}")

        # Track response metrics
        current_time = time.monotonic()
        if pending is not None:
            response_time = current_time - pending.created_at
            self._metrics.total_response_time += response_time
            self._metrics.last_response_time = current_time

        if future is not None and not future.done():
            if response == "200":
                future.set_result(msg)
                self._metrics.requests_completed += 1
            else:
                future.set_exception(CommandError(response or "unknown"))
                self._metrics.requests_failed += 1
        elif response is None or response == "200":
            self.processMessage(command, msg)
        else:
            _LOGGER.warning(f"CONTROLLER: error {response} : {msg}")

    def processMessage(self, command: str, msg: dict[str, Any]) -> None:
        """Process a notification message.

        Override this method in subclasses to handle specific commands.

        Args:
            command: The command name from the notification
            msg: The full message dictionary
        """
        pass

    @property
    def systemInfo(self) -> SystemInfo | None:
        """Return the (cached) system information."""
        return self._systemInfo


# -------------------------------------------------------------------------------------


class ModelController(BaseController):
    """A controller creating and updating a PoolModel.

    This controller extends BaseController with object model management.
    It maintains a PoolModel of equipment state, tracks attribute changes
    via RequestParamList, and processes NotifyList push updates.
    """

    def __init__(
        self,
        host: str,
        model: PoolModel,
        port: int = 6681,
        loop: AbstractEventLoop | None = None,
        keepalive_interval: int | None = None,
    ) -> None:
        """Initialize the controller.

        Args:
            host: IP address or hostname of the IntelliCenter
            model: The PoolModel to populate and update
            port: TCP port for connection (default: 6681)
            loop: Event loop to use (default: current event loop)
            keepalive_interval: Optional override for keepalive query interval in seconds.
                              Defaults to protocol's KEEPALIVE_INTERVAL if not specified.
        """
        super().__init__(host, port, loop, keepalive_interval)
        self._model: PoolModel = model

        self._updatedCallback: (
            Callable[[ModelController, dict[str, dict[str, Any]]], None] | None
        ) = None

    @property
    def model(self) -> PoolModel:
        """Return the model this controller manages."""
        return self._model

    async def start(self) -> None:
        """Start the controller, fetch and start monitoring the model.

        This method:
        1. Establishes connection via parent class
        2. Fetches all objects and populates the model
        3. Requests monitoring of relevant attributes

        Raises:
            Exception: If connection or model initialization fails
        """
        await super().start()

        # Retrieve all objects with their type, subtype, sname and parent
        allObjects = await self.getAllObjects([OBJTYP_ATTR, SUBTYP_ATTR, SNAME_ATTR, PARENT_ATTR])
        # Process that list into our model
        self.model.addObjects(allObjects)

        _LOGGER.info(f"model now contains {self.model.numObjects} objects")

        try:
            # Build a query to monitor all relevant attributes
            attributes = self._model.attributesToTrack()

            query: list[dict[str, Any]] = []
            numAttributes = 0
            for items in attributes:
                query.append(items)
                numAttributes += len(items["keys"])
                # A query too large can choke the protocol...
                # Split into batches of MAX_ATTRIBUTES_PER_QUERY attributes
                if numAttributes >= MAX_ATTRIBUTES_PER_QUERY:
                    batch_future = self.sendCmd("RequestParamList", {"objectList": query})
                    if batch_future is None:
                        raise RuntimeError("sendCmd returned None when waitForResponse=True")
                    res = await batch_future
                    self._applyUpdates(res["objectList"])
                    query = []
                    numAttributes = 0
            # Issue the remaining elements if any
            if query:
                future = self.sendCmd("RequestParamList", {"objectList": query})
                if future is None:
                    raise RuntimeError("sendCmd returned None when waitForResponse=True")
                res = await future
                self._applyUpdates(res["objectList"])

        except (TimeoutError, CommandError, ConnectionError) as err:
            _LOGGER.exception(f"Error during model initialization: {err}")
            raise
        except KeyError as err:
            _LOGGER.exception(f"Model initialization failed - missing key: {err}")
            raise RuntimeError(f"Invalid response format: missing {err}") from err

    def receivedQueryResult(self, queryName: str, answer: list[dict[str, Any]]) -> None:
        """Handle the result of all 'getQuery' responses.

        Override this method to handle specific query results.
        See Pentair protocol documentation for details on:
        GetHardwareDefinition, GetConfiguration, etc.

        Args:
            queryName: Name of the query that was executed
            answer: The query result as a list of dictionaries
        """
        pass

    def _applyUpdates(self, changesAsList: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
        """Apply updates received to the model.

        Args:
            changesAsList: List of object updates with their changes

        Returns:
            Dictionary of updated objects with their changed attributes
        """
        updates = self._model.processUpdates(changesAsList)

        # If an update happens on the SYSTEM object,
        # also apply it to our cached SystemInfo
        if self._systemInfo is not None:
            system_objnam = self._systemInfo.objnam
            if system_objnam in updates:
                self._systemInfo.update(updates[system_objnam])

        if updates and self._updatedCallback:
            self._updatedCallback(self, updates)

        return updates

    def receivedNotifyList(self, changes: list[dict[str, Any]]) -> None:
        """Handle notifications from IntelliCenter when tracked objects are modified.

        Args:
            changes: List of object changes from IntelliCenter
        """
        try:
            self._applyUpdates(changes)
        except (KeyError, TypeError, ValueError) as err:
            # Data structure issues - log but don't crash
            _LOGGER.error(f"CONTROLLER: Invalid data in NotifyList: {err}")
        except Exception:  # noqa: BLE001 - Callback must not crash
            _LOGGER.exception("CONTROLLER: Unexpected error in receivedNotifyList")

    def receivedWriteParamList(self, changes: list[dict[str, Any]]) -> None:
        """Handle the response to a change requested on an object.

        Args:
            changes: List of applied changes
        """
        try:
            self._applyUpdates(changes)
        except (KeyError, TypeError, ValueError) as err:
            # Data structure issues - log but don't crash
            _LOGGER.error(f"CONTROLLER: Invalid data in WriteParamList: {err}")
        except Exception:  # noqa: BLE001 - Callback must not crash
            _LOGGER.exception("CONTROLLER: Unexpected error in receivedWriteParamList")

    def receivedSystemConfig(self, objectList: list[dict[str, Any]]) -> None:
        """Handle the response for a request for objects.

        Args:
            objectList: List of objects received from the system
        """
        _LOGGER.debug(f"CONTROLLER: received SystemConfig for {len(objectList)} object(s)")
        # Note that here we might create new objects
        self.model.addObjects(objectList)

    def processMessage(self, command: str, msg: dict[str, Any]) -> None:
        """Handle the callback for an incoming message.

        Args:
            command: The command type from the message
            msg: The full message dictionary
        """
        _LOGGER.debug(f"CONTROLLER: received {command} response: {msg}")

        try:
            if command == "SendQuery":
                self.receivedQueryResult(msg["queryName"], msg["answer"])
            elif command == "NotifyList":
                self.receivedNotifyList(msg["objectList"])
            elif command == "WriteParamList":
                self.receivedWriteParamList(msg["objectList"][0]["changes"])
            elif command == "SendParamList":
                self.receivedSystemConfig(msg["objectList"])
            else:
                _LOGGER.debug(f"no handler for {command}")
        except (KeyError, IndexError) as err:
            # Missing expected fields in message
            _LOGGER.error(f"CONTROLLER: Message missing expected field: {err} in {command}")
        except Exception:  # noqa: BLE001 - Callback must not crash
            _LOGGER.exception(f"CONTROLLER: Unexpected error processing {command}")


# -------------------------------------------------------------------------------------

# Reconnection configuration constants
DEFAULT_RECONNECT_DELAY = 30  # Initial delay between reconnection attempts in seconds
DEFAULT_DISCONNECT_DEBOUNCE = 15  # Grace period before marking as disconnected
MAX_RECONNECT_DELAY = 600  # Maximum delay between reconnection attempts (10 minutes)

# Circuit breaker configuration
CIRCUIT_BREAKER_FAILURES = 5  # Number of consecutive failures before opening circuit
CIRCUIT_BREAKER_RESET_TIME = 300  # Time (seconds) before resetting failure count


class ConnectionHandler:
    """Helper class to manage connect/disconnect/reconnect cycle of a controller.

    This class wraps a controller and provides:
    - Automatic reconnection with exponential backoff
    - Debounced disconnect notifications to avoid UI flapping
    - Callbacks for connection state changes (started, reconnected, disconnected)
    """

    def __init__(
        self,
        controller: BaseController | ModelController,
        timeBetweenReconnects: int = DEFAULT_RECONNECT_DELAY,
        disconnectDebounceTime: int = DEFAULT_DISCONNECT_DEBOUNCE,
    ) -> None:
        """Initialize the handler.

        Args:
            controller: The controller to manage
            timeBetweenReconnects: Initial delay between reconnection attempts (default: 30s)
            disconnectDebounceTime: Grace period before marking as disconnected (default: 15s)
                This prevents rapid online/offline transitions from triggering notifications
        """
        self._controller = controller

        self._starterTask: asyncio.Task[None] | None = None
        self._stopped = False
        self._firstTime = True

        self._timeBetweenReconnects = timeBetweenReconnects
        self._disconnectDebounceTime = disconnectDebounceTime
        self._disconnectDebounceTask: asyncio.Task[None] | None = None
        self._isConnected = False

        # Circuit breaker state
        self._failure_count = 0
        self._last_failure_time: float | None = None

        controller._disconnected_callback = self._disconnected_callback

        if hasattr(controller, "_updatedCallback"):
            controller._updatedCallback = self.updated

    @property
    def controller(self) -> BaseController | ModelController:
        """Return the controller the handler manages."""
        return self._controller

    async def start(self) -> None:
        """Start the handler loop."""
        if not self._starterTask:
            self._starterTask = asyncio.create_task(self._starter())

    def _next_delay(self, currentDelay: int) -> int:
        """Compute the delay before the next reconnection attempt.

        Uses exponential backoff with a 1.5 factor, capped at MAX_RECONNECT_DELAY.
        """
        next_delay = int(currentDelay * 1.5)
        return min(next_delay, MAX_RECONNECT_DELAY)

    async def _starter(self, initial_delay: int = 0) -> None:
        """Attempt to start the controller.

        Implements circuit breaker pattern: after CIRCUIT_BREAKER_FAILURES
        consecutive failures, pauses for CIRCUIT_BREAKER_RESET_TIME before
        continuing to prevent hammering an unresponsive server.

        Args:
            initial_delay: Initial delay before first connection attempt.
        """
        started = False
        delay = self._timeBetweenReconnects
        while not started:
            try:
                # Check circuit breaker - reset if enough time has passed
                current_time = time.monotonic()
                if self._last_failure_time:
                    time_since_failure = current_time - self._last_failure_time
                    if time_since_failure > CIRCUIT_BREAKER_RESET_TIME:
                        self._failure_count = 0
                        self._last_failure_time = None

                # Circuit breaker open - wait before trying again
                if self._failure_count >= CIRCUIT_BREAKER_FAILURES:
                    _LOGGER.warning(
                        f"Circuit breaker open after {self._failure_count} failures - "
                        f"pausing for {CIRCUIT_BREAKER_RESET_TIME}s"
                    )
                    await asyncio.sleep(CIRCUIT_BREAKER_RESET_TIME)
                    self._failure_count = 0
                    self._last_failure_time = None

                if initial_delay:
                    self.retrying(initial_delay)
                    # Track reconnection attempt in metrics
                    self._controller._metrics.reconnect_attempts += 1
                    await asyncio.sleep(initial_delay)
                _LOGGER.debug("trying to start controller")

                await self._controller.start()

                # Success - reset circuit breaker
                self._failure_count = 0
                self._last_failure_time = None

                # Cancel any pending disconnect debounce
                if self._disconnectDebounceTask and not self._disconnectDebounceTask.done():
                    self._disconnectDebounceTask.cancel()
                    self._disconnectDebounceTask = None

                if self._firstTime:
                    self.started(self._controller)
                    self._firstTime = False
                    self._isConnected = True
                else:
                    # Only call reconnected if we were previously marked as disconnected
                    if not self._isConnected:
                        self.reconnected(self._controller)
                    self._isConnected = True

                started = True
                self._starterTask = None
            except (TimeoutError, ConnectionError, OSError, CommandError) as err:
                # Track failure for circuit breaker
                self._failure_count += 1
                self._last_failure_time = time.monotonic()

                # Track reconnection attempt in metrics
                self._controller._metrics.reconnect_attempts += 1

                _LOGGER.error(
                    f"cannot start: {err} "
                    f"(failure {self._failure_count}/{CIRCUIT_BREAKER_FAILURES})"
                )
                self.retrying(delay)
                await asyncio.sleep(delay)
                delay = self._next_delay(delay)

    def stop(self) -> None:
        """Stop the handler and the associated controller."""
        _LOGGER.debug(f"terminating connection to {self._controller.host}")
        self._stopped = True
        if self._starterTask:
            self._starterTask.cancel()
            self._starterTask = None
        if self._disconnectDebounceTask and not self._disconnectDebounceTask.done():
            self._disconnectDebounceTask.cancel()
            self._disconnectDebounceTask = None
        self._controller.stop()

    async def _delayed_disconnect_notification(
        self, controller: BaseController, err: Exception | None
    ) -> None:
        """Notify about disconnection after debounce period.

        This prevents rapid online/offline notifications when the connection
        is unstable or briefly interrupted.
        """
        try:
            await asyncio.sleep(self._disconnectDebounceTime)
            # Only notify if we're still not connected after the debounce period
            if not self._isConnected:
                _LOGGER.info(
                    f"system confirmed disconnected from {self._controller.host} "
                    f"after {self._disconnectDebounceTime}s grace period"
                )
                self.disconnected(controller, err)
        except asyncio.CancelledError:
            _LOGGER.debug("disconnect notification cancelled - system reconnected")

    def _disconnected_callback(
        self,
        controller: BaseController,
        err: Exception | None,
    ) -> None:
        """Handle the disconnection of the underlying controller.

        Args:
            controller: The controller that disconnected
            err: The exception that caused disconnection, or None if heartbeat missed
        """
        if not self._stopped:
            _LOGGER.warning(
                f"system disconnected from {self._controller.host} "
                f"{err if err else ''} "
                f"- waiting {self._disconnectDebounceTime}s before marking unavailable"
            )

            # Mark as disconnected immediately for internal tracking
            self._isConnected = False

            # Schedule debounced disconnect notification
            if self._disconnectDebounceTask and not self._disconnectDebounceTask.done():
                self._disconnectDebounceTask.cancel()
            self._disconnectDebounceTask = asyncio.create_task(
                self._delayed_disconnect_notification(controller, err)
            )

            # Start reconnection attempt
            self._starterTask = asyncio.create_task(self._starter(self._timeBetweenReconnects))

    def started(self, controller: BaseController) -> None:
        """Handle the first time the controller is started.

        Override this method to perform actions on initial connection.
        Further reconnections will trigger reconnected() instead.

        Args:
            controller: The controller that started
        """
        pass

    def retrying(self, delay: int) -> None:
        """Handle the fact that we will retry connection in {delay} seconds.

        Args:
            delay: Number of seconds until next retry attempt
        """
        _LOGGER.info(f"will attempt to reconnect in {delay}s")

    def updated(self, controller: ModelController, updates: dict[str, dict[str, Any]]) -> None:
        """Handle the callback that our underlying system has been modified.

        Only invoked if the controller has a _updatedCallback attribute.

        Args:
            controller: The controller that received updates
            updates: Dictionary of updated objects with their changed attributes
        """
        pass

    def disconnected(self, controller: BaseController, exc: Exception | None) -> None:
        """Handle the controller being disconnected.

        Called after the debounce period if still disconnected.

        Args:
            controller: The controller that disconnected
            exc: The exception that caused disconnection, or None if heartbeat missed
        """
        pass

    def reconnected(self, controller: BaseController) -> None:
        """Handle the controller being reconnected.

        Only called if the controller was previously connected and then disconnected.

        Args:
            controller: The controller that reconnected
        """
        pass
