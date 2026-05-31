"""Private domain mixins composed into :class:`ICModelController`.

These mixins group related convenience methods (chemistry, sensors, covers,
schedules, circuit groups, lights, pumps, bodies, system) to keep
``controller.py`` focused. They are an internal implementation detail and are
not part of the public API.
"""

from __future__ import annotations

from .body import _BodyMixin
from .chemistry import _ChemistryMixin
from .circuit_group import _CircuitGroupMixin
from .cover import _CoverMixin
from .light import _LightMixin
from .pump import _PumpMixin
from .schedule import _ScheduleMixin
from .sensor import _SensorMixin
from .system import _SystemMixin

__all__ = [
    "_BodyMixin",
    "_ChemistryMixin",
    "_CircuitGroupMixin",
    "_CoverMixin",
    "_LightMixin",
    "_PumpMixin",
    "_ScheduleMixin",
    "_SensorMixin",
    "_SystemMixin",
]
