"""Schedule helpers for :class:`ICModelController`."""

from __future__ import annotations

from typing import TYPE_CHECKING

from ..attributes import SCHED_TYPE
from ._base import _MixinBase

if TYPE_CHECKING:
    from ..model import PoolObject


class _ScheduleMixin(_MixinBase):
    """Schedule convenience methods for ``ICModelController``."""

    def get_schedules(self) -> list[PoolObject]:
        """Get all schedule objects."""
        return self._model.get_by_type(SCHED_TYPE)
