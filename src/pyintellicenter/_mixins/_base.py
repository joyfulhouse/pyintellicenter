"""Shared typing support for ``ICModelController`` mixins.

The mixins in this package are composed into :class:`ICModelController` and rely
on members defined by the host class (the model, attribute coercion helpers, the
request-coalescing entry point, and the connection-level ``send_cmd`` /
``system_info``). To give ``mypy`` strict visibility of those members without any
runtime behavior change, each mixin inherits :data:`_MixinBase`.

At runtime ``_MixinBase`` is plain ``object``, so the method-resolution order and
behavior of ``ICModelController`` are completely unchanged. Under ``TYPE_CHECKING``
it is a stub class declaring the host-class members the mixins use.

The stub is deliberately a plain class -- **not** a :class:`typing.Protocol`. A
``Protocol``'s empty-bodied members are *implicitly abstract*; because the mixins
(and therefore this base) precede the concrete ``ICBaseController`` in the MRO,
that abstractness leaked out to downstream type-checkers, which then rejected
``ICModelController(...)`` as ``[abstract]`` even though the runtime class is
fully concrete (issue #35). Giving the stub concrete (never-executed) bodies
keeps it non-abstract while still resolving the members for the mixin bodies.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from ..controller import ICSystemInfo
    from ..model import PoolModel

    class _MixinBase:
        """Static-only view of the ``ICModelController`` members used by mixins.

        Exists only under ``TYPE_CHECKING``; at runtime the mixins subclass
        ``object`` (see the ``else`` branch below), so ``ICModelController``'s MRO
        and behavior are unchanged. Every member carries a concrete body so the
        class is not abstract -- this is what keeps ``ICModelController``
        instantiable for downstream type-checkers. Signatures mirror the concrete
        implementations on ``ICBaseController`` / ``ICModelController`` exactly so
        no incompatible-base errors arise when they are combined. The bodies are
        never executed (the real implementations win at runtime).
        """

        _model: PoolModel
        _system_info: ICSystemInfo | None

        @property
        def system_info(self) -> ICSystemInfo | None:
            """Return cached system information (provided by ``ICBaseController``)."""
            raise NotImplementedError

        def _get_attr_as_int(self, objnam: str, attr: str) -> int | None:
            """Return an attribute value coerced to ``int`` or ``None``."""
            raise NotImplementedError

        def _get_attr_as_float(self, objnam: str, attr: str) -> float | None:
            """Return an attribute value coerced to ``float`` or ``None``."""
            raise NotImplementedError

        async def _queue_property_change(
            self, objnam: str, changes: dict[str, str]
        ) -> dict[str, Any]:
            """Queue a coalesced property change and return the response."""
            raise NotImplementedError

        async def send_cmd(self, cmd: str, extra: dict[str, Any] | None = None) -> dict[str, Any]:
            """Send a command and return the response (provided by ``ICBaseController``)."""
            raise NotImplementedError

else:
    _MixinBase = object
