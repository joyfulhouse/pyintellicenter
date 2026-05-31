"""Cover (external instrument) helpers for :class:`ICModelController`.

Covers are external instruments (EXTINSTR) with ``SUBTYP=COVER`` and can be
turned on or off like a simple switch.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from ..attributes import EXTINSTR_TYPE, STATUS_ATTR, STATUS_OFF, STATUS_ON
from ._base import _MixinBase

if TYPE_CHECKING:
    from ..model import PoolObject


class _CoverMixin(_MixinBase):
    """Cover convenience methods for ``ICModelController``."""

    def get_covers(self) -> list[PoolObject]:
        """Get all cover objects (pool covers, spa covers).

        Covers are external instruments (EXTINSTR) with SUBTYP=COVER.
        They can be controlled via set_cover_state().

        Returns:
            List of PoolObject for covers
        """
        return [obj for obj in self._model.get_by_type(EXTINSTR_TYPE) if obj.subtype == "COVER"]

    async def set_cover_state(self, objnam: str, state: bool) -> dict[str, Any]:
        """Turn a cover on or off.

        Args:
            objnam: Object name of the cover (e.g., "CVR01")
            state: True to turn on, False to turn off

        Returns:
            Response dictionary from the controller
        """
        return await self._queue_property_change(
            objnam, {STATUS_ATTR: STATUS_ON if state else STATUS_OFF}
        )

    def is_cover_on(self, cover_objnam: str) -> bool:
        """Check if a cover is currently on.

        Args:
            cover_objnam: Object name of the cover

        Returns:
            True if the cover status is ON, False otherwise
        """
        obj = self._model[cover_objnam]
        if not obj:
            return False
        return obj.status == STATUS_ON
