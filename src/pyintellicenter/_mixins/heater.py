"""Heater and setpoint helpers for :class:`ICModelController`.

Provides the setters that drive a body of water's heat mode and heating/cooling
setpoints (used by Home Assistant climate/water-heater entities), plus a
predicate that reports whether any heater attached to a body supports cooling.
The setters route through the controller's request-coalescing engine so rapid
successive calls are batched into a single command.
"""

from __future__ import annotations

import logging
from typing import Any

from ..attributes import (
    BODY_ATTR,
    HEATER_TYPE,
    HITMP_ATTR,
    LOTMP_ATTR,
    MODE_ATTR,
    READY_ATTR,
    STATUS_ON,
    HeaterType,
)
from ._base import _MixinBase

_LOGGER = logging.getLogger(__name__)


class _HeaterMixin(_MixinBase):
    """Heater/setpoint convenience methods for ``ICModelController``."""

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
        return await self._queue_property_change(body_objnam, {MODE_ATTR: str(mode.value)})

    async def set_setpoint(self, body_objnam: str, temperature: int) -> dict[str, Any]:
        """Set the heating setpoint for a body of water.

        This is the temperature the system will heat UP to.
        Alias for set_heating_setpoint().

        Args:
            body_objnam: Object name of the body (pool or spa)
            temperature: Target heating temperature (units match system config)

        Returns:
            Response dictionary
        """
        return await self._queue_property_change(body_objnam, {LOTMP_ATTR: str(temperature)})

    async def set_heating_setpoint(self, body_objnam: str, temperature: int) -> dict[str, Any]:
        """Set the heating setpoint for a body of water.

        This is the temperature the system will heat UP to (LOTMP attribute).
        For the cooling setpoint, use set_cooling_setpoint().

        Args:
            body_objnam: Object name of the body (pool or spa)
            temperature: Target heating temperature (units match system config)

        Returns:
            Response dictionary

        Example:
            await controller.set_heating_setpoint("B1101", 84)
        """
        return await self._queue_property_change(body_objnam, {LOTMP_ATTR: str(temperature)})

    async def set_cooling_setpoint(self, body_objnam: str, temperature: int) -> dict[str, Any]:
        """Set the cooling setpoint for a body of water.

        This is the temperature the system will cool DOWN to (HITMP attribute).
        Only relevant for systems with heat pumps or chillers that support cooling.
        The cooling setpoint must be higher than the heat setpoint.

        Args:
            body_objnam: Object name of the body (pool or spa)
            temperature: Target cooling temperature (units match system config)

        Returns:
            Response dictionary

        Example:
            await controller.set_cooling_setpoint("B1101", 86)
        """
        return await self._queue_property_change(body_objnam, {HITMP_ATTR: str(temperature)})

    def body_supports_cooling(self, body_objnam: str) -> bool:
        """Check if a body has a heater that supports cooling.

        UltraTemp heat pumps (SUBTYP="ULTRA") support both heating and cooling.
        Gas heaters (SUBTYP="HEATER"), solar heaters (SUBTYP="SOLAR"), and
        generic heaters (SUBTYP="GENERIC") do not support cooling.

        This checks ALL heaters that support this body, not just the currently
        active one, so it returns True even if the system is currently off or
        using a different heater.

        Args:
            body_objnam: Object name of the body (pool or spa)

        Returns:
            True if any available heater for this body supports cooling

        Example:
            if controller.body_supports_cooling("B1101"):
                # Show both heating and cooling setpoints
                heat_sp = controller.get_body_heating_setpoint("B1101")
                cool_sp = controller.get_body_cooling_setpoint("B1101")
        """
        body = self._model[body_objnam]
        if not body:
            _LOGGER.warning("body_supports_cooling: body %s not found", body_objnam)
            return False

        # Check ALL heaters to see if any support this body AND can cool
        all_heaters = list(self._model.get_by_type(HEATER_TYPE))

        for heater in all_heaters:
            # Check if this heater supports this body
            supported_bodies = heater[BODY_ATTR]
            if supported_bodies:
                body_list = supported_bodies.split(" ")
                if body_objnam in body_list:
                    # Check if this heater supports cooling via either:
                    # 1. Subtype being ULTRA (UltraTemp heat pump)
                    # 2. Having a COOL attribute set to "ON"
                    has_ultra = heater.subtype == "ULTRA"
                    has_cool = heater["COOL"] == "ON"
                    if has_ultra or has_cool:
                        return True

        return False

    def is_heater_ready(self, heater_objnam: str) -> bool:
        """Check if a heater is ready to fire.

        A heater that is enabled (STATUS=ON) may not be ready if it is in a
        cool-down period, waiting for flow, or experiencing a fault. READY=ON
        indicates the heater hardware is able to begin heating when demanded by
        the body temperature setpoint.

        Args:
            heater_objnam: Object name of the heater (e.g., "H0001")

        Returns:
            True if the heater reports READY=ON, False otherwise (including when
            the heater or the READY attribute is missing)
        """
        obj = self._model[heater_objnam]
        if not obj:
            return False
        return bool(obj[READY_ATTR] == STATUS_ON)
