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

from .attributes import (
    ALK_ATTR,
    BODY_TYPE,
    CALC_ATTR,
    CHEM_TYPE,
    CIRCUIT_TYPE,
    CYACID_ATTR,
    GPM_ATTR,
    HEATER_TYPE,
    HTMODE_ATTR,
    LIGHT_EFFECTS,
    LOTMP_ATTR,
    MODE_ATTR,
    OBJTYP_ATTR,
    ORPHI_ATTR,
    ORPLO_ATTR,
    ORPVAL_ATTR,
    PARENT_ATTR,
    PHHI_ATTR,
    PHLO_ATTR,
    PHVAL_ATTR,
    PROPNAME_ATTR,
    PUMP_STATUS_ON,
    PUMP_TYPE,
    PWR_ATTR,
    QUALTY_ATTR,
    RPM_ATTR,
    SALT_ATTR,
    SCHED_TYPE,
    SENSE_TYPE,
    SNAME_ATTR,
    SOURCE_ATTR,
    STATUS_ATTR,
    STATUS_OFF,
    STATUS_ON,
    SUBTYP_ATTR,
    SUPER_ATTR,
    SYSTEM_TYPE,
    TEMP_ATTR,
    USE_ATTR,
    VALVE_TYPE,
    VER_ATTR,
    HeaterType,
)
from .connection import DEFAULT_TCP_PORT, DEFAULT_WEBSOCKET_PORT, ICConnection, TransportType
from .exceptions import ICCommandError, ICConnectionError, ICResponseError

if TYPE_CHECKING:
    from collections.abc import Callable

    from .model import PoolModel
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
        # Create connection
        self._connection = ICConnection(
            self._host,
            self._port,
            keepalive_interval=self._keepalive_interval,
            transport=self._transport,
        )

        # Set disconnect callback
        self._connection.set_disconnect_callback(self._on_disconnect)

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

        Raises:
            ICConnectionError: If not connected
            ICCommandError: If command fails
        """
        if not self._connection or not self._connection.connected:
            raise ICConnectionError("Not connected")

        with _RequestContext(self._metrics):
            try:
                return await self._connection.send_request(cmd, **(extra or {}))
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


class ICModelController(ICBaseController):
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
        """Apply updates to the model."""
        updates = self._model.process_updates(changes_as_list)

        # Update ICSystemInfo if changed
        if self._system_info and self._system_info.objnam in updates:
            self._system_info.update(updates[self._system_info.objnam])

        # Notify callback
        if updates and self._updated_callback:
            self._updated_callback(self, updates)

        return updates

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
        """
        return await self.request_changes(objnam, {STATUS_ATTR: STATUS_ON if state else STATUS_OFF})

    async def set_multiple_circuit_states(self, objnams: list[str], state: bool) -> dict[str, Any]:
        """Set multiple circuits on or off simultaneously.

        This matches node-intellicenter's SetObjectStatus(array, boolean) functionality.

        Args:
            objnams: List of object names to control
            state: True for ON, False for OFF

        Returns:
            Response dictionary
        """
        status = STATUS_ON if state else STATUS_OFF
        object_list = [{"objnam": objnam, "params": {STATUS_ATTR: status}} for objnam in objnams]
        return await self.send_cmd("SETPARAMLIST", {"objectList": object_list})

    async def set_heat_mode(self, body_objnam: str, mode: HeaterType) -> dict[str, Any]:
        """Set the heat mode for a body of water.

        Args:
            body_objnam: Object name of the body (pool or spa)
            mode: HeaterType enum value

        Returns:
            Response dictionary

        Example:
            await controller.set_heat_mode("B1101", HeaterType.HEATER)
        """
        return await self.request_changes(body_objnam, {MODE_ATTR: str(mode.value)})

    async def set_setpoint(self, body_objnam: str, temperature: int) -> dict[str, Any]:
        """Set the temperature setpoint for a body of water.

        Args:
            body_objnam: Object name of the body (pool or spa)
            temperature: Target temperature (units match system config)

        Returns:
            Response dictionary
        """
        return await self.request_changes(body_objnam, {LOTMP_ATTR: str(temperature)})

    async def set_super_chlorinate(self, chem_objnam: str, enabled: bool) -> dict[str, Any]:
        """Enable or disable super chlorination (boost mode).

        Args:
            chem_objnam: Object name of the chemistry controller
            enabled: True to enable, False to disable

        Returns:
            Response dictionary
        """
        return await self.request_changes(
            chem_objnam, {SUPER_ATTR: STATUS_ON if enabled else STATUS_OFF}
        )

    def get_bodies(self) -> list[Any]:
        """Get all body objects (pools and spas)."""
        return self._model.get_by_type(BODY_TYPE)

    def get_circuits(self) -> list[Any]:
        """Get all circuit objects."""
        return self._model.get_by_type(CIRCUIT_TYPE)

    def get_heaters(self) -> list[Any]:
        """Get all heater objects."""
        return self._model.get_by_type(HEATER_TYPE)

    def get_schedules(self) -> list[Any]:
        """Get all schedule objects."""
        return self._model.get_by_type(SCHED_TYPE)

    def get_sensors(self) -> list[Any]:
        """Get all sensor objects."""
        return self._model.get_by_type(SENSE_TYPE)

    def get_pumps(self) -> list[Any]:
        """Get all pump objects."""
        return self._model.get_by_type(PUMP_TYPE)

    def get_chem_controllers(self) -> list[Any]:
        """Get all chemistry controller objects (IntelliChem, IntelliChlor)."""
        return self._model.get_by_type(CHEM_TYPE)

    def get_valves(self) -> list[Any]:
        """Get all valve objects."""
        return self._model.get_by_type(VALVE_TYPE)

    # =========================================================================
    # Light Helpers (for Home Assistant light entities)
    # =========================================================================

    def get_lights(self, include_shows: bool = True) -> list[Any]:
        """Get all light circuits.

        Args:
            include_shows: If True, include light show circuits (LITSHO)

        Returns:
            List of PoolObject for light circuits
        """
        lights = [obj for obj in self._model if obj.is_a_light]
        if include_shows:
            lights.extend(obj for obj in self._model if obj.is_a_light_show)
        return lights

    def get_color_lights(self) -> list[Any]:
        """Get lights that support color effects (IntelliBrite, MagicStream, etc.).

        These lights can have their effect/color changed via set_light_effect().

        Returns:
            List of PoolObject for color-capable lights
        """
        return [obj for obj in self._model if obj.supports_color_effects]

    async def set_light_effect(self, objnam: str, effect: str) -> dict[str, Any]:
        """Set the color effect for a color-capable light.

        Args:
            objnam: Object name of the light
            effect: Effect code (e.g., "PARTY", "CARIB", "ROYAL")
                   Use LIGHT_EFFECTS.keys() for valid codes.

        Returns:
            Response dictionary

        Raises:
            ValueError: If effect code is invalid

        Example:
            await controller.set_light_effect("C0012", "PARTY")
        """
        if effect not in LIGHT_EFFECTS:
            valid = ", ".join(LIGHT_EFFECTS.keys())
            raise ValueError(f"Invalid effect '{effect}'. Valid effects: {valid}")
        return await self.request_changes(objnam, {USE_ATTR: effect})

    def get_light_effect(self, objnam: str) -> str | None:
        """Get the current color effect for a light.

        Args:
            objnam: Object name of the light

        Returns:
            Effect code (e.g., "PARTY") or None if not set/not a color light
        """
        obj = self._model[objnam]
        return obj[USE_ATTR] if obj else None

    def get_light_effect_name(self, objnam: str) -> str | None:
        """Get the human-readable name of the current light effect.

        Args:
            objnam: Object name of the light

        Returns:
            Effect name (e.g., "Party Mode") or None
        """
        effect = self.get_light_effect(objnam)
        return LIGHT_EFFECTS.get(effect) if effect else None

    @staticmethod
    def get_available_light_effects() -> dict[str, str]:
        """Get all available light effect codes and their names.

        Returns:
            Dict mapping effect codes to human-readable names
        """
        return dict(LIGHT_EFFECTS)

    # =========================================================================
    # Temperature/Body Helpers (for Home Assistant climate entities)
    # =========================================================================

    def get_temperature_unit(self) -> str:
        """Get the temperature unit used by this system.

        Returns:
            "°C" for Celsius, "°F" for Fahrenheit
        """
        if self.system_info and self.system_info.uses_metric:
            return "°C"
        return "°F"

    def get_body_temperature(self, body_objnam: str) -> int | None:
        """Get the current water temperature for a body.

        Args:
            body_objnam: Object name of the body (pool or spa)

        Returns:
            Current temperature as integer, or None if unavailable
        """
        obj = self._model[body_objnam]
        if obj and obj[TEMP_ATTR]:
            try:
                return int(obj[TEMP_ATTR])
            except (ValueError, TypeError):
                return None
        return None

    def get_body_setpoint(self, body_objnam: str) -> int | None:
        """Get the temperature setpoint for a body.

        Args:
            body_objnam: Object name of the body (pool or spa)

        Returns:
            Setpoint temperature as integer, or None if unavailable
        """
        obj = self._model[body_objnam]
        if obj and obj[LOTMP_ATTR]:
            try:
                return int(obj[LOTMP_ATTR])
            except (ValueError, TypeError):
                return None
        return None

    def get_body_heat_mode(self, body_objnam: str) -> HeaterType | None:
        """Get the current heat mode for a body.

        Args:
            body_objnam: Object name of the body (pool or spa)

        Returns:
            HeaterType enum value, or None if unavailable
        """
        obj = self._model[body_objnam]
        if obj and obj[MODE_ATTR]:
            try:
                return HeaterType(int(obj[MODE_ATTR]))
            except (ValueError, TypeError):
                return None
        return None

    def is_body_heating(self, body_objnam: str) -> bool:
        """Check if a body is actively heating.

        Args:
            body_objnam: Object name of the body (pool or spa)

        Returns:
            True if heating is active
        """
        obj = self._model[body_objnam]
        if obj:
            htmode = obj[HTMODE_ATTR]
            return htmode is not None and htmode != "0"
        return False

    # =========================================================================
    # Chemistry Helpers (for Home Assistant sensor entities)
    # =========================================================================

    def get_chem_reading(self, chem_objnam: str, reading_type: str) -> float | int | None:
        """Get a chemistry reading from a chemistry controller.

        Args:
            chem_objnam: Object name of the chemistry controller
            reading_type: One of "pH", "ORP", "SALT", "ALK", "CYACID",
                         "CALC", "QUALITY"

        Returns:
            Reading value, or None if unavailable

        Example:
            ph = controller.get_chem_reading("CHEM1", "pH")
            salt = controller.get_chem_reading("CHEM1", "SALT")
        """
        obj = self._model[chem_objnam]
        if not obj:
            return None

        attr_map = {
            "pH": PHVAL_ATTR,
            "ORP": ORPVAL_ATTR,
            "SALT": SALT_ATTR,
            "ALK": ALK_ATTR,
            "CYACID": CYACID_ATTR,
            "CALC": CALC_ATTR,
            "QUALITY": QUALTY_ATTR,
        }

        attr = attr_map.get(reading_type.upper() if reading_type else "")
        if not attr:
            return None

        value = obj[attr]
        if value is None:
            return None

        try:
            # pH values are typically decimal, others are integers
            if reading_type.upper() == "PH":
                return float(value)
            return int(value)
        except (ValueError, TypeError):
            return None

    def get_chem_alerts(self, chem_objnam: str) -> list[str]:
        """Get active chemistry alerts for a controller.

        Args:
            chem_objnam: Object name of the chemistry controller

        Returns:
            List of active alert names (e.g., ["pH High", "ORP Low"])
        """
        obj = self._model[chem_objnam]
        if not obj:
            return []

        alerts = []
        alert_checks = [
            (PHHI_ATTR, "pH High"),
            (PHLO_ATTR, "pH Low"),
            (ORPHI_ATTR, "ORP High"),
            (ORPLO_ATTR, "ORP Low"),
        ]

        for attr, name in alert_checks:
            if obj[attr] == STATUS_ON:
                alerts.append(name)

        return alerts

    def has_chem_alert(self, chem_objnam: str) -> bool:
        """Check if any chemistry alert is active.

        Args:
            chem_objnam: Object name of the chemistry controller

        Returns:
            True if any alert is active
        """
        return len(self.get_chem_alerts(chem_objnam)) > 0

    # =========================================================================
    # Sensor Helpers (for Home Assistant sensor entities)
    # =========================================================================

    def get_sensors_by_type(self, subtype: str) -> list[Any]:
        """Get sensors of a specific type.

        Args:
            subtype: Sensor subtype ("SOLAR", "POOL", "AIR")

        Returns:
            List of PoolObject matching the subtype
        """
        return self._model.get_by_type(SENSE_TYPE, subtype)

    def get_solar_sensors(self) -> list[Any]:
        """Get all solar temperature sensors.

        Returns:
            List of PoolObject for solar sensors
        """
        return self.get_sensors_by_type("SOLAR")

    def get_air_sensors(self) -> list[Any]:
        """Get all air temperature sensors.

        Returns:
            List of PoolObject for air sensors
        """
        return self.get_sensors_by_type("AIR")

    def get_pool_temp_sensors(self) -> list[Any]:
        """Get all pool water temperature sensors.

        Returns:
            List of PoolObject for pool temp sensors
        """
        return self.get_sensors_by_type("POOL")

    def get_sensor_reading(self, sensor_objnam: str) -> int | None:
        """Get the current calibrated reading from a sensor.

        Args:
            sensor_objnam: Object name of the sensor

        Returns:
            Calibrated reading as integer, or None if unavailable
        """
        obj = self._model[sensor_objnam]
        if obj and obj[SOURCE_ATTR]:
            try:
                return int(obj[SOURCE_ATTR])
            except (ValueError, TypeError):
                return None
        return None

    # =========================================================================
    # Pump Helpers (for Home Assistant sensor/switch entities)
    # =========================================================================

    def is_pump_running(self, pump_objnam: str) -> bool:
        """Check if a pump is currently running.

        Note: Pumps use different status values than circuits.
        "10" = running, "4" = stopped.

        Args:
            pump_objnam: Object name of the pump

        Returns:
            True if pump is running
        """
        obj = self._model[pump_objnam]
        if obj:
            return bool(obj[STATUS_ATTR] == PUMP_STATUS_ON)
        return False

    def get_pump_rpm(self, pump_objnam: str) -> int | None:
        """Get current pump RPM.

        Args:
            pump_objnam: Object name of the pump

        Returns:
            Current RPM, or None if unavailable
        """
        obj = self._model[pump_objnam]
        if obj and obj[RPM_ATTR]:
            try:
                return int(obj[RPM_ATTR])
            except (ValueError, TypeError):
                return None
        return None

    def get_pump_gpm(self, pump_objnam: str) -> int | None:
        """Get current pump flow rate in gallons per minute.

        Args:
            pump_objnam: Object name of the pump

        Returns:
            Current GPM, or None if unavailable
        """
        obj = self._model[pump_objnam]
        if obj and obj[GPM_ATTR]:
            try:
                return int(obj[GPM_ATTR])
            except (ValueError, TypeError):
                return None
        return None

    def get_pump_watts(self, pump_objnam: str) -> int | None:
        """Get current pump power consumption in watts.

        Args:
            pump_objnam: Object name of the pump

        Returns:
            Current power in watts, or None if unavailable
        """
        obj = self._model[pump_objnam]
        if obj and obj[PWR_ATTR]:
            try:
                return int(obj[PWR_ATTR])
            except (ValueError, TypeError):
                return None
        return None

    def get_pump_metrics(self, pump_objnam: str) -> dict[str, int | None]:
        """Get all pump metrics in a single call.

        Args:
            pump_objnam: Object name of the pump

        Returns:
            Dict with keys: rpm, gpm, watts (values may be None)
        """
        return {
            "rpm": self.get_pump_rpm(pump_objnam),
            "gpm": self.get_pump_gpm(pump_objnam),
            "watts": self.get_pump_watts(pump_objnam),
        }

    # =========================================================================
    # Entity Discovery Helpers (for Home Assistant integration setup)
    # =========================================================================

    def get_all_entities(self) -> dict[str, list[Any]]:
        """Get all entities grouped by type for Home Assistant discovery.

        Returns:
            Dict with keys: bodies, circuits, lights, color_lights, pumps,
            heaters, sensors, chem_controllers, schedules, valves
        """
        return {
            "bodies": self.get_bodies(),
            "circuits": [c for c in self.get_circuits() if not c.is_a_light],
            "lights": self.get_lights(include_shows=False),
            "light_shows": [obj for obj in self._model if obj.is_a_light_show],
            "color_lights": self.get_color_lights(),
            "pumps": self.get_pumps(),
            "heaters": self.get_heaters(),
            "sensors": self.get_sensors(),
            "chem_controllers": self.get_chem_controllers(),
            "schedules": self.get_schedules(),
            "valves": self.get_valves(),
        }

    def get_featured_entities(self) -> list[Any]:
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
                    self._starter_task = None
                except (TimeoutError, OSError, ICConnectionError, ICCommandError) as err:
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
                self._starter_task = None
                return

            except (TimeoutError, OSError, ICConnectionError, ICCommandError) as err:
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

        # Start reconnection
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
