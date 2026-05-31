"""Body-of-water temperature helpers for :class:`ICModelController`.

Provides accessors for the system temperature unit and for a body's current
temperature, heating/cooling setpoints, heat mode, and active heating/cooling
state (used by Home Assistant climate/water-heater entities).
"""

from __future__ import annotations

from ..attributes import (
    HEATER_ATTR,
    HITMP_ATTR,
    HTMODE_ATTR,
    LOTMP_ATTR,
    MODE_ATTR,
    NULL_OBJNAM,
    TEMP_ATTR,
    HeaterType,
)
from ._base import _MixinBase


class _BodyMixin(_MixinBase):
    """Body temperature convenience methods for ``ICModelController``."""

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
        return self._get_attr_as_int(body_objnam, TEMP_ATTR)

    def get_body_setpoint(self, body_objnam: str) -> int | None:
        """Get the heating setpoint for a body.

        This is the temperature the system will heat UP to.
        Alias for get_body_heating_setpoint().

        Args:
            body_objnam: Object name of the body (pool or spa)

        Returns:
            Heating setpoint temperature as integer, or None if unavailable
        """
        return self._get_attr_as_int(body_objnam, LOTMP_ATTR)

    def get_body_heating_setpoint(self, body_objnam: str) -> int | None:
        """Get the heating setpoint for a body.

        This is the temperature the system will heat UP to (LOTMP attribute).
        For the cooling setpoint, use get_body_cooling_setpoint().

        Args:
            body_objnam: Object name of the body (pool or spa)

        Returns:
            Heating setpoint temperature as integer, or None if unavailable
        """
        return self._get_attr_as_int(body_objnam, LOTMP_ATTR)

    def get_body_cooling_setpoint(self, body_objnam: str) -> int | None:
        """Get the cooling setpoint for a body.

        This is the temperature the system will cool DOWN to (HITMP attribute).
        Only relevant for systems with heat pumps or chillers that support cooling.
        The cooling setpoint must be higher than the heat setpoint.

        Args:
            body_objnam: Object name of the body (pool or spa)

        Returns:
            Cooling setpoint temperature as integer, or None if unavailable
        """
        return self._get_attr_as_int(body_objnam, HITMP_ATTR)

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

    def is_body_cooling(self, body_objnam: str) -> bool:
        """Check if a body is actively cooling.

        This checks the heater's COOL attribute to determine if the system
        is currently in cooling mode. Only UltraTemp heat pumps support cooling.

        Args:
            body_objnam: Object name of the body (pool or spa)

        Returns:
            True if cooling is active
        """
        body = self._model[body_objnam]
        if not body:
            return False

        # Get the heater reference from the body
        heater_objnam = body[HEATER_ATTR]
        if not heater_objnam or heater_objnam == NULL_OBJNAM:
            return False

        # Look up the heater object
        heater = self._model[heater_objnam]
        if not heater:
            return False

        # Check if the heater's COOL attribute is ON
        return bool(heater["COOL"] == "ON")
