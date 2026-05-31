"""Sensor helpers for :class:`ICModelController`.

Provides accessors for temperature sensors (solar, air, pool water) and a
helper to read a sensor's current calibrated value.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from ..attributes import CALIB_ATTR, PROBE_ATTR, SENSE_TYPE, SOURCE_ATTR
from ._base import _MixinBase

if TYPE_CHECKING:
    from ..model import PoolObject


class _SensorMixin(_MixinBase):
    """Sensor convenience methods for ``ICModelController``."""

    def get_sensors_by_type(self, subtype: str) -> list[PoolObject]:
        """Get sensors of a specific type.

        Args:
            subtype: Sensor subtype ("SOLAR", "POOL", "AIR")

        Returns:
            List of PoolObject matching the subtype
        """
        return self._model.get_by_type(SENSE_TYPE, subtype)

    def get_solar_sensors(self) -> list[PoolObject]:
        """Get all solar temperature sensors.

        Returns:
            List of PoolObject for solar sensors
        """
        return self.get_sensors_by_type("SOLAR")

    def get_air_sensors(self) -> list[PoolObject]:
        """Get all air temperature sensors.

        Returns:
            List of PoolObject for air sensors
        """
        return self.get_sensors_by_type("AIR")

    def get_pool_temp_sensors(self) -> list[PoolObject]:
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
        return self._get_attr_as_int(sensor_objnam, SOURCE_ATTR)

    def get_sensor_probe_reading(self, sensor_objnam: str) -> int | None:
        """Get the raw, uncalibrated probe reading from a sensor.

        Each temperature sensor exposes two readings: SOURCE (the calibrated
        value, after the CALIB offset is applied) and PROBE (the raw value
        directly from the sensor hardware). Comparing the two reveals the
        calibration offset currently in effect (SOURCE - PROBE == CALIB).

        Args:
            sensor_objnam: Object name of the sensor

        Returns:
            Raw uncalibrated probe reading as integer, or None if unavailable
        """
        return self._get_attr_as_int(sensor_objnam, PROBE_ATTR)

    def get_sensor_calibration(self, sensor_objnam: str) -> int | None:
        """Get the calibration offset currently applied to a sensor.

        The CALIB attribute stores the offset (in the system's temperature
        units) IntelliCenter adds to the raw PROBE reading to produce the
        calibrated SOURCE reading: ``SOURCE = PROBE + CALIB``. A value of 0
        means no calibration is applied.

        Args:
            sensor_objnam: Object name of the sensor

        Returns:
            Calibration offset as integer (positive, negative, or zero),
            or None if unavailable
        """
        return self._get_attr_as_int(sensor_objnam, CALIB_ATTR)
