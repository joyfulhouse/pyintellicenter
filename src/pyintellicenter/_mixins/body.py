"""Body-of-water temperature helpers for :class:`ICModelController`.

Provides accessors for the system temperature unit and for a body's current
temperature, heating/cooling setpoints, heat mode, and active heating/cooling
state (used by Home Assistant climate/water-heater entities).
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from ..attributes import (
    COOL_ATTR,
    HEATER_ATTR,
    HITMP_ATTR,
    HTMODE_ATTR,
    LOTMP_ATTR,
    LSTTMP_ATTR,
    MODE_ATTR,
    NULL_OBJNAM,
    TEMP_ATTR,
    HeaterType,
)
from ._base import _MixinBase

if TYPE_CHECKING:
    from ..model import PoolObject


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
        heater = self.get_heater_for_body(body_objnam)
        if not heater:
            return False

        # Check if the heater's COOL attribute is ON
        return bool(heater[COOL_ATTR] == "ON")

    def get_body_last_temperature(self, body_objnam: str) -> int | None:
        """Get the last recorded water temperature for a body of water.

        Unlike :meth:`get_body_temperature`, which only reads a valid value
        while the body circuit is active, ``LSTTMP`` holds the most recently
        recorded temperature regardless of whether the body is currently on or
        off, making it a more reliable temperature source.

        Args:
            body_objnam: Object name of the body (pool or spa)

        Returns:
            Last recorded temperature as integer, or None if unavailable
        """
        return self._get_attr_as_int(body_objnam, LSTTMP_ATTR)

    def get_heater_for_body(self, body_objnam: str) -> PoolObject | None:
        """Get the heater object currently assigned to a body of water.

        Each body tracks its active heater via the ``HEATER`` attribute. This
        resolves that reference to the actual :class:`PoolObject`.

        Args:
            body_objnam: Object name of the body (pool or spa)

        Returns:
            The assigned heater :class:`PoolObject`, or None when the body has
            no heater assigned (the attribute is missing or set to the null
            object id) or the body does not exist
        """
        body = self._model[body_objnam]
        if not body:
            return None
        heater_objnam = body[HEATER_ATTR]
        if not heater_objnam or heater_objnam == NULL_OBJNAM:
            return None
        return self._model[heater_objnam]
