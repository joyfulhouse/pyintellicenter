"""Controller classes for Pentair IntelliCenter.

This module provides controller classes that manage communication
with the Pentair IntelliCenter system using modern asyncio patterns.

Classes:
    ICBaseController: Basic connection and command handling
    ICModelController: Extends ICBaseController with PoolModel management
    ICConnectionHandler: Manages reconnection with exponential backoff
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import time
from dataclasses import asdict, dataclass, field
from typing import TYPE_CHECKING, Any, ClassVar, Protocol, runtime_checkable

from ._mixins import (
    _BodyMixin,
    _ChemistryMixin,
    _CircuitGroupMixin,
    _CoverMixin,
    _HeaterMixin,
    _LightMixin,
    _PumpMixin,
    _ScheduleMixin,
    _SensorMixin,
    _SystemMixin,
)

# Backward-compatible re-exports: these chemistry validation constants now live in
# ._mixins.chemistry but were historically importable from this module
# (pyintellicenter.controller.<CONST>). Re-export them with redundant aliases so
# the original import path keeps working and consumers are not broken.
from ._mixins.chemistry import (
    ALKALINITY_MAX as ALKALINITY_MAX,
)
from ._mixins.chemistry import (
    ALKALINITY_MIN as ALKALINITY_MIN,
)
from ._mixins.chemistry import (
    CALCIUM_HARDNESS_MAX as CALCIUM_HARDNESS_MAX,
)
from ._mixins.chemistry import (
    CALCIUM_HARDNESS_MIN as CALCIUM_HARDNESS_MIN,
)
from ._mixins.chemistry import (
    CHLORINATOR_PERCENT_MAX as CHLORINATOR_PERCENT_MAX,
)
from ._mixins.chemistry import (
    CHLORINATOR_PERCENT_MIN as CHLORINATOR_PERCENT_MIN,
)
from ._mixins.chemistry import (
    CYANURIC_ACID_MAX as CYANURIC_ACID_MAX,
)
from ._mixins.chemistry import (
    CYANURIC_ACID_MIN as CYANURIC_ACID_MIN,
)
from ._mixins.chemistry import (
    ORP_MAX as ORP_MAX,
)
from ._mixins.chemistry import (
    ORP_MIN as ORP_MIN,
)
from ._mixins.chemistry import (
    PH_MAX as PH_MAX,
)
from ._mixins.chemistry import (
    PH_MIN as PH_MIN,
)
from ._mixins.chemistry import (
    PH_STEP as PH_STEP,
)

# Backward-compatible re-exports of attribute/type constants. These names were all
# importable from this module (pyintellicenter.controller.<NAME>) before the helper
# methods that used them were extracted into ._mixins. The extraction moved their
# only local uses out of controller.py, but the module namespace must stay stable
# for any consumer importing them from here. Re-export with redundant aliases
# (NAME as NAME) so the names are intentional public re-exports rather than unused
# imports. (Names still used locally above are intentionally not repeated here.)
# Guarded by tests/test_controller_namespace_compat.py.
from .attributes import (
    ACT_ATTR as ACT_ATTR,
)
from .attributes import (
    ALK_ATTR as ALK_ATTR,
)
from .attributes import (
    ASSIGN_ATTR as ASSIGN_ATTR,
)
from .attributes import (
    BODY_ATTR as BODY_ATTR,
)
from .attributes import (
    BODY_TYPE as BODY_TYPE,
)
from .attributes import (
    CALC_ATTR as CALC_ATTR,
)
from .attributes import (
    CHEM_TYPE as CHEM_TYPE,
)
from .attributes import (
    CIRCGRP_TYPE as CIRCGRP_TYPE,
)
from .attributes import (
    CIRCUIT_ATTR as CIRCUIT_ATTR,
)
from .attributes import (
    CIRCUIT_TYPE as CIRCUIT_TYPE,
)
from .attributes import (
    CYACID_ATTR as CYACID_ATTR,
)
from .attributes import (
    EXTINSTR_TYPE as EXTINSTR_TYPE,
)
from .attributes import (
    GPM_ATTR as GPM_ATTR,
)
from .attributes import (
    HEATER_ATTR as HEATER_ATTR,
)
from .attributes import (
    HEATER_TYPE as HEATER_TYPE,
)
from .attributes import (
    HITMP_ATTR as HITMP_ATTR,
)
from .attributes import (
    HTMODE_ATTR as HTMODE_ATTR,
)
from .attributes import (
    LIGHT_EFFECTS as LIGHT_EFFECTS,
)
from .attributes import (
    LOTMP_ATTR as LOTMP_ATTR,
)
from .attributes import (
    MAX_ATTR as MAX_ATTR,
)
from .attributes import (
    MAXF_ATTR as MAXF_ATTR,
)
from .attributes import (
    MIN_ATTR as MIN_ATTR,
)
from .attributes import (
    MINF_ATTR as MINF_ATTR,
)
from .attributes import (
    MODE_ATTR,
    OBJTYP_ATTR,
    PARENT_ATTR,
    PROPNAME_ATTR,
    SNAME_ATTR,
    STATUS_ATTR,
    STATUS_OFF,
    STATUS_ON,
    SUBTYP_ATTR,
    SYSTEM_TYPE,
    VER_ATTR,
)
from .attributes import (
    NULL_OBJNAM as NULL_OBJNAM,
)
from .attributes import (
    ORPHI_ATTR as ORPHI_ATTR,
)
from .attributes import (
    ORPLO_ATTR as ORPLO_ATTR,
)
from .attributes import (
    ORPSET_ATTR as ORPSET_ATTR,
)
from .attributes import (
    ORPVAL_ATTR as ORPVAL_ATTR,
)
from .attributes import (
    PHHI_ATTR as PHHI_ATTR,
)
from .attributes import (
    PHLO_ATTR as PHLO_ATTR,
)
from .attributes import (
    PHSET_ATTR as PHSET_ATTR,
)
from .attributes import (
    PHVAL_ATTR as PHVAL_ATTR,
)
from .attributes import (
    PMPCIRC_TYPE as PMPCIRC_TYPE,
)
from .attributes import (
    PRIM_ATTR as PRIM_ATTR,
)
from .attributes import (
    PUMP_STATUS_ON as PUMP_STATUS_ON,
)
from .attributes import (
    PUMP_TYPE as PUMP_TYPE,
)
from .attributes import (
    PWR_ATTR as PWR_ATTR,
)
from .attributes import (
    QUALTY_ATTR as QUALTY_ATTR,
)
from .attributes import (
    RPM_ATTR as RPM_ATTR,
)
from .attributes import (
    SALT_ATTR as SALT_ATTR,
)
from .attributes import (
    SCHED_TYPE as SCHED_TYPE,
)
from .attributes import (
    SEC_ATTR as SEC_ATTR,
)
from .attributes import (
    SELECT_ATTR as SELECT_ATTR,
)
from .attributes import (
    SENSE_TYPE as SENSE_TYPE,
)
from .attributes import (
    SOURCE_ATTR as SOURCE_ATTR,
)
from .attributes import (
    SPEED_ATTR as SPEED_ATTR,
)
from .attributes import (
    SUPER_ATTR as SUPER_ATTR,
)
from .attributes import (
    TEMP_ATTR as TEMP_ATTR,
)
from .attributes import (
    USE_ATTR as USE_ATTR,
)
from .attributes import (
    VACFLO_ATTR as VACFLO_ATTR,
)
from .attributes import (
    VALVE_TYPE as VALVE_TYPE,
)
from .attributes import (
    HeaterType as HeaterType,
)
from .connection import DEFAULT_TCP_PORT, DEFAULT_WEBSOCKET_PORT, ICConnection, TransportType
from .exceptions import ICCommandError, ICConnectionError, ICError, ICResponseError, ICTimeoutError

if TYPE_CHECKING:
    from collections.abc import AsyncIterator, Callable
    from contextlib import AbstractAsyncContextManager

    from .model import PoolModel, PoolObject
    from .types import ObjectEntry

_LOGGER = logging.getLogger(__name__)

# Configuration constants
MAX_ATTRIBUTES_PER_QUERY = 50  # Maximum attributes per query batch


@dataclass
class ICConnectionMetrics:
    """Tracks connection metrics for observability."""

    requests_sent: int = 0
    requests_completed: int = 0
    requests_failed: int = 0
    reconnect_attempts: int = 0
    successful_connects: int = 0

    def to_dict(self) -> dict[str, int]:
        """Return metrics as a dictionary."""
        return asdict(self)

    def __repr__(self) -> str:
        return (
            f"ICConnectionMetrics(sent={self.requests_sent}, "
            f"completed={self.requests_completed}, failed={self.requests_failed})"
        )


@dataclass
class _PendingRequest:
    """A pending property change request waiting to be sent.

    Used internally by ICModelController for request coalescing.
    Multiple requests for the same (objnam, attribute) are merged,
    with the latest value winning.
    """

    changes: dict[str, dict[str, str]]
    future: asyncio.Future[dict[str, Any]] = field(default_factory=asyncio.Future)


class ICSystemInfo:
    """Represents system information from IntelliCenter.

    Contains metadata like software version, temperature units,
    and a unique identifier.
    """

    ATTRIBUTES_LIST: ClassVar[list[str]] = [
        PROPNAME_ATTR,
        VER_ATTR,
        MODE_ATTR,
        SNAME_ATTR,
    ]

    def __init__(self, objnam: str, params: dict[str, Any]) -> None:
        # Lazy import to avoid loading hashlib at module level
        from hashlib import blake2b

        self._objnam = objnam
        self._prop_name: str = params[PROPNAME_ATTR]
        self._sw_version: str = params[VER_ATTR]
        self._mode: str = params[MODE_ATTR]

        # Generate unique ID from system name
        h = blake2b(digest_size=8)
        h.update(params[SNAME_ATTR].encode())
        self._unique_id = h.hexdigest()

    def __repr__(self) -> str:
        return (
            f"ICSystemInfo(objnam={self._objnam!r}, prop_name={self._prop_name!r}, "
            f"version={self._sw_version!r}, metric={self.uses_metric})"
        )

    @property
    def prop_name(self) -> str:
        """Return the property name."""
        return self._prop_name

    @property
    def sw_version(self) -> str:
        """Return the software version."""
        return self._sw_version

    @property
    def uses_metric(self) -> bool:
        """Return True if system uses metric units."""
        return self._mode == "METRIC"

    @property
    def unique_id(self) -> str:
        """Return unique identifier for this system."""
        return self._unique_id

    @property
    def objnam(self) -> str:
        """Return the object name."""
        return self._objnam

    def update(self, updates: dict[str, Any]) -> None:
        """Update system info from attribute changes."""
        if PROPNAME_ATTR in updates:
            self._prop_name = updates[PROPNAME_ATTR]
        if VER_ATTR in updates:
            self._sw_version = updates[VER_ATTR]
        if MODE_ATTR in updates:
            self._mode = updates[MODE_ATTR]


def prune(obj: Any) -> Any:
    """Remove undefined parameters (where key == value) from object tree."""
    if isinstance(obj, list):
        return [prune(item) for item in obj]
    if isinstance(obj, dict):
        return {k: prune(v) for k, v in obj.items() if k != v}
    return obj


@dataclass
class _RequestContext:
    """Context for tracking a single request's metrics."""

    metrics: ICConnectionMetrics
    success: bool = field(default=False, init=False)

    def __enter__(self) -> _RequestContext:
        self.metrics.requests_sent += 1
        return self

    def __exit__(self, exc_type: type | None, exc_val: Exception | None, exc_tb: Any) -> None:
        if exc_type is None:
            self.metrics.requests_completed += 1
        else:
            self.metrics.requests_failed += 1


class ICBaseController:
    """Controller for communicating with IntelliCenter.

    Uses modern asyncio streams for clean, efficient communication.
    """

    def __init__(
        self,
        host: str,
        port: int | None = None,
        keepalive_interval: float | None = None,
        transport: TransportType = "tcp",
    ) -> None:
        """Initialize the controller.

        Args:
            host: IP address or hostname of IntelliCenter
            port: Port number (default: 6681 for TCP, 6680 for WebSocket)
            keepalive_interval: Seconds between keepalive requests
            transport: Transport type - "tcp" or "websocket" (default: "tcp")
        """
        self._host = host
        self._transport = transport
        self._port = (
            port
            if port is not None
            else (DEFAULT_WEBSOCKET_PORT if transport == "websocket" else DEFAULT_TCP_PORT)
        )
        self._keepalive_interval = keepalive_interval or 90.0

        # Connection
        self._connection: ICConnection | None = None
        self._system_info: ICSystemInfo | None = None

        # Callbacks
        self._disconnected_callback: Callable[[ICBaseController, Exception | None], None] | None = (
            None
        )

        # Metrics
        self._metrics = ICConnectionMetrics()

        # Object writes share one controller-wide mutation lifecycle. Color Sync
        # marks its long-running lifecycle pending before waiting for older
        # admitted writers, then authorizes its captured-connection requests with
        # one unforgeable identity token.
        self._mutation_lock = asyncio.Lock()
        self._mutation_owner: asyncio.Task[Any] | None = None
        self._light_group_mutation_pending = False
        self._light_group_mutation_lease: object | None = None

    def __repr__(self) -> str:
        return (
            f"ICBaseController(host={self._host!r}, port={self._port}, "
            f"transport={self._transport!r}, connected={self.connected})"
        )

    @property
    def host(self) -> str:
        """Return the host address."""
        return self._host

    @property
    def transport(self) -> TransportType:
        """Return the transport type."""
        return self._transport

    @property
    def metrics(self) -> ICConnectionMetrics:
        """Return connection metrics."""
        return self._metrics

    @property
    def system_info(self) -> ICSystemInfo | None:
        """Return cached system information."""
        return self._system_info

    @property
    def connected(self) -> bool:
        """Return True if connected."""
        return self._connection is not None and self._connection.connected

    def set_disconnected_callback(
        self, callback: Callable[[ICBaseController, Exception | None], None] | None
    ) -> None:
        """Set callback for disconnection events."""
        self._disconnected_callback = callback

    async def start(self) -> None:
        """Connect and retrieve system information.

        Raises:
            ICConnectionError: If connection fails
            ICCommandError: If system info request fails
        """
        # Tear down any previous connection before replacing it: overwriting
        # the reference leaks the old socket and its keepalive task, and a late
        # disconnect event from it would masquerade as the live connection's.
        if self._connection:
            with contextlib.suppress(Exception):
                await self._connection.disconnect()
            self._connection = None

        # Create connection
        connection = ICConnection(
            self._host,
            self._port,
            keepalive_interval=self._keepalive_interval,
            transport=self._transport,
        )

        # Set disconnect callback. The identity check ignores events from a
        # connection this controller has since replaced - a stale socket dying
        # must not tear down (or trigger reconnection of) the live one.
        def _on_connection_disconnect(exc: Exception | None) -> None:
            if self._connection is connection:
                self._on_disconnect(exc)
            else:
                _LOGGER.debug("Ignoring disconnect from a replaced connection")

        connection.set_disconnect_callback(_on_connection_disconnect)
        self._connection = connection

        # Connect
        await self._connection.connect()
        self._metrics.successful_connects += 1

        _LOGGER.debug("Connected to IC at %s:%s", self._host, self._port)

        # Fetch system info
        with _RequestContext(self._metrics):
            try:
                response = await self._connection.send_request(
                    "GetParamList",
                    condition=f"{OBJTYP_ATTR}={SYSTEM_TYPE}",
                    objectList=[{"objnam": "INCR", "keys": ICSystemInfo.ATTRIBUTES_LIST}],
                )
                info = response["objectList"][0]
                self._system_info = ICSystemInfo(info["objnam"], info["params"])
            except ICResponseError as err:
                raise ICCommandError(err.code) from err

    async def stop(self) -> None:
        """Stop the controller and disconnect."""
        if self._connection:
            await self._connection.disconnect()
            self._connection = None

    def _on_disconnect(self, exc: Exception | None) -> None:
        """Handle disconnection from connection layer."""
        if self._disconnected_callback:
            self._disconnected_callback(self, exc)

    async def send_cmd(
        self,
        cmd: str,
        extra: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Send a command and return the response.

        Args:
            cmd: Command name (e.g., "GetParamList")
            extra: Additional parameters

        Returns:
            Response dictionary

        Mutation boundary:
            Case-insensitive ``SetParamList`` is the controller's supported
            object-writer command. Once Color Sync marks its mutation lifecycle
            pending, later same-controller object writes fail immediately and
            must be retried deliberately; they are never queued for replay after
            Sync. Read-only commands continue. Undocumented vendor writers and a
            separately constructed raw ``ICConnection`` are outside this
            controller boundary.

        Raises:
            ICConnectionError: If not connected
            ICCommandError: If command fails
        """
        is_object_writer = cmd.casefold() == "setparamlist"
        if is_object_writer and self._light_group_mutation_pending:
            raise ICError("Color Sync mutation lifecycle is in progress")

        async def _send_on_current_connection() -> dict[str, Any]:
            connection = self._connection
            if connection is None or not connection.connected:
                raise ICConnectionError("Not connected")

            with _RequestContext(self._metrics):
                try:
                    return await connection.send_request(cmd, **(extra or {}))
                except ICResponseError as err:
                    raise ICCommandError(err.code) from err

        if not is_object_writer:
            return await _send_on_current_connection()

        async with self._mutation_lifecycle():
            return await _send_on_current_connection()

    def _mutation_lifecycle(self) -> AbstractAsyncContextManager[None]:
        """Serialize an ordinary object writer and record its owning task."""

        @contextlib.asynccontextmanager
        async def _lifecycle() -> AsyncIterator[None]:
            await self._mutation_lock.acquire()
            self._mutation_owner = asyncio.current_task()
            try:
                yield
            finally:
                self._mutation_owner = None
                self._mutation_lock.release()

        return _lifecycle()

    def _light_group_mutation_lifecycle(self) -> AbstractAsyncContextManager[object]:
        """Own the exclusive Color Sync lifecycle and yield its opaque lease."""

        @contextlib.asynccontextmanager
        async def _lifecycle() -> AsyncIterator[object]:
            if self._light_group_mutation_pending:
                raise ICError("Color Sync mutation lifecycle is in progress")

            # No await may occur between admission and this mark: later public and
            # coalesced writers must observe the lifecycle immediately.
            self._light_group_mutation_pending = True
            acquired = False
            try:
                await self._mutation_lock.acquire()
                acquired = True
                self._mutation_owner = asyncio.current_task()
                lease = object()
                self._light_group_mutation_lease = lease
                yield lease
            finally:
                if acquired:
                    # Callers must cancel and await delegated children before
                    # leaving this context. Invalidate authorization before
                    # releasing the lifecycle to a later writer.
                    self._light_group_mutation_lease = None
                    self._mutation_owner = None
                    self._mutation_lock.release()
                self._light_group_mutation_pending = False

        return _lifecycle()

    async def _send_cmd_on_connection_unlocked(
        self,
        connection: ICConnection,
        cmd: str,
        extra: dict[str, Any] | None = None,
        *,
        _mutation_lease: object,
        request_timeout: float | None = None,
        _before_write_callback: Callable[[int, float], None] | None = None,
        _after_write_callback: Callable[[int], None] | None = None,
    ) -> dict[str, Any]:
        """Send on the captured connection under the active opaque Sync lease."""
        if (
            not self._light_group_mutation_pending
            or not self._mutation_lock.locked()
            or self._mutation_owner is None
            or self._light_group_mutation_lease is None
            or self._light_group_mutation_lease is not _mutation_lease
        ):
            raise ICError("Invalid or inactive Color Sync mutation lease")
        if self._connection is not connection or not connection.connected:
            raise ICConnectionError("Connection changed or is not connected")

        with _RequestContext(self._metrics):
            try:
                return await connection.send_request(
                    cmd,
                    request_timeout=request_timeout,
                    _before_write_callback=_before_write_callback,
                    _after_write_callback=_after_write_callback,
                    **(extra or {}),
                )
            except ICResponseError as err:
                raise ICCommandError(err.code) from err

    async def request_changes(
        self,
        objnam: str,
        changes: dict[str, Any],
    ) -> dict[str, Any]:
        """Submit changes for an object.

        Args:
            objnam: Object name to modify
            changes: Attribute changes to apply

        Returns:
            Response dictionary
        """
        return await self.send_cmd(
            "SETPARAMLIST",
            {"objectList": [{"objnam": objnam, "params": changes}]},
        )

    async def get_all_objects(self, attribute_list: list[str]) -> list[ObjectEntry]:
        """Fetch attributes for all objects.

        Args:
            attribute_list: Attributes to fetch

        Returns:
            List of objects with their attributes
        """
        result = await self.send_cmd(
            "GetParamList",
            {"condition": "", "objectList": [{"objnam": "INCR", "keys": attribute_list}]},
        )
        pruned: list[ObjectEntry] = prune(result["objectList"])
        return pruned

    async def get_query(self, query_name: str, arguments: str = "") -> list[dict[str, Any]]:
        """Execute a query.

        Args:
            query_name: Query name
            arguments: Optional arguments

        Returns:
            Query results
        """
        result = await self.send_cmd("GetQuery", {"queryName": query_name, "arguments": arguments})
        answer: list[dict[str, Any]] = result["answer"]
        return answer

    async def get_configuration(self) -> list[dict[str, Any]]:
        """Get system configuration with bodies and circuits.

        This matches node-intellicenter's GetQuery with queryName="GetConfiguration".

        Returns:
            List of configuration objects including bodies and circuits
        """
        return await self.get_query("GetConfiguration")

    async def get_hardware_definition(self) -> list[dict[str, Any]]:
        """Get complete hardware definition with full object hierarchy.

        Returns the entire panel configuration including all objects in a
        hierarchical structure. Each object includes type, subtype, and
        relationships to other objects.

        This is more comprehensive than get_configuration() and includes
        all equipment types: bodies, circuits, pumps, heaters, chemistry
        controllers, valves, sensors, schedules, remotes, and modules.

        Returns:
            List of hardware definition objects with full hierarchy
        """
        return await self.get_query("GetHardwareDefinition")


class ICModelController(
    _ChemistryMixin,
    _SensorMixin,
    _CoverMixin,
    _ScheduleMixin,
    _CircuitGroupMixin,
    _LightMixin,
    _PumpMixin,
    _BodyMixin,
    _SystemMixin,
    _HeaterMixin,
    ICBaseController,
):
    """Controller that maintains a PoolModel of equipment state."""

    def __init__(
        self,
        host: str,
        model: PoolModel,
        port: int | None = None,
        keepalive_interval: float | None = None,
        transport: TransportType = "tcp",
    ) -> None:
        """Initialize the controller.

        Args:
            host: IP address or hostname of IntelliCenter
            model: PoolModel to populate and update
            port: Port number (default: 6681 for TCP, 6680 for WebSocket)
            keepalive_interval: Seconds between keepalive requests
            transport: Transport type - "tcp" or "websocket" (default: "tcp")
        """
        super().__init__(host, port, keepalive_interval, transport)
        self._model = model
        self._updated_callback: (
            Callable[[ICModelController, dict[str, dict[str, Any]]], None] | None
        ) = None

        # Request coalescing state
        # When multiple convenience method calls happen while a request is in-flight,
        # they are merged into a single batch request. Latest value wins for same (objnam, attr).
        self._pending_changes: dict[str, dict[str, str]] = {}  # objnam -> {attr: value}
        self._pending_requests: list[_PendingRequest] = []
        self._coalesce_lock = asyncio.Lock()

        # Background tasks that request monitoring for objects added at runtime.
        # Held in a set so they are not garbage-collected before completing.
        self._monitor_tasks: set[asyncio.Task[None]] = set()

    def __repr__(self) -> str:
        return (
            f"ICModelController(host={self._host!r}, port={self._port}, "
            f"transport={self._transport!r}, connected={self.connected}, "
            f"objects={self._model.num_objects})"
        )

    @property
    def model(self) -> PoolModel:
        """Return the model."""
        return self._model

    def set_updated_callback(
        self, callback: Callable[[ICModelController, dict[str, dict[str, Any]]], None] | None
    ) -> None:
        """Set callback for model updates."""
        self._updated_callback = callback

    async def start(self) -> None:
        """Connect, fetch objects, and start monitoring.

        Raises:
            ICConnectionError: If connection fails
            ICCommandError: If initialization fails
        """
        await super().start()

        # Set notification callback
        if self._connection:
            self._connection.set_notification_callback(self._on_notification)

        # Fetch all objects
        all_objects = await self.get_all_objects(
            [OBJTYP_ATTR, SUBTYP_ATTR, SNAME_ATTR, PARENT_ATTR]
        )
        self._model.add_objects(all_objects)
        _LOGGER.info("Model contains %d objects", self._model.num_objects)

        # Request monitoring of attributes in batches
        attributes = self._model.attributes_to_track()
        query: list[dict[str, Any]] = []
        num_attributes = 0

        for items in attributes:
            query.append(items)
            num_attributes += len(items["keys"])

            # Batch to avoid overwhelming the system
            if num_attributes >= MAX_ATTRIBUTES_PER_QUERY:
                res = await self.send_cmd("RequestParamList", {"objectList": query})
                self._apply_updates(res["objectList"])
                query = []
                num_attributes = 0

        # Send remaining
        if query:
            res = await self.send_cmd("RequestParamList", {"objectList": query})
            self._apply_updates(res["objectList"])

    def _on_notification(self, msg: dict[str, Any]) -> None:
        """Handle NotifyList notifications."""
        if msg.get("command") == "NotifyList":
            try:
                self._apply_updates(msg["objectList"])
            except (KeyError, TypeError, ValueError) as err:
                _LOGGER.exception("Error processing NotifyList: %s", err)

    def _apply_updates(self, changes_as_list: list[ObjectEntry]) -> dict[str, dict[str, Any]]:
        """Apply updates to the model.

        A NotifyList may introduce a brand-new object (e.g. equipment installed
        while the connection is live). process_updates() adds such objects to the
        model and reports their objnams via ``added_objnams``; we then schedule a
        RequestParamList so IntelliCenter starts pushing their monitored
        attributes (a newly-added object is not monitored otherwise).
        """
        added_objnams: set[str] = set()
        updates = self._model.process_updates(changes_as_list, added_objnams)

        # Update ICSystemInfo if changed
        if self._system_info and self._system_info.objnam in updates:
            self._system_info.update(updates[self._system_info.objnam])

        # Notify callback (newly-added objects are included in updates, so the
        # existing callback path surfaces them to consumers).
        if updates and self._updated_callback:
            self._updated_callback(self, updates)

        # Start monitoring any newly-added objects. This issues a network request,
        # so it runs as a background task; _on_notification is a synchronous
        # callback. If no event loop is running (e.g. direct synchronous calls in
        # tests) we skip scheduling rather than crash.
        if added_objnams:
            try:
                loop = asyncio.get_running_loop()
            except RuntimeError:
                _LOGGER.debug(
                    "No running loop; skipping monitor request for new objects %s",
                    added_objnams,
                )
            else:
                task = loop.create_task(self._request_monitoring_for(added_objnams))
                # Retain a reference so the task is not garbage-collected; the
                # done callback drops it and logs any unexpected failure.
                self._monitor_tasks.add(task)
                task.add_done_callback(self._on_monitor_task_done)

        return updates

    def _on_monitor_task_done(self, task: asyncio.Task[None]) -> None:
        """Discard a finished monitor task and surface any unexpected error.

        Expected connection errors are handled inside the task; this catches
        anything else (a bug, or a callback raising) so it is logged rather than
        silently swallowed by asyncio.
        """
        self._monitor_tasks.discard(task)
        if not task.cancelled():
            exc = task.exception()
            if exc is not None:
                _LOGGER.warning("Monitor request for new objects failed: %s", exc)

    async def _request_monitoring_for(self, objnams: set[str]) -> None:
        """Request attribute monitoring for the given (newly-added) objects.

        Builds the same per-object {objnam, keys} query that start() uses, from
        the model's attribute map, and sends it in batches bounded by
        MAX_ATTRIBUTES_PER_QUERY. Connection errors are logged and swallowed:
        this runs in a background task off the notification hot path.
        """
        # Reuse the model's tracking query, filtered to the new objects so we only
        # (re-)subscribe what is needed.
        queries = [q for q in self._model.attributes_to_track() if q["objnam"] in objnams]
        if not queries:
            return

        batch: list[dict[str, Any]] = []
        num_attributes = 0
        try:
            for items in queries:
                keys_len = len(items["keys"])
                # Flush the current batch before it would exceed the limit (a
                # single object with more keys than the limit is still sent alone).
                if batch and num_attributes + keys_len > MAX_ATTRIBUTES_PER_QUERY:
                    await self._send_monitor_batch(batch)
                    batch = []
                    num_attributes = 0
                batch.append(items)
                num_attributes += keys_len

            if batch:
                await self._send_monitor_batch(batch)
        except (ICConnectionError, ICCommandError, ICTimeoutError, OSError) as err:
            _LOGGER.warning("Failed to request monitoring for new objects %s: %s", objnams, err)

    async def _send_monitor_batch(self, batch: list[dict[str, Any]]) -> None:
        """Send one RequestParamList batch and apply the response.

        Validates the response shape so a malformed reply is logged and skipped
        rather than crashing the background monitor task.
        """
        res = await self.send_cmd("RequestParamList", {"objectList": batch})
        object_list = res.get("objectList")
        if not isinstance(object_list, list):
            _LOGGER.warning(
                "RequestParamList returned no usable objectList for monitor request: %r",
                res,
            )
            return
        self._apply_updates(object_list)

    # --------------------------------------------------------------------------
    # Request coalescing for convenience methods
    # --------------------------------------------------------------------------

    async def _queue_property_change(self, objnam: str, changes: dict[str, str]) -> dict[str, Any]:
        """Queue a property change with automatic coalescing.

        Used by convenience methods (set_*, etc.) to enable smart batching.
        When multiple calls happen while a request is in-flight, they are
        merged into a single batch request:

        - Same (objnam, attr): latest value wins
        - Different attrs on same objnam: merged into one params dict
        - Different objnams: batched into one SETPARAMLIST

        Direct API access via request_changes() bypasses coalescing for
        users who need precise control over request timing.

        Args:
            objnam: Object name to modify
            changes: Attribute changes to apply (already stringified)

        Returns:
            Response dictionary from the batched request
        """
        if self._light_group_mutation_pending:
            raise ICError("Color Sync mutation lifecycle is in progress")

        owned_changes = {objnam: dict(changes)}
        request = _PendingRequest(owned_changes)

        # Merge changes into pending (latest value wins for same objnam+attr)
        if objnam not in self._pending_changes:
            self._pending_changes[objnam] = {}
        self._pending_changes[objnam].update(owned_changes[objnam])

        # Track this request so it gets notified when batch completes
        self._pending_requests.append(request)

        # Try to flush - if lock is held, we wait and our changes get batched
        try:
            await self._flush_pending_changes(request)
            return await request.future
        except asyncio.CancelledError:
            self._remove_pending_request(request)
            raise

    def _rebuild_pending_changes(self) -> None:
        """Rebuild latest-wins aggregation from requests still awaiting detach."""
        rebuilt: dict[str, dict[str, str]] = {}
        for request in self._pending_requests:
            for objnam, attrs in request.changes.items():
                rebuilt.setdefault(objnam, {}).update(attrs)
        self._pending_changes = rebuilt

    def _remove_pending_request(self, request: _PendingRequest) -> None:
        """Remove one not-yet-detached request without leaving a live future."""
        removed = False
        for index, pending in enumerate(self._pending_requests):
            if pending is request:
                self._pending_requests.pop(index)
                removed = True
                break

        if removed:
            self._rebuild_pending_changes()

        if not request.future.done():
            request.future.cancel()
        # Cancellation can arrive after another flush detached this request and
        # completed its future with either a result or an exception. Always
        # retrieve the terminal state so a caller-level CancelledError cannot
        # orphan a completed exception warning.
        with contextlib.suppress(asyncio.CancelledError):
            request.future.exception()

    async def _flush_pending_changes(self, owner_request: _PendingRequest) -> None:
        """Flush all pending changes in a single batch request.

        Only one flush runs at a time. While one is in progress, new requests
        queue up and will be sent in the next batch.
        """
        async with self._coalesce_lock:
            # Another flush may already have detached and completed this
            # caller's request while it waited for the coalescing lock. Such a
            # caller must observe its own future next; it cannot detach or send
            # work admitted by a later caller.
            if not any(request is owner_request for request in self._pending_requests):
                return
            if not self._pending_changes:
                return

            # Atomically capture and clear pending state
            changes = self._pending_changes
            requests = self._pending_requests
            self._pending_changes = {}
            self._pending_requests = []

            # Build batched request
            object_list = [
                {"objnam": objnam, "params": params} for objnam, params in changes.items()
            ]

            _LOGGER.debug(
                "Flushing %d coalesced changes for %d objects",
                sum(len(p) for p in changes.values()),
                len(changes),
            )

            try:
                response = await self.send_cmd("SETPARAMLIST", {"objectList": object_list})
                # Resolve all waiting futures with the same response
                for req in requests:
                    if not req.future.done():
                        req.future.set_result(response)
            except asyncio.CancelledError:
                # The transport may already have accepted this batch. Never
                # requeue or retry it. The cancelled initiating caller keeps its
                # CancelledError; peers receive one stable uncertainty failure.
                if not owner_request.future.done():
                    owner_request.future.cancel()
                with contextlib.suppress(asyncio.CancelledError):
                    owner_request.future.exception()
                uncertainty = ICError(
                    "Coalesced mutation delivery is unknown after flush cancellation"
                )
                for req in requests:
                    if req is not owner_request and not req.future.done():
                        req.future.set_exception(uncertainty)
                raise
            except (ICError, OSError) as e:
                # Propagate error to all waiters
                for req in requests:
                    if not req.future.done():
                        req.future.set_exception(e)

    # --------------------------------------------------------------------------
    # Convenience methods for common operations
    # --------------------------------------------------------------------------

    async def set_circuit_state(self, objnam: str, state: bool) -> dict[str, Any]:
        """Set a circuit on or off.

        Args:
            objnam: Object name of the circuit
            state: True for ON, False for OFF

        Returns:
            Response dictionary

        Note:
            This method uses request coalescing. Multiple rapid calls will be
            batched together, with the latest state winning for each circuit.
        """
        return await self._queue_property_change(
            objnam, {STATUS_ATTR: STATUS_ON if state else STATUS_OFF}
        )

    async def set_multiple_circuit_states(self, objnams: list[str], state: bool) -> dict[str, Any]:
        """Set multiple circuits on or off simultaneously.

        This matches node-intellicenter's SetObjectStatus(array, boolean) functionality.

        Args:
            objnams: List of object names to control
            state: True for ON, False for OFF

        Returns:
            Response dictionary

        Note:
            This method uses request coalescing. All circuits are queued together
            and sent in a single batch request.
        """
        status = STATUS_ON if state else STATUS_OFF
        changes = {objnam: {STATUS_ATTR: status} for objnam in objnams}
        return await self._queue_batch_changes(changes)

    async def _queue_batch_changes(self, changes: dict[str, dict[str, str]]) -> dict[str, Any]:
        """Queue multiple object changes with automatic coalescing.

        More efficient than multiple _queue_property_change calls when you have
        multiple changes ready at once - creates only one Future for the batch.

        Args:
            changes: Dict mapping objnam -> {attr: value}

        Returns:
            Response dictionary from the batched request
        """
        if self._light_group_mutation_pending:
            raise ICError("Color Sync mutation lifecycle is in progress")

        owned_changes = {objnam: dict(attrs) for objnam, attrs in changes.items()}
        request = _PendingRequest(owned_changes)

        # Merge all changes into pending
        for objnam, attrs in owned_changes.items():
            if objnam not in self._pending_changes:
                self._pending_changes[objnam] = {}
            self._pending_changes[objnam].update(attrs)

        self._pending_requests.append(request)
        try:
            await self._flush_pending_changes(request)
            return await request.future
        except asyncio.CancelledError:
            self._remove_pending_request(request)
            raise

    def _get_attr_as_int(self, objnam: str, attr: str) -> int | None:
        """Get an attribute value as an integer, or None if unavailable."""
        obj = self._model[objnam]
        if obj and obj[attr]:
            try:
                return int(obj[attr])
            except (ValueError, TypeError):
                return None
        return None

    def _get_attr_as_float(self, objnam: str, attr: str) -> float | None:
        """Get an attribute value as a float, or None if unavailable."""
        obj = self._model[objnam]
        if obj and obj[attr]:
            try:
                return float(obj[attr])
            except (ValueError, TypeError):
                return None
        return None

    # =========================================================================
    # Entity Discovery Helpers (for Home Assistant integration setup)
    # =========================================================================

    def get_all_entities(self) -> dict[str, list[Any]]:
        """Get all entities grouped by type for Home Assistant discovery.

        Returns:
            Dict with keys: bodies, circuits, circuit_groups, lights, color_lights,
            color_light_groups, pumps, heaters, sensors, chem_controllers, schedules, valves
        """
        return {
            "bodies": self.get_bodies(),
            "circuits": [c for c in self.get_circuits() if not c.is_a_light],
            "circuit_groups": self.get_circuit_groups(),
            "lights": self.get_lights(include_shows=False),
            "light_shows": [obj for obj in self._model if obj.is_a_light_show],
            "color_lights": self.get_color_lights(),
            "color_light_groups": self.get_color_light_groups(),
            "pumps": self.get_pumps(),
            "heaters": self.get_heaters(),
            "sensors": self.get_sensors(),
            "chem_controllers": self.get_chem_controllers(),
            "schedules": self.get_schedules(),
            "valves": self.get_valves(),
        }

    def get_featured_entities(self) -> list[PoolObject]:
        """Get entities marked as 'featured' in IntelliCenter.

        These are typically the most important entities that should
        be prominently displayed.

        Returns:
            List of featured PoolObject
        """
        return [obj for obj in self._model if obj.is_featured]


# Reconnection constants
DEFAULT_RECONNECT_DELAY = 30
DEFAULT_DISCONNECT_DEBOUNCE = 15
MAX_RECONNECT_DELAY = 600
CIRCUIT_BREAKER_FAILURES = 5
CIRCUIT_BREAKER_RESET_TIME = 300


@runtime_checkable
class ICConnectionHandlerCallbacks(Protocol):
    """Protocol for ICConnectionHandler event callbacks.

    Implement this protocol to handle connection lifecycle events.
    """

    def on_started(self, controller: ICBaseController) -> None:
        """Called on initial successful connection."""
        ...

    def on_reconnected(self, controller: ICBaseController) -> None:
        """Called when reconnected after a disconnect."""
        ...

    def on_disconnected(self, controller: ICBaseController, exc: Exception | None) -> None:
        """Called when disconnected (after debounce period)."""
        ...

    def on_retrying(self, delay: int) -> None:
        """Called before each retry attempt."""
        ...

    def on_updated(self, controller: ICModelController, updates: dict[str, dict[str, Any]]) -> None:
        """Called when model is updated (only for ICModelController)."""
        ...


class ICConnectionHandler:
    """Manages automatic reconnection with exponential backoff.

    This handler wraps a controller and provides automatic reconnection
    with exponential backoff, circuit breaker pattern, and debounced
    disconnect notifications.

    Example:
        model = PoolModel()
        controller = ICModelController("192.168.1.100", model)
        handler = ICConnectionHandler(controller)

        # Override callbacks
        handler.on_started = lambda ctrl: print("Connected!")
        handler.on_disconnected = lambda ctrl, exc: print(f"Disconnected: {exc}")

        await handler.start()
    """

    def __init__(
        self,
        controller: ICBaseController,
        time_between_reconnects: int = DEFAULT_RECONNECT_DELAY,
        disconnect_debounce_time: int = DEFAULT_DISCONNECT_DEBOUNCE,
    ) -> None:
        """Initialize the handler.

        Args:
            controller: Controller to manage
            time_between_reconnects: Initial reconnect delay (seconds)
            disconnect_debounce_time: Grace period before disconnect notification
        """
        self._controller = controller
        self._time_between_reconnects = time_between_reconnects
        self._disconnect_debounce_time = disconnect_debounce_time

        self._starter_task: asyncio.Task[None] | None = None
        self._disconnect_debounce_task: asyncio.Task[None] | None = None
        self._stopped = False
        self._first_time = True
        self._is_connected = False

        # Circuit breaker
        self._failure_count = 0
        self._last_failure_time: float | None = None

        # Set callbacks on controller
        controller.set_disconnected_callback(self._on_disconnect)

        if isinstance(controller, ICModelController):
            controller.set_updated_callback(self._on_model_updated)

    def __repr__(self) -> str:
        return (
            f"ICConnectionHandler(controller={self._controller!r}, "
            f"connected={self._is_connected}, failures={self._failure_count})"
        )

    @property
    def controller(self) -> ICBaseController:
        """Return the managed controller."""
        return self._controller

    async def start(self) -> None:
        """Start the connection handler.

        This method waits for the first successful connection before returning.
        If the first connection attempt fails, the exception is raised.
        Subsequent reconnections happen automatically in the background.

        Raises:
            ICConnectionError: If the first connection attempt fails.
        """
        if not self._starter_task:
            # Create an event to signal first connection attempt complete
            first_attempt_done = asyncio.Event()
            first_attempt_error: Exception | None = None

            async def starter_with_signal() -> None:
                nonlocal first_attempt_error
                try:
                    await self._controller.start()
                    # Success on first attempt
                    self._failure_count = 0
                    self._last_failure_time = None
                    if self._first_time:
                        self.on_started(self._controller)
                        self._first_time = False
                    self._is_connected = True
                    if self._starter_task is asyncio.current_task():
                        self._starter_task = None
                except (ICTimeoutError, OSError, ICConnectionError, ICCommandError) as err:
                    first_attempt_error = err
                finally:
                    first_attempt_done.set()

                # If first attempt failed, continue with normal reconnection logic
                if first_attempt_error is not None:
                    await self._starter(initial_delay=self._time_between_reconnects)

            self._starter_task = asyncio.create_task(starter_with_signal())

            # Wait for first attempt to complete
            await first_attempt_done.wait()

            # If first attempt failed, raise the error
            if first_attempt_error is not None:
                raise first_attempt_error

    def stop(self) -> None:
        """Stop the handler and controller."""
        self._stopped = True
        if self._starter_task:
            self._starter_task.cancel()
            self._starter_task = None
        if self._disconnect_debounce_task:
            self._disconnect_debounce_task.cancel()
            self._disconnect_debounce_task = None
        # Fire and forget the async stop
        asyncio.create_task(self._stop_controller())

    async def _stop_controller(self) -> None:
        """Stop the controller asynchronously."""
        with contextlib.suppress(Exception):
            await self._controller.stop()

    async def _starter(self, initial_delay: int = 0) -> None:
        """Attempt to connect with exponential backoff."""
        delay = self._time_between_reconnects

        while not self._stopped:
            try:
                # Check circuit breaker reset
                if (
                    self._last_failure_time
                    and time.monotonic() - self._last_failure_time > CIRCUIT_BREAKER_RESET_TIME
                ):
                    self._failure_count = 0
                    self._last_failure_time = None

                # Circuit breaker open - pause
                if self._failure_count >= CIRCUIT_BREAKER_FAILURES:
                    _LOGGER.warning(
                        "Circuit breaker open - pausing %ds", CIRCUIT_BREAKER_RESET_TIME
                    )
                    await asyncio.sleep(CIRCUIT_BREAKER_RESET_TIME)
                    self._failure_count = 0

                if initial_delay:
                    self.on_retrying(initial_delay)
                    self._controller._metrics.reconnect_attempts += 1
                    await asyncio.sleep(initial_delay)
                    initial_delay = 0

                # Re-check after the sleeps above: stop() may have run while we
                # waited, and opening a fresh connection past that point would
                # leave a socket nothing ever closes.
                if self._stopped:
                    return

                await self._controller.start()

                # Success - reset circuit breaker
                self._failure_count = 0
                self._last_failure_time = None

                if self._disconnect_debounce_task:
                    self._disconnect_debounce_task.cancel()
                    self._disconnect_debounce_task = None

                if self._first_time:
                    self.on_started(self._controller)
                    self._first_time = False
                elif not self._is_connected:
                    self.on_reconnected(self._controller)

                self._is_connected = True
                # Only clear the reference if it points at THIS task; clearing
                # someone else's reference would let stop() miss it.
                if self._starter_task is asyncio.current_task():
                    self._starter_task = None
                return

            except (
                ICTimeoutError,
                TimeoutError,
                OSError,
                ICConnectionError,
                ICCommandError,
            ) as err:
                self._failure_count += 1
                self._last_failure_time = time.monotonic()
                self._controller._metrics.reconnect_attempts += 1

                _LOGGER.error(
                    "Connection failed: %s (failure %d/%d)",
                    err,
                    self._failure_count,
                    CIRCUIT_BREAKER_FAILURES,
                )
                self.on_retrying(delay)
                await asyncio.sleep(delay)
                delay = min(int(delay * 1.5), MAX_RECONNECT_DELAY)

    def _on_disconnect(self, controller: ICBaseController, exc: Exception | None) -> None:
        """Handle disconnection."""
        if self._stopped:
            return

        _LOGGER.warning("Disconnected from %s: %s", controller.host, exc)
        self._is_connected = False

        # Debounced disconnect notification
        if self._disconnect_debounce_task:
            self._disconnect_debounce_task.cancel()
        self._disconnect_debounce_task = asyncio.create_task(
            self._delayed_disconnect(controller, exc)
        )

        # Start reconnection - unless one is already in flight (multiple
        # disconnect paths can fire for the same dead connection)
        if not self._starter_task or self._starter_task.done():
            self._starter_task = asyncio.create_task(self._starter(self._time_between_reconnects))

    async def _delayed_disconnect(
        self, controller: ICBaseController, exc: Exception | None
    ) -> None:
        """Notify about disconnection after debounce period."""
        try:
            await asyncio.sleep(self._disconnect_debounce_time)
            if not self._is_connected:
                self.on_disconnected(controller, exc)
        except asyncio.CancelledError:
            pass

    def _on_model_updated(
        self, controller: ICModelController, updates: dict[str, dict[str, Any]]
    ) -> None:
        """Internal callback that forwards to user callback."""
        self.on_updated(controller, updates)

    # Override these methods or assign callables to handle events
    def on_started(self, controller: ICBaseController) -> None:
        """Called on initial connection. Override or replace to handle."""

    def on_reconnected(self, controller: ICBaseController) -> None:
        """Called on reconnection after disconnect. Override or replace to handle."""

    def on_disconnected(self, controller: ICBaseController, exc: Exception | None) -> None:
        """Called after debounce period if still disconnected. Override or replace to handle."""

    def on_retrying(self, delay: int) -> None:
        """Called before retry attempt. Override or replace to handle."""
        _LOGGER.info("Retrying in %ds", delay)

    def on_updated(self, controller: ICModelController, updates: dict[str, dict[str, Any]]) -> None:
        """Called when model is updated. Override or replace to handle."""
