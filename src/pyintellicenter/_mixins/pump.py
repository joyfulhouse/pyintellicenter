"""Pump helpers for :class:`ICModelController` (Home Assistant sensor/switch entities).

Provides accessors for pump run state and metrics (RPM, GPM, watts) as well as
pump-circuit helpers for variable speed/flow (VSF) pumps, including reading the
current speed, mode, and limits and refreshing the speed value after a mode
change.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from ..attributes import (
    GPM_ATTR,
    MAX_ATTR,
    MAXF_ATTR,
    MIN_ATTR,
    MINF_ATTR,
    PARENT_ATTR,
    PMPCIRC_TYPE,
    PUMP_STATUS_ON,
    PWR_ATTR,
    RPM_ATTR,
    SELECT_ATTR,
    SPEED_ATTR,
    STATUS_ATTR,
)
from ..exceptions import ICCommandError, ICConnectionError
from ._base import _MixinBase

if TYPE_CHECKING:
    from ..model import PoolObject


class _PumpMixin(_MixinBase):
    """Pump convenience methods for ``ICModelController``."""

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
        return self._get_attr_as_int(pump_objnam, RPM_ATTR)

    def get_pump_gpm(self, pump_objnam: str) -> int | None:
        """Get current pump flow rate in gallons per minute.

        Args:
            pump_objnam: Object name of the pump

        Returns:
            Current GPM, or None if unavailable
        """
        return self._get_attr_as_int(pump_objnam, GPM_ATTR)

    def get_pump_watts(self, pump_objnam: str) -> int | None:
        """Get current pump power consumption in watts.

        Args:
            pump_objnam: Object name of the pump

        Returns:
            Current power in watts, or None if unavailable
        """
        return self._get_attr_as_int(pump_objnam, PWR_ATTR)

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
    # Pump Circuit Helpers (for VSF pump speed/flow control)
    # =========================================================================

    def get_pump_circuits(self) -> list[PoolObject]:
        """Get all pump circuit objects.

        Pump circuits (PMPCIRC) represent per-circuit speed/flow settings
        for variable speed pumps. Each PMPCIRC links a pump to a circuit
        with a speed setpoint.

        Returns:
            List of PoolObject for pump circuits
        """
        return self._model.get_by_type(PMPCIRC_TYPE)

    def get_pump_circuit_speed(self, pmpcirc_objnam: str) -> int | None:
        """Get the speed for a pump circuit if valid for current mode.

        VSF (Variable Speed/Flow) pumps use a unified SPEED attribute that holds
        either RPM or GPM depending on the SELECT mode. When switching modes,
        IntelliCenter may send SELECT and SPEED updates in separate NotifyList
        messages, causing a brief period where the speed value is stale.

        This method returns None if the speed value is outside the valid range
        for the current mode, indicating the value is stale and should be shown
        as "unavailable" until the real value arrives from IntelliCenter.

        Example scenario this handles:
        - Pump is at 80 GPM
        - User switches mode to RPM
        - SELECT update arrives first, SPEED still shows 80
        - 80 is outside RPM range (450-3450), so return None
        - Entity shows "unavailable" until real RPM value arrives

        Args:
            pmpcirc_objnam: Object name of the pump circuit (e.g., "p0101")

        Returns:
            Speed value if within valid range for current mode, None otherwise
        """
        pmpcirc = self._model[pmpcirc_objnam]
        if not pmpcirc or pmpcirc.objtype != PMPCIRC_TYPE:
            return None

        speed = self._get_attr_as_int(pmpcirc_objnam, SPEED_ATTR)
        if speed is None:
            return None

        # Get parent pump for limits
        parent_objnam = pmpcirc[PARENT_ATTR]
        parent = self._model[parent_objnam] if parent_objnam else None
        if not parent:
            return speed  # No parent pump, can't determine limits

        # Determine limits based on current mode
        mode = pmpcirc[SELECT_ATTR] or "RPM"
        if mode == "GPM":
            min_val = self._get_attr_as_int(parent_objnam, MINF_ATTR) or 15
            max_val = self._get_attr_as_int(parent_objnam, MAXF_ATTR) or 140
        else:
            min_val = self._get_attr_as_int(parent_objnam, MIN_ATTR) or 450
            max_val = self._get_attr_as_int(parent_objnam, MAX_ATTR) or 3450

        # Return None if value is outside valid range (stale value from mode switch)
        if speed < min_val or speed > max_val:
            return None

        return speed

    async def refresh_pump_circuit_speed(self, pmpcirc_objnam: str) -> int | None:
        """Request fresh SPEED value from IntelliCenter for a pump circuit.

        Use this after changing the pump mode (SELECT attribute) to get the
        actual SPEED value that IntelliCenter calculated for the new mode.

        This also updates the internal model with the fresh value.

        Args:
            pmpcirc_objnam: Object name of the pump circuit (e.g., "p0101")

        Returns:
            Fresh speed value from IntelliCenter, or None if unavailable
        """
        try:
            response = await self.send_cmd(
                "GetParamList",
                {
                    "condition": "",
                    "objectList": [{"objnam": pmpcirc_objnam, "keys": [SPEED_ATTR]}],
                },
            )
        except (ICConnectionError, ICCommandError):
            return None

        if response and "objectList" in response:
            for obj in response["objectList"]:
                if obj.get("objnam") == pmpcirc_objnam:
                    params = obj.get("params", {})
                    speed_str = params.get(SPEED_ATTR)
                    if speed_str is not None:
                        # Update the model with fresh value
                        pmpcirc = self._model[pmpcirc_objnam]
                        if pmpcirc:
                            pmpcirc.update({SPEED_ATTR: speed_str})
                        try:
                            return int(speed_str)
                        except (ValueError, TypeError):
                            pass
        return None

    def get_pump_circuit_mode(self, pmpcirc_objnam: str) -> str | None:
        """Get the current mode (RPM or GPM) for a pump circuit.

        Args:
            pmpcirc_objnam: Object name of the pump circuit

        Returns:
            "RPM" or "GPM", or None if unavailable
        """
        pmpcirc = self._model[pmpcirc_objnam]
        if not pmpcirc:
            return None
        mode = pmpcirc[SELECT_ATTR]
        return str(mode) if mode else None

    def get_pump_circuit_limits(self, pmpcirc_objnam: str) -> dict[str, dict[str, int | None]]:
        """Get the speed/flow limits for a pump circuit from its parent pump.

        Returns limits for both RPM and GPM modes, useful for UI controls
        that need to know the valid range for each mode.

        Args:
            pmpcirc_objnam: Object name of the pump circuit

        Returns:
            Dict with 'rpm' and 'gpm' keys, each containing 'min' and 'max' values.
            Values are None if the pump doesn't support that mode.
        """
        pmpcirc = self._model[pmpcirc_objnam]
        if not pmpcirc:
            return {"rpm": {"min": None, "max": None}, "gpm": {"min": None, "max": None}}

        parent_objnam = pmpcirc[PARENT_ATTR]
        parent = self._model[parent_objnam] if parent_objnam else None
        if not parent:
            return {"rpm": {"min": None, "max": None}, "gpm": {"min": None, "max": None}}

        return {
            "rpm": {
                "min": self._get_attr_as_int(parent_objnam, MIN_ATTR),
                "max": self._get_attr_as_int(parent_objnam, MAX_ATTR),
            },
            "gpm": {
                "min": self._get_attr_as_int(parent_objnam, MINF_ATTR),
                "max": self._get_attr_as_int(parent_objnam, MAXF_ATTR),
            },
        }
