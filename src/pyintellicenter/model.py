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
    FEATR_ATTR,
    OBJTYP_ATTR,
    PARENT_ATTR,
    SNAME_ATTR,
    STATUS_ATTR,
    SUBTYP_ATTR,
)

if TYPE_CHECKING:
    from collections.abc import Iterator

_LOGGER = logging.getLogger(__name__)

# ---------------------------------------------------------------------------

# Light subtypes that represent illumination devices
LIGHT_SUBTYPES = frozenset(["LIGHT", "INTELLI", "GLOW", "GLOWT", "DIMMER", "MAGIC2"])

# Light subtypes that support color effects
COLOR_EFFECT_SUBTYPES = frozenset(["INTELLI", "MAGIC2", "GLOW"])


class PoolObject:
    """Representation of an object in the Pentair system.

    A PoolObject represents a single piece of equipment (pump, light, heater, etc.)
    with its type, subtype, and current attribute values.
    """

    def __init__(self, objnam: str, params: dict[str, Any]) -> None:
        """Initialize from object name and parameters.

        Args:
            objnam: The unique object identifier (e.g., "PUMP01", "LIGHT1")
            params: Dictionary of object attributes including OBJTYP and optionally SUBTYP
        """
        self._objnam = objnam
        self._objtyp: str = params.pop(OBJTYP_ATTR)
        self._subtyp: str | None = params.pop(SUBTYP_ATTR, None)
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
        return self._objtyp

    @property
    def subtype(self) -> str | None:
        """Return the object subtype."""
        return self._subtyp

    @property
    def status(self) -> str | None:
        """Return the object status."""
        return self._properties.get(STATUS_ATTR)

    @property
    def offStatus(self) -> str:
        """Return the value of an OFF status."""
        return "4" if self.objtype == "PUMP" else "OFF"

    @property
    def onStatus(self) -> str:
        """Return the value of an ON status."""
        return "10" if self.objtype == "PUMP" else "ON"

    @property
    def isALight(self) -> bool:
        """Return True if the object is a light."""
        return self.objtype == CIRCUIT_TYPE and self.subtype in LIGHT_SUBTYPES

    @property
    def supportColorEffects(self) -> bool:
        """Return True if object is a light that supports color effects."""
        return self.isALight and self.subtype in COLOR_EFFECT_SUBTYPES

    @property
    def isALightShow(self) -> bool:
        """Return True if the object is a light show."""
        return self.objtype == CIRCUIT_TYPE and self.subtype == "LITSHO"

    @property
    def isFeatured(self) -> bool:
        """Return True if the object is Featured."""
        return bool(self[FEATR_ATTR] == "ON")

    def __getitem__(self, key: str) -> Any:
        """Return the value for attribute 'key'."""
        return self._properties.get(key)

    def __str__(self) -> str:
        """Return a friendly string representation."""
        result = f"{self.objnam} "
        result += f"({self.objtype}/{self.subtype}):" if self.subtype else f"({self.objtype}):"
        for key in sorted(set(self._properties.keys())):
            value = self._properties[key]
            if isinstance(value, list):
                value = "[" + ",".join(f"{ {str(v)} }" for v in value) + "]"
            result += f" {key}: {value}"
        return result

    @property
    def attributes(self) -> list[str]:
        """Return the list of attributes for this object."""
        return list(self._properties.keys())

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
            if key in self._properties and self._properties[key] == value:
                # Ignore unchanged existing value
                continue

            # There are a few cases when we receive the type/subtype in an update
            if key == OBJTYP_ATTR:
                self._objtyp = value
            elif key == SUBTYP_ATTR:
                self._subtyp = value
            else:
                self._properties[key] = value
            changed[key] = value

        return changed


# ---------------------------------------------------------------------------


class PoolModel:
    """Representation of a subset of the underlying Pentair system.

    The PoolModel maintains a collection of PoolObjects and provides
    methods for querying and updating them. It filters objects based
    on an attribute map to only track relevant equipment types.
    """

    def __init__(
        self,
        attributeMap: dict[str, set[str]] | None = None,
    ) -> None:
        """Initialize the model.

        Args:
            attributeMap: Optional mapping of object types to their tracked attributes.
                         Defaults to ALL_ATTRIBUTES_BY_TYPE.
        """
        self._objects: dict[str, PoolObject] = {}
        self._systemObject: PoolObject | None = None
        self._attributeMap = attributeMap if attributeMap is not None else ALL_ATTRIBUTES_BY_TYPE

    @property
    def objectList(self) -> list[PoolObject]:
        """Return the list of objects contained in the model."""
        return list(self._objects.values())

    @property
    def objects(self) -> dict[str, PoolObject]:
        """Return the dictionary of objects contained in the model."""
        return self._objects

    @property
    def numObjects(self) -> int:
        """Return the number of objects contained in the model."""
        return len(self._objects)

    def __iter__(self) -> Iterator[PoolObject]:
        """Allow iteration over all values."""
        return iter(self._objects.values())

    def __getitem__(self, key: str) -> PoolObject | None:
        """Return an object based on its objnam."""
        return self._objects.get(key)

    def getByType(self, obj_type: str, subtype: str | None = None) -> list[PoolObject]:
        """Return all objects which match the type and optional subtype.

        Args:
            obj_type: The object type to filter by (e.g., 'BODY', 'PUMP')
            subtype: Optional subtype to further filter (e.g., 'SPA', 'POOL')

        Returns:
            List of matching PoolObjects

        Examples:
            getByType('BODY') will return all objects of type 'BODY'
            getByType('BODY', 'SPA') will only return the Spa
        """
        return [
            obj
            for obj in self
            if obj.objtype == obj_type and (not subtype or obj.subtype == subtype)
        ]

    def getChildren(self, pool_object: PoolObject) -> list[PoolObject]:
        """Return the children of a given object.

        Args:
            pool_object: The parent object

        Returns:
            List of child PoolObjects
        """
        return [obj for obj in self if obj[PARENT_ATTR] == pool_object.objnam]

    def addObject(self, objnam: str, params: dict[str, Any]) -> PoolObject | None:
        """Update the model with a new object.

        If the object already exists, updates its attributes instead.
        Only adds objects whose type is in the attribute map.

        Args:
            objnam: The object identifier
            params: Dictionary of object attributes

        Returns:
            The created/updated PoolObject, or None if type not in attribute map
        """
        # Because the controller may be started more than once,
        # we don't override existing objects
        pool_obj = self._objects.get(objnam)

        if not pool_obj:
            pool_obj = PoolObject(objnam, params)
            if pool_obj.objtype == "SYSTEM":
                self._systemObject = pool_obj
            if pool_obj.objtype in self._attributeMap:
                self._objects[objnam] = pool_obj
            else:
                pool_obj = None
        else:
            pool_obj.update(params)
        return pool_obj

    def addObjects(self, objList: list[dict[str, Any]]) -> None:
        """Create or update from all the objects in the list.

        Args:
            objList: List of objects with 'objnam' and 'params' keys
        """
        for elt in objList:
            self.addObject(elt["objnam"], elt["params"])

    def attributesToTrack(self) -> list[dict[str, Any]]:
        """Return all the object/attributes we want to track.

        Returns:
            List of query items with 'objnam' and 'keys' for each object
        """
        query: list[dict[str, Any]] = []
        for pool_obj in self.objectList:
            attributes = self._attributeMap.get(pool_obj.objtype)
            if not attributes:
                # If we don't specify a set of attributes for this object type,
                # default to all known attributes for this type
                attributes = ALL_ATTRIBUTES_BY_TYPE.get(pool_obj.objtype)
            if attributes:
                query.append({"objnam": pool_obj.objnam, "keys": list(attributes)})
        return query

    def processUpdates(self, updates: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
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
            if pool_obj:
                changed = pool_obj.update(update["params"])
                if changed:
                    updated[objnam] = changed
        return updated
