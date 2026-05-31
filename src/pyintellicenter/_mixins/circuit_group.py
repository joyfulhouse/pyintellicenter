"""Circuit group helpers for :class:`ICModelController`.

Circuit groups allow multiple circuits to be controlled together. Groups that
contain color-capable lights can have light effects applied to the whole group.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from ..attributes import CIRCGRP_TYPE, CIRCUIT_ATTR
from ._base import _MixinBase

if TYPE_CHECKING:
    from ..model import PoolObject


class _CircuitGroupMixin(_MixinBase):
    """Circuit group convenience methods for ``ICModelController``."""

    def get_circuit_groups(self) -> list[PoolObject]:
        """Get all circuit group objects.

        Circuit groups allow multiple circuits to be controlled together.
        Groups containing color lights can have light effects applied.

        Returns:
            List of PoolObject for circuit groups
        """
        return self._model.get_by_type(CIRCGRP_TYPE)

    def get_circuits_in_group(self, circgrp_objnam: str) -> list[PoolObject]:
        """Get all circuit objects that belong to a circuit group.

        Args:
            circgrp_objnam: Object name of the circuit group

        Returns:
            List of PoolObject for circuits in the group
        """
        obj = self._model[circgrp_objnam]
        if not obj or obj.objtype != CIRCGRP_TYPE:
            return []

        circuit_ref = obj[CIRCUIT_ATTR]
        if not circuit_ref:
            return []

        # CIRCUIT attribute can be a single objnam or space-separated list
        circuit_objnams = circuit_ref.split() if isinstance(circuit_ref, str) else [circuit_ref]

        circuits = []
        for objnam in circuit_objnams:
            circuit = self._model[objnam]
            if circuit:
                circuits.append(circuit)
        return circuits

    def circuit_group_has_color_lights(self, circgrp_objnam: str) -> bool:
        """Check if a circuit group contains any color-capable lights.

        Circuit groups that contain IntelliBrite, MagicStream, or other
        color lights can have light effects applied to the entire group.

        Args:
            circgrp_objnam: Object name of the circuit group

        Returns:
            True if the group contains at least one color light
        """
        circuits = self.get_circuits_in_group(circgrp_objnam)
        return any(circuit.supports_color_effects for circuit in circuits)

    def get_color_light_groups(self) -> list[PoolObject]:
        """Get circuit groups that contain color-capable lights.

        These groups can have light effects applied via set_light_effect().

        Returns:
            List of PoolObject for circuit groups with color lights
        """
        return [
            group
            for group in self.get_circuit_groups()
            if self.circuit_group_has_color_lights(group.objnam)
        ]
