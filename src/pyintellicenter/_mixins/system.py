"""System-level helpers for :class:`ICModelController`.

Provides vacation-mode control plus convenience accessors that return objects of
a given type (bodies, circuits, heaters, sensors, pumps, chemistry controllers,
valves) and a helper to read a valve's assignment/role.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from ..attributes import (
    ASSIGN_ATTR,
    BODY_TYPE,
    CHEM_TYPE,
    CIRCUIT_TYPE,
    HEATER_TYPE,
    PUMP_TYPE,
    SENSE_TYPE,
    STATUS_OFF,
    STATUS_ON,
    VACFLO_ATTR,
    VALVE_TYPE,
)
from ..exceptions import ICCommandError
from ._base import _MixinBase

if TYPE_CHECKING:
    from ..model import PoolObject


class _SystemMixin(_MixinBase):
    """System-level convenience methods for ``ICModelController``."""

    # =========================================================================
    # Vacation Mode Control
    # =========================================================================

    async def set_vacation_mode(self, enabled: bool) -> dict[str, Any]:
        """Enable or disable vacation mode.

        Vacation mode typically reduces pump runtime and adjusts
        schedules to minimize energy usage while maintaining water quality.

        Args:
            enabled: True to enable vacation mode, False to disable

        Returns:
            Response dictionary

        Example:
            await controller.set_vacation_mode(True)
        """
        if not self._system_info:
            raise ICCommandError("System info not available")

        return await self._queue_property_change(
            self._system_info.objnam, {VACFLO_ATTR: STATUS_ON if enabled else STATUS_OFF}
        )

    def is_vacation_mode(self) -> bool:
        """Check if vacation mode is currently enabled.

        Returns:
            True if vacation mode is enabled
        """
        if self._system_info:
            obj = self._model[self._system_info.objnam]
            if obj:
                return bool(obj[VACFLO_ATTR] == STATUS_ON)
        return False

    # =========================================================================
    # Object Type Accessors
    # =========================================================================

    def get_bodies(self) -> list[PoolObject]:
        """Get all body objects (pools and spas)."""
        return self._model.get_by_type(BODY_TYPE)

    def get_circuits(self) -> list[PoolObject]:
        """Get all circuit objects."""
        return self._model.get_by_type(CIRCUIT_TYPE)

    def get_heaters(self) -> list[PoolObject]:
        """Get all heater objects."""
        return self._model.get_by_type(HEATER_TYPE)

    def get_sensors(self) -> list[PoolObject]:
        """Get all sensor objects."""
        return self._model.get_by_type(SENSE_TYPE)

    def get_pumps(self) -> list[PoolObject]:
        """Get all pump objects."""
        return self._model.get_by_type(PUMP_TYPE)

    def get_chem_controllers(self) -> list[PoolObject]:
        """Get all chemistry controller objects (IntelliChem, IntelliChlor)."""
        return self._model.get_by_type(CHEM_TYPE)

    def get_valves(self) -> list[PoolObject]:
        """Get all valve objects."""
        return self._model.get_by_type(VALVE_TYPE)

    # =========================================================================
    # Valve Helpers
    # =========================================================================

    def get_valve_assignment(self, valve_objnam: str) -> str | None:
        """Get the assignment/role of a valve.

        Valves can be assigned to different roles in the pool system:
        - 'INTAKE': Draws water from a specific body (pool or spa)
        - 'RETURN': Returns water to a specific body (pool or spa)
        - 'NONE': Not assigned to intake/return (e.g., water feature valve)

        Args:
            valve_objnam: Object name of the valve

        Returns:
            Assignment string ('NONE', 'INTAKE', 'RETURN'), or None if unavailable
        """
        obj = self._model[valve_objnam]
        if obj:
            assign = obj[ASSIGN_ATTR]
            return str(assign) if assign is not None else None
        return None
