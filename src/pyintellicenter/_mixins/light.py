"""Light helpers for :class:`ICModelController` (Home Assistant light entities).

Provides accessors for light circuits and color-capable lights, plus helpers to
read and set light effects (IntelliBrite, MagicStream, etc.).
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from ..attributes import ACT_ATTR, LIGHT_EFFECTS, USE_ATTR
from ._base import _MixinBase

if TYPE_CHECKING:
    from ..model import PoolObject


class _LightMixin(_MixinBase):
    """Light convenience methods for ``ICModelController``."""

    def get_lights(self, include_shows: bool = True) -> list[PoolObject]:
        """Get all light circuits.

        Args:
            include_shows: If True, include light show circuits (LITSHO)

        Returns:
            List of PoolObject for light circuits
        """
        lights = [obj for obj in self._model if obj.is_a_light]
        if include_shows:
            lights.extend(obj for obj in self._model if obj.is_a_light_show)
        return lights

    def get_color_lights(self) -> list[PoolObject]:
        """Get lights that support color effects (IntelliBrite, MagicStream, etc.).

        These lights can have their effect/color changed via set_light_effect().

        Returns:
            List of PoolObject for color-capable lights
        """
        return [obj for obj in self._model if obj.supports_color_effects]

    async def set_light_effect(self, objnam: str, effect: str) -> dict[str, Any]:
        """Set the color effect for a color-capable light.

        Note: IntelliCenter uses ACT (action) attribute to set effects,
        while USE attribute reflects the current state. The effect change
        propagates to USE after IntelliCenter processes the command.

        Args:
            objnam: Object name of the light
            effect: Effect code (e.g., "PARTY", "CARIB", "ROYAL")
                   Use LIGHT_EFFECTS.keys() for valid codes.

        Returns:
            Response dictionary

        Raises:
            ValueError: If effect code is invalid

        Example:
            await controller.set_light_effect("C0012", "PARTY")
        """
        if effect not in LIGHT_EFFECTS:
            valid = ", ".join(LIGHT_EFFECTS.keys())
            raise ValueError(f"Invalid effect '{effect}'. Valid effects: {valid}")
        return await self._queue_property_change(objnam, {ACT_ATTR: effect})

    def get_light_effect(self, objnam: str) -> str | None:
        """Get the current color effect for a light.

        Args:
            objnam: Object name of the light

        Returns:
            Effect code (e.g., "PARTY") or None if not set/not a color light
        """
        obj = self._model[objnam]
        return obj[USE_ATTR] if obj else None

    def get_light_effect_name(self, objnam: str) -> str | None:
        """Get the human-readable name of the current light effect.

        Args:
            objnam: Object name of the light

        Returns:
            Effect name (e.g., "Party Mode") or None
        """
        effect = self.get_light_effect(objnam)
        return LIGHT_EFFECTS.get(effect) if effect else None

    @staticmethod
    def get_available_light_effects() -> dict[str, str]:
        """Get all available light effect codes and their names.

        Returns:
            Dict mapping effect codes to human-readable names
        """
        return dict(LIGHT_EFFECTS)
