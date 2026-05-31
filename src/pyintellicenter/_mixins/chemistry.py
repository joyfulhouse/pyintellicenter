"""Chemistry controller helpers for :class:`ICModelController`.

Provides setters and getters for IntelliChem and IntelliChlor controllers,
including pH/ORP setpoints, chlorinator output, water-balance configuration
values (alkalinity, calcium hardness, cyanuric acid), readings, and alerts.
"""

from __future__ import annotations

from typing import Any

from ..attributes import (
    ALK_ATTR,
    CALC_ATTR,
    CYACID_ATTR,
    ORPHI_ATTR,
    ORPLO_ATTR,
    ORPSET_ATTR,
    ORPVAL_ATTR,
    PHHI_ATTR,
    PHLO_ATTR,
    PHSET_ATTR,
    PHVAL_ATTR,
    PRIM_ATTR,
    QUALTY_ATTR,
    SALT_ATTR,
    SEC_ATTR,
    STATUS_OFF,
    STATUS_ON,
    SUPER_ATTR,
)
from ._base import _MixinBase

# Validation range constants for chemistry controllers
PH_MIN = 6.0
PH_MAX = 8.5
PH_STEP = 0.1

ORP_MIN = 200  # mV
ORP_MAX = 900  # mV

CHLORINATOR_PERCENT_MIN = 0
CHLORINATOR_PERCENT_MAX = 100

ALKALINITY_MIN = 0  # ppm
ALKALINITY_MAX = 800  # ppm

CALCIUM_HARDNESS_MIN = 0  # ppm
CALCIUM_HARDNESS_MAX = 800  # ppm

CYANURIC_ACID_MIN = 0  # ppm
CYANURIC_ACID_MAX = 200  # ppm


class _ChemistryMixin(_MixinBase):
    """Chemistry controller convenience methods for ``ICModelController``."""

    async def set_super_chlorinate(self, chem_objnam: str, enabled: bool) -> dict[str, Any]:
        """Enable or disable super chlorination (boost mode).

        Args:
            chem_objnam: Object name of the chemistry controller
            enabled: True to enable, False to disable

        Returns:
            Response dictionary
        """
        return await self._queue_property_change(
            chem_objnam, {SUPER_ATTR: STATUS_ON if enabled else STATUS_OFF}
        )

    async def set_ph_setpoint(self, chem_objnam: str, value: float) -> dict[str, Any]:
        """Set the pH setpoint for an IntelliChem controller.

        Args:
            chem_objnam: Object name of the chemistry controller
            value: Target pH value (PH_MIN-PH_MAX, in PH_STEP increments)

        Returns:
            Response dictionary

        Raises:
            ValueError: If value is outside valid range or not a 0.1 increment

        Example:
            await controller.set_ph_setpoint("CHEM1", 7.4)
        """
        if not PH_MIN <= value <= PH_MAX:
            raise ValueError(f"pH setpoint {value} outside valid range ({PH_MIN}-{PH_MAX})")

        # IntelliChem only accepts pH values in PH_STEP increments
        # Check if value is a valid step (e.g., 7.0, 7.1, 7.2, not 7.05 or 7.15)
        rounded = round(value, 1)
        if abs(value - rounded) > 0.001:
            raise ValueError(
                f"pH setpoint {value} must be in {PH_STEP} increments (e.g., 7.0, 7.1, 7.2)"
            )

        return await self._queue_property_change(chem_objnam, {PHSET_ATTR: str(rounded)})

    async def set_orp_setpoint(self, chem_objnam: str, value: int) -> dict[str, Any]:
        """Set the ORP setpoint for an IntelliChem controller.

        ORP (Oxidation Reduction Potential) measures sanitizer effectiveness.

        Args:
            chem_objnam: Object name of the chemistry controller
            value: Target ORP in millivolts (typically 400-800 mV)

        Returns:
            Response dictionary

        Raises:
            ValueError: If value is outside valid range

        Example:
            await controller.set_orp_setpoint("CHEM1", 700)
        """
        if not ORP_MIN <= value <= ORP_MAX:
            raise ValueError(f"ORP setpoint {value} outside valid range ({ORP_MIN}-{ORP_MAX} mV)")
        return await self._queue_property_change(chem_objnam, {ORPSET_ATTR: str(value)})

    async def set_chlorinator_output(
        self, chem_objnam: str, primary_percent: int, secondary_percent: int | None = None
    ) -> dict[str, Any]:
        """Set the chlorinator output percentage for an IntelliChlor.

        Args:
            chem_objnam: Object name of the chemistry controller (IntelliChlor)
            primary_percent: Output percentage for primary body (0-100)
            secondary_percent: Output percentage for secondary body (0-100),
                             or None to leave unchanged

        Returns:
            Response dictionary

        Raises:
            ValueError: If percentage is outside valid range

        Example:
            # Set pool to 50%, spa to 100%
            await controller.set_chlorinator_output("CHEM1", 50, 100)
            # Set pool only
            await controller.set_chlorinator_output("CHEM1", 75)
        """
        if not CHLORINATOR_PERCENT_MIN <= primary_percent <= CHLORINATOR_PERCENT_MAX:
            raise ValueError(
                f"Primary percentage {primary_percent} outside valid range "
                f"({CHLORINATOR_PERCENT_MIN}-{CHLORINATOR_PERCENT_MAX})"
            )

        changes: dict[str, str] = {PRIM_ATTR: str(primary_percent)}

        if secondary_percent is not None:
            if not CHLORINATOR_PERCENT_MIN <= secondary_percent <= CHLORINATOR_PERCENT_MAX:
                raise ValueError(
                    f"Secondary percentage {secondary_percent} outside valid range "
                    f"({CHLORINATOR_PERCENT_MIN}-{CHLORINATOR_PERCENT_MAX})"
                )
            changes[SEC_ATTR] = str(secondary_percent)

        return await self._queue_property_change(chem_objnam, changes)

    async def set_alkalinity(self, chem_objnam: str, value: int) -> dict[str, Any]:
        """Set the alkalinity value for an IntelliChem controller.

        Alkalinity is a user-entered configuration value used to calculate
        the Saturation Index (water quality). It is NOT a sensor reading.

        Args:
            chem_objnam: Object name of the chemistry controller
            value: Alkalinity in ppm (typically 80-120 ppm for pools)

        Returns:
            Response dictionary

        Raises:
            ValueError: If value is outside valid range

        Example:
            await controller.set_alkalinity("CHEM1", 100)
        """
        if not ALKALINITY_MIN <= value <= ALKALINITY_MAX:
            raise ValueError(
                f"Alkalinity {value} outside valid range ({ALKALINITY_MIN}-{ALKALINITY_MAX} ppm)"
            )
        return await self._queue_property_change(chem_objnam, {ALK_ATTR: str(value)})

    async def set_calcium_hardness(self, chem_objnam: str, value: int) -> dict[str, Any]:
        """Set the calcium hardness value for an IntelliChem controller.

        Calcium hardness is a user-entered configuration value used to calculate
        the Saturation Index (water quality). It is NOT a sensor reading.

        Args:
            chem_objnam: Object name of the chemistry controller
            value: Calcium hardness in ppm (typically 200-400 ppm for pools)

        Returns:
            Response dictionary

        Raises:
            ValueError: If value is outside valid range

        Example:
            await controller.set_calcium_hardness("CHEM1", 300)
        """
        if not CALCIUM_HARDNESS_MIN <= value <= CALCIUM_HARDNESS_MAX:
            raise ValueError(
                f"Calcium hardness {value} outside valid range "
                f"({CALCIUM_HARDNESS_MIN}-{CALCIUM_HARDNESS_MAX} ppm)"
            )
        return await self._queue_property_change(chem_objnam, {CALC_ATTR: str(value)})

    async def set_cyanuric_acid(self, chem_objnam: str, value: int) -> dict[str, Any]:
        """Set the cyanuric acid (stabilizer) value for an IntelliChem controller.

        Cyanuric acid is a user-entered configuration value used to calculate
        the Saturation Index (water quality). It is NOT a sensor reading.

        Args:
            chem_objnam: Object name of the chemistry controller
            value: Cyanuric acid in ppm (typically 30-50 ppm for pools)

        Returns:
            Response dictionary

        Raises:
            ValueError: If value is outside valid range

        Example:
            await controller.set_cyanuric_acid("CHEM1", 40)
        """
        if not CYANURIC_ACID_MIN <= value <= CYANURIC_ACID_MAX:
            raise ValueError(
                f"Cyanuric acid {value} outside valid range "
                f"({CYANURIC_ACID_MIN}-{CYANURIC_ACID_MAX} ppm)"
            )
        return await self._queue_property_change(chem_objnam, {CYACID_ATTR: str(value)})

    def get_ph_setpoint(self, chem_objnam: str) -> float | None:
        """Get the current pH setpoint for a chemistry controller.

        Args:
            chem_objnam: Object name of the chemistry controller

        Returns:
            pH setpoint value, or None if unavailable
        """
        return self._get_attr_as_float(chem_objnam, PHSET_ATTR)

    def get_orp_setpoint(self, chem_objnam: str) -> int | None:
        """Get the current ORP setpoint for a chemistry controller.

        Args:
            chem_objnam: Object name of the chemistry controller

        Returns:
            ORP setpoint in mV, or None if unavailable
        """
        return self._get_attr_as_int(chem_objnam, ORPSET_ATTR)

    def get_chlorinator_output(self, chem_objnam: str) -> dict[str, int | None]:
        """Get the current chlorinator output percentages.

        Args:
            chem_objnam: Object name of the chemistry controller (IntelliChlor)

        Returns:
            Dict with 'primary' and 'secondary' output percentages
        """
        return {
            "primary": self._get_attr_as_int(chem_objnam, PRIM_ATTR),
            "secondary": self._get_attr_as_int(chem_objnam, SEC_ATTR),
        }

    def get_alkalinity(self, chem_objnam: str) -> int | None:
        """Get the alkalinity configuration value for a chemistry controller.

        Alkalinity is a user-entered configuration value (not a sensor reading).

        Args:
            chem_objnam: Object name of the chemistry controller

        Returns:
            Alkalinity in ppm, or None if unavailable
        """
        return self._get_attr_as_int(chem_objnam, ALK_ATTR)

    def get_calcium_hardness(self, chem_objnam: str) -> int | None:
        """Get the calcium hardness configuration value for a chemistry controller.

        Calcium hardness is a user-entered configuration value (not a sensor reading).

        Args:
            chem_objnam: Object name of the chemistry controller

        Returns:
            Calcium hardness in ppm, or None if unavailable
        """
        return self._get_attr_as_int(chem_objnam, CALC_ATTR)

    def get_cyanuric_acid(self, chem_objnam: str) -> int | None:
        """Get the cyanuric acid configuration value for a chemistry controller.

        Cyanuric acid is a user-entered configuration value (not a sensor reading).

        Args:
            chem_objnam: Object name of the chemistry controller

        Returns:
            Cyanuric acid in ppm, or None if unavailable
        """
        return self._get_attr_as_int(chem_objnam, CYACID_ATTR)

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
