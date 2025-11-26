"""Model class for storing a Pentair system.

This module provides the data model classes for representing pool equipment
and their state. It's used by the controller to maintain a synchronized
view of the IntelliCenter system.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from .attributes import (
    ALL_ATTRIBUTES_BY_TYPE,
    CIRCUIT_TYPE,
    COLOR_EFFECT_SUBTYPES,
    FEATR_ATTR,
    LIGHT_SUBTYPES,
    OBJTYP_ATTR,
    PARENT_ATTR,
    PUMP_STATUS_OFF,
    PUMP_STATUS_ON,
    PUMP_TYPE,
    SNAME_ATTR,
    STATUS_ATTR,
    STATUS_OFF,
    STATUS_ON,
    SUBTYP_ATTR,
)

if TYPE_CHECKING:
    from collections.abc import Iterator, KeysView, ValuesView

    from .types import ObjectEntry

_LOGGER = logging.getLogger(__name__)


class PoolObject:
    """Representation of an object in the Pentair system.

    A PoolObject represents a single piece of equipment (pump, light, heater, etc.)
    with its type, subtype, and current attribute values.
    """

    __slots__ = ("_objnam", "_objtype", "_subtype", "_properties")

    def __init__(self, objnam: str, params: dict[str, Any]) -> None:
        """Initialize from object name and parameters.

        Args:
            objnam: The unique object identifier (e.g., "PUMP01", "LIGHT1")
            params: Dictionary of object attributes including OBJTYP and optionally SUBTYP
        """
        self._objnam = objnam
        self._objtype: str = params.pop(OBJTYP_ATTR)
        self._subtype: str | None = params.pop(SUBTYP_ATTR, None)
        self._properties: dict[str, Any] = params

    @property
    def objnam(self) -> str:
        """Return the id of the object (OBJNAM)."""
        return self._objnam

    @property
    def sname(self) -> str | None:
        """Return the friendly name (SNAME)."""
        return self._properties.get(SNAME_ATTR)

    @property
    def objtype(self) -> str:
        """Return the object type."""
        return self._objtype

    @property
    def subtype(self) -> str | None:
        """Return the object subtype."""
        return self._subtype

    @property
    def status(self) -> str | None:
        """Return the object status."""
        return self._properties.get(STATUS_ATTR)

    @property
    def off_status(self) -> str:
        """Return the value of an OFF status."""
        return PUMP_STATUS_OFF if self._objtype == PUMP_TYPE else STATUS_OFF

    @property
    def on_status(self) -> str:
        """Return the value of an ON status."""
        return PUMP_STATUS_ON if self._objtype == PUMP_TYPE else STATUS_ON

    @property
    def is_a_light(self) -> bool:
        """Return True if the object is a light."""
        return self._objtype == CIRCUIT_TYPE and self._subtype in LIGHT_SUBTYPES

    @property
    def supports_color_effects(self) -> bool:
        """Return True if object is a light that supports color effects."""
        return self.is_a_light and self._subtype in COLOR_EFFECT_SUBTYPES

    @property
    def is_a_light_show(self) -> bool:
        """Return True if the object is a light show."""
        return self._objtype == CIRCUIT_TYPE and self._subtype == "LITSHO"

    @property
    def is_featured(self) -> bool:
        """Return True if the object is Featured."""
        return self._properties.get(FEATR_ATTR) == "ON"

    def __getitem__(self, key: str) -> Any:
        """Return the value for attribute 'key'."""
        return self._properties.get(key)

    def __str__(self) -> str:
        """Return a friendly string representation."""
        parts = [self._objnam]
        if self._subtype:
            parts.append(f"({self._objtype}/{self._subtype}):")
        else:
            parts.append(f"({self._objtype}):")

        for key in sorted(self._properties):
            value = self._properties[key]
            if isinstance(value, list):
                value = "[" + ",".join(f"{{{v}}}" for v in value) + "]"
            parts.append(f"{key}: {value}")
        return " ".join(parts)

    def __repr__(self) -> str:
        """Return a detailed string representation for debugging."""
        return (
            f"PoolObject(objnam={self._objnam!r}, objtype={self._objtype!r}, "
            f"subtype={self._subtype!r}, properties={self._properties!r})"
        )

    @property
    def attribute_keys(self) -> KeysView[str]:
        """Return a view of attribute keys for this object."""
        return self._properties.keys()

    @property
    def properties(self) -> dict[str, Any]:
        """Return the properties of the object."""
        return self._properties

    def update(self, updates: dict[str, Any]) -> dict[str, Any]:
        """Update the object from a set of key/value pairs.

        Args:
            updates: Dictionary of attribute updates to apply

        Returns:
            Dictionary of attributes that actually changed
        """
        changed: dict[str, Any] = {}

        for key, value in updates.items():
            # Check if value is unchanged using single lookup
            current = self._properties.get(key)
            if current == value:
                continue

            # Handle type/subtype updates (rare but possible)
            if key == OBJTYP_ATTR:
                self._objtype = value
            elif key == SUBTYP_ATTR:
                self._subtype = value
            else:
                self._properties[key] = value
            changed[key] = value

        return changed


class PoolModel:
    """Representation of a subset of the underlying Pentair system.

    The PoolModel maintains a collection of PoolObjects and provides
    methods for querying and updating them. It filters objects based
    on an attribute map to only track relevant equipment types.
    """

    def __init__(
        self,
        attribute_map: dict[str, set[str]] | None = None,
    ) -> None:
        """Initialize the model.

        Args:
            attribute_map: Optional mapping of object types to their tracked attributes.
                         Defaults to ALL_ATTRIBUTES_BY_TYPE.
        """
        self._objects: dict[str, PoolObject] = {}
        self._attribute_map = attribute_map if attribute_map is not None else ALL_ATTRIBUTES_BY_TYPE

    @property
    def object_values(self) -> ValuesView[PoolObject]:
        """Return a view of all objects (no copy)."""
        return self._objects.values()

    @property
    def objects(self) -> dict[str, PoolObject]:
        """Return the dictionary of objects contained in the model."""
        return self._objects

    @property
    def num_objects(self) -> int:
        """Return the number of objects contained in the model."""
        return len(self._objects)

    def __iter__(self) -> Iterator[PoolObject]:
        """Allow iteration over all values."""
        return iter(self._objects.values())

    def __getitem__(self, key: str) -> PoolObject | None:
        """Return an object based on its objnam."""
        return self._objects.get(key)

    def __repr__(self) -> str:
        """Return a detailed string representation for debugging."""
        return (
            f"PoolModel(num_objects={self.num_objects}, types={list(self._attribute_map.keys())})"
        )

    def get_by_type(self, obj_type: str, subtype: str | None = None) -> list[PoolObject]:
        """Return all objects which match the type and optional subtype.

        Args:
            obj_type: The object type to filter by (e.g., 'BODY', 'PUMP')
            subtype: Optional subtype to further filter (e.g., 'SPA', 'POOL')

        Returns:
            List of matching PoolObjects

        Examples:
            get_by_type('BODY') will return all objects of type 'BODY'
            get_by_type('BODY', 'SPA') will only return the Spa
        """
        return [
            obj
            for obj in self._objects.values()
            if obj.objtype == obj_type and (subtype is None or obj.subtype == subtype)
        ]

    def get_children(self, pool_object: PoolObject) -> list[PoolObject]:
        """Return the children of a given object.

        Args:
            pool_object: The parent object

        Returns:
            List of child PoolObjects
        """
        parent_objnam = pool_object.objnam
        return [obj for obj in self._objects.values() if obj[PARENT_ATTR] == parent_objnam]

    def add_object(self, objnam: str, params: dict[str, Any]) -> PoolObject | None:
        """Update the model with a new object.

        If the object already exists, updates its attributes instead.
        Only adds objects whose type is in the attribute map.

        Args:
            objnam: The object identifier
            params: Dictionary of object attributes

        Returns:
            The created/updated PoolObject, or None if type not in attribute map
        """
        pool_obj = self._objects.get(objnam)

        if pool_obj is None:
            pool_obj = PoolObject(objnam, params)
            if pool_obj.objtype in self._attribute_map:
                self._objects[objnam] = pool_obj
            else:
                return None
        else:
            pool_obj.update(params)
        return pool_obj

    def add_objects(self, obj_list: list[ObjectEntry]) -> None:
        """Create or update from all the objects in the list.

        Args:
            obj_list: List of objects with 'objnam' and 'params' keys
        """
        for entry in obj_list:
            self.add_object(entry["objnam"], entry["params"])

    def attributes_to_track(self) -> list[dict[str, Any]]:
        """Return all the object/attributes we want to track.

        Returns:
            List of query items with 'objnam' and 'keys' for each object
        """
        query: list[dict[str, Any]] = []
        for pool_obj in self._objects.values():
            attributes = self._attribute_map.get(pool_obj.objtype)
            if attributes is None:
                # If we don't specify a set of attributes for this object type,
                # default to all known attributes for this type
                attributes = ALL_ATTRIBUTES_BY_TYPE.get(pool_obj.objtype)
            if attributes:
                query.append({"objnam": pool_obj.objnam, "keys": list(attributes)})
        return query

    def process_updates(self, updates: list[ObjectEntry]) -> dict[str, dict[str, Any]]:
        """Update the state of the objects in the model.

        Args:
            updates: List of updates with 'objnam' and 'params' keys

        Returns:
            Dictionary mapping objnam to their changed attributes
        """
        updated: dict[str, dict[str, Any]] = {}
        for update in updates:
            objnam = update["objnam"]
            pool_obj = self._objects.get(objnam)
            if pool_obj is not None:
                changed = pool_obj.update(update["params"])
                if changed:
                    updated[objnam] = changed
        return updated
