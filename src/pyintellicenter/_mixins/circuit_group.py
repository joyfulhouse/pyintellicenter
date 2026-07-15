"""Circuit group helpers for :class:`ICModelController`.

Circuit groups allow multiple circuits to be controlled together. Groups that
contain color-capable lights can have light effects applied to the whole group.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from ..attributes import (
    CIRCGRP_TYPE,
    CIRCUIT_ATTR,
    CIRCUIT_TYPE,
    LISTORD_ATTR,
    PARENT_ATTR,
)
from ._base import _MixinBase

if TYPE_CHECKING:
    from ..model import PoolObject


_GROUP_PARENT_SUBTYPES = frozenset({"CIRCGRP", "LITSHO"})


def _is_group_parent(obj: PoolObject) -> bool:
    """Return whether an object has a supported circuit-group parent shape."""
    return obj.objtype == CIRCUIT_TYPE and obj.subtype in _GROUP_PARENT_SUBTYPES


def _member_order(member: PoolObject) -> tuple[int, int, str]:
    """Sort valid nonnegative list orders before a deterministic malformed tail."""
    value = member[LISTORD_ATTR]
    try:
        order = int(value)
    except (TypeError, ValueError):
        return (1, 0, member.objnam)
    if order < 0:
        return (1, 0, member.objnam)
    return (0, order, member.objnam)


class _CircuitGroupMixin(_MixinBase):
    """Circuit group convenience methods for ``ICModelController``."""

    def get_circuit_groups(self) -> list[PoolObject]:
        """Get all circuit objects that act as group parents.

        ``CIRCGRP`` objects are membership rows and are not returned here.

        Returns:
            List of circuit-group parent objects
        """
        return [obj for obj in self._model if _is_group_parent(obj)]

    def get_circuit_group_members(self, parent_objnam: str) -> list[PoolObject]:
        """Get the ordered membership rows for a circuit-group parent.

        Args:
            parent_objnam: Object name of the circuit-group parent

        Returns:
            Membership rows sorted by valid LISTORD, then object name
        """
        return sorted(
            (
                obj
                for obj in self._model.get_by_type(CIRCGRP_TYPE)
                if obj[PARENT_ATTR] == parent_objnam
            ),
            key=_member_order,
        )

    def get_circuits_in_group(self, group_or_row_objnam: str) -> list[PoolObject]:
        """Get the resolved circuits for a parent or membership row.

        A real membership row resolves all ordered siblings through its parent.
        For compatibility, a standalone legacy row can directly list one or
        more circuit object names.

        Args:
            group_or_row_objnam: Object name of a group parent or membership row

        Returns:
            Existing circuit references in deterministic membership order
        """
        obj = self._model[group_or_row_objnam]
        if not obj:
            return []

        parent: PoolObject | None
        if _is_group_parent(obj):
            parent = obj
        elif obj.objtype == CIRCGRP_TYPE:
            if PARENT_ATTR not in obj.attribute_keys:
                return self._get_legacy_circuits_in_group(obj)

            parent_ref = obj[PARENT_ATTR]
            if not isinstance(parent_ref, str) or not parent_ref:
                return []
            parent = self._model[parent_ref]
            if not parent or not _is_group_parent(parent):
                return []
        else:
            return []

        circuits: list[PoolObject] = []
        for member in self.get_circuit_group_members(parent.objnam):
            circuit_ref = member[CIRCUIT_ATTR]
            if not isinstance(circuit_ref, str) or not circuit_ref:
                continue
            if any(character.isspace() for character in circuit_ref):
                continue
            circuit = self._model[circuit_ref]
            if circuit:
                circuits.append(circuit)
        return circuits

    def _get_legacy_circuits_in_group(self, row: PoolObject) -> list[PoolObject]:
        """Resolve an exact legacy standalone membership-row fixture."""
        circuit_ref = row[CIRCUIT_ATTR]
        if not isinstance(circuit_ref, str):
            return []

        circuits: list[PoolObject] = []
        for objnam in circuit_ref.split():
            circuit = self._model[objnam]
            if circuit:
                circuits.append(circuit)
        return circuits

    def circuit_group_has_color_lights(self, parent_objnam: str) -> bool:
        """Check if a circuit group contains any color-capable lights.

        Circuit groups that contain IntelliBrite, MagicStream, or other
        color lights can have light effects applied to the entire group.

        Args:
            parent_objnam: Object name of the circuit-group parent

        Returns:
            True if the group contains at least one color light
        """
        circuits = self.get_circuits_in_group(parent_objnam)
        return any(circuit.supports_color_effects for circuit in circuits)

    def get_color_light_groups(self) -> list[PoolObject]:
        """Get real circuit-group parents that contain color-capable lights.

        These groups can have light effects applied via set_light_effect().

        Returns:
            List of PoolObject for circuit groups with color lights
        """
        return [
            group
            for group in self.get_circuit_groups()
            if self.circuit_group_has_color_lights(group.objnam)
        ]
