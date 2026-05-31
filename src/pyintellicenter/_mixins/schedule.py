"""Schedule helpers for :class:`ICModelController`."""

from __future__ import annotations

from typing import TYPE_CHECKING

from ..attributes import (
    CIRCUIT_ATTR,
    DAY_ATTR,
    NULL_OBJNAM,
    SCHED_TYPE,
    STATUS_ATTR,
    STATUS_ON,
    TIME_ATTR,
    TIMOUT_ATTR,
)
from ._base import _MixinBase

if TYPE_CHECKING:
    from ..model import PoolObject


class _ScheduleMixin(_MixinBase):
    """Schedule convenience methods for ``ICModelController``."""

    def get_schedules(self) -> list[PoolObject]:
        """Get all schedule objects."""
        return self._model.get_by_type(SCHED_TYPE)

    def is_schedule_enabled(self, sched_objnam: str) -> bool:
        """Check if a schedule is enabled (will run at its scheduled time).

        STATUS=ON means the schedule is enabled; this is distinct from whether
        the schedule is currently running (the ACT attribute).

        Args:
            sched_objnam: Object name of the schedule

        Returns:
            True if the schedule reports STATUS=ON, False otherwise (including
            when the schedule does not exist)
        """
        obj = self._model[sched_objnam]
        if not obj:
            return False
        return bool(obj[STATUS_ATTR] == STATUS_ON)

    def get_schedule_circuit(self, sched_objnam: str) -> str | None:
        """Get the object name of the circuit controlled by a schedule.

        Args:
            sched_objnam: Object name of the schedule

        Returns:
            Object name of the controlled circuit (e.g., "C0006"), or None if
            unavailable
        """
        obj = self._model[sched_objnam]
        if not obj:
            return None
        value = obj[CIRCUIT_ATTR]
        if not value or value == NULL_OBJNAM:
            return None
        return str(value)

    def get_schedule_start_time(self, sched_objnam: str) -> str | None:
        """Get the start time of a schedule.

        Returns the time in 'HH,MM,SS' 24-hour format (e.g., '21,00,00').

        Args:
            sched_objnam: Object name of the schedule

        Returns:
            Start time string, or None if unavailable
        """
        obj = self._model[sched_objnam]
        if not obj:
            return None
        value = obj[TIME_ATTR]
        return str(value) if value else None

    def get_schedule_stop_time(self, sched_objnam: str) -> str | None:
        """Get the stop time of a schedule.

        Returns the time in 'HH,MM,SS' 24-hour format (e.g., '09,00,00').

        Args:
            sched_objnam: Object name of the schedule

        Returns:
            Stop time string, or None if unavailable
        """
        obj = self._model[sched_objnam]
        if not obj:
            return None
        value = obj[TIMOUT_ATTR]
        return str(value) if value else None

    def get_schedule_days(self, sched_objnam: str) -> str | None:
        """Get the days of the week a schedule runs.

        Returns a string where each character is a day: M=Monday, T=Tuesday,
        W=Wednesday, R=Thursday, F=Friday, A=Saturday, U=Sunday. For example
        'MTWRFAU' runs every day and 'AU' runs weekends only.

        Args:
            sched_objnam: Object name of the schedule

        Returns:
            Day string (e.g., 'MTWRFAU'), or None if unavailable
        """
        obj = self._model[sched_objnam]
        if not obj:
            return None
        value = obj[DAY_ATTR]
        return str(value) if value else None
