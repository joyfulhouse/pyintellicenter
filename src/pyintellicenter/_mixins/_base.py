"""Shared typing support for ``ICModelController`` mixins.

The mixins in this package are composed into :class:`ICModelController` and rely
on members defined by the host class (the model, attribute coercion helpers, and
the request-coalescing entry point). To keep ``mypy`` strict happy without any
runtime behavior change, each mixin inherits :class:`_ModelControllerProtocol`
*only* under ``TYPE_CHECKING``. At runtime the mixins remain plain ``object``
subclasses, so the method-resolution order of ``ICModelController`` is unchanged.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Protocol

if TYPE_CHECKING:
    from ..model import PoolModel


class _ModelControllerProtocol(Protocol):
    """Structural declaration of the host-class members used by the mixins.

    This protocol is used purely for static type checking; it is never
    instantiated and adds no runtime cost.
    """

    _model: PoolModel

    def _get_attr_as_int(self, objnam: str, attr: str) -> int | None:
        """Return an attribute value coerced to ``int`` or ``None``."""
        ...

    def _get_attr_as_float(self, objnam: str, attr: str) -> float | None:
        """Return an attribute value coerced to ``float`` or ``None``."""
        ...

    async def _queue_property_change(self, objnam: str, changes: dict[str, str]) -> dict[str, Any]:
        """Queue a coalesced property change and return the response."""
        ...


# Base class for the domain mixins. Under static type checking the mixins inherit
# the protocol above so ``mypy`` can resolve the host-class members they use; at
# runtime they inherit plain ``object`` so ``ICModelController``'s method
# resolution order and behavior are completely unchanged.
if TYPE_CHECKING:
    _MixinBase = _ModelControllerProtocol
else:
    _MixinBase = object
