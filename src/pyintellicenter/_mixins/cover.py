"""Cover (external instrument) helpers for :class:`ICModelController`.

Covers are external instruments (EXTINSTR) with ``SUBTYP=COVER`` and can be
turned on or off like a simple switch.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from ..attributes import EXTINSTR_TYPE, POSIT_ATTR, STATUS_ATTR, STATUS_OFF, STATUS_ON
from ._base import _MixinBase

if TYPE_CHECKING:
    from ..model import PoolObject


class _CoverMixin(_MixinBase):
    """Cover convenience methods for ``ICModelController``."""

    def get_covers(self) -> list[PoolObject]:
        """Get all cover objects (pool covers, spa covers).

        Covers are external instruments (EXTINSTR) with SUBTYP=COVER. This
        includes covers disabled in Settings > Covers (see is_cover_enabled());
        filter on that if you only want covers a caller should act on. They can
        be actuated via set_cover_state().

        Returns:
            List of PoolObject for covers
        """
        return [obj for obj in self._model.get_by_type(EXTINSTR_TYPE) if obj.subtype == "COVER"]

    async def set_cover_state(self, objnam: str, state: bool) -> dict[str, Any]:
        """Open or close a cover.

        Drives POSIT, the cover's physical position. STATUS is a separate
        attribute reflecting whether the cover is enabled in Settings >
        Covers, not its position - confirmed by capturing the panel's own
        SETPARAMLIST traffic when toggling that setting (it writes STATUS,
        never POSIT).

        Args:
            objnam: Object name of the cover (e.g., "CVR01")
            state: True to turn on, False to turn off

        Returns:
            Response dictionary from the controller
        """
        return await self._queue_property_change(
            objnam, {POSIT_ATTR: STATUS_ON if state else STATUS_OFF}
        )

    def is_cover_on(self, cover_objnam: str) -> bool:
        """Check if a cover is currently on (its raw POSIT reading).

        Args:
            cover_objnam: Object name of the cover

        Returns:
            True if the cover's POSIT is ON, False otherwise
        """
        obj = self._model[cover_objnam]
        if not obj:
            return False
        return bool(obj[POSIT_ATTR] == STATUS_ON)

    def is_cover_enabled(self, cover_objnam: str) -> bool:
        """Check if a cover is enabled in Settings > Covers.

        A cover disabled there still exists as a static EXTINSTR object and
        is returned by get_covers(), but its STATUS is not meaningful (the
        panel does not report a live position for it) and it should not be
        surfaced as controllable equipment.

        Args:
            cover_objnam: Object name of the cover

        Returns:
            True if the cover's STATUS is ON, False otherwise (including if
            the cover is unknown)
        """
        obj = self._model[cover_objnam]
        if not obj:
            return False
        return bool(obj[STATUS_ATTR] == STATUS_ON)
