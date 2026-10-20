"""Evidence-bounded light-group action capabilities.

Capability decisions describe cached firmware/topology eligibility, not current
readiness or device completion. Only ``run_light_group_sync`` performs an action;
its fresh preflight and complete lifecycle remain mandatory.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import TYPE_CHECKING

from .exceptions import ICError

if TYPE_CHECKING:
    from ._mixins.circuit_group import _CircuitGroupMixin


class LightGroupAction(StrEnum):
    """Dedicated parent action parameters observed in the official app."""

    SYNC = "SYNC"
    SET = "SET"
    SWIM = "SWIM"


class LightGroupCapabilityReason(StrEnum):
    """Stable decision codes; human-readable details are not API identifiers."""

    VALIDATED = "validated"
    UNSUPPORTED_FIRMWARE = "unsupported_firmware"
    UNSUPPORTED_TRANSPORT = "unsupported_transport"
    UNSUPPORTED_PARENT = "unsupported_parent"
    MEMBERSHIP_COUNT = "membership_count"
    MALFORMED_MEMBERSHIP = "malformed_membership"
    UNSUPPORTED_CHILD = "unsupported_child"
    DUPLICATE_CHILD = "duplicate_child"
    INCOMPLETE_INVENTORY = "incomplete_inventory"
    MALFORMED_CACHE = "malformed_cache"
    SET_PERSISTED_FLAGS = "set_persisted_flags"
    SWIM_PERSISTED_FLAGS = "swim_persisted_flags"
    SWIM_LATE_MIXED_STATE = "swim_late_mixed_state"


@dataclass(frozen=True)
class LightGroupActionDecision:
    """One action's eligibility and the evidence limiting it."""

    action: LightGroupAction
    reason: LightGroupCapabilityReason
    detail: str

    @property
    def supported(self) -> bool:
        """Return whether the existing production lifecycle is validated."""
        return self.reason == LightGroupCapabilityReason.VALIDATED


@dataclass(frozen=True)
class LightGroupCapabilities:
    """Immutable per-action decisions for a single cached group/transport."""

    decisions: tuple[LightGroupActionDecision, ...]

    def for_action(self, action: LightGroupAction | str) -> LightGroupActionDecision:
        """Return a decision, rejecting unrecognized action names."""
        selected = LightGroupAction(action)
        return next(decision for decision in self.decisions if decision.action == selected)

    @property
    def validated_actions(self) -> frozenset[LightGroupAction]:
        """Return actions eligible for the production lifecycle."""
        return frozenset(decision.action for decision in self.decisions if decision.supported)


class ICLightGroupCapabilityError(ICError, ValueError):
    """A cached capability gate failed before I/O; retains ValueError compatibility."""

    def __init__(self, reason: LightGroupCapabilityReason, message: str) -> None:
        self.reason = reason
        super().__init__(message)


def _capabilities_for(controller: _CircuitGroupMixin, group_objnam: str) -> LightGroupCapabilities:
    from ._light_group import build_topology

    try:
        build_topology(controller, group_objnam)
    except ICLightGroupCapabilityError as error:
        return LightGroupCapabilities(
            tuple(
                LightGroupActionDecision(action, error.reason, str(error))
                for action in LightGroupAction
            )
        )
    except ICError as error:
        return LightGroupCapabilities(
            tuple(
                LightGroupActionDecision(
                    action, LightGroupCapabilityReason.MALFORMED_CACHE, str(error)
                )
                for action in LightGroupAction
            )
        )

    return LightGroupCapabilities(
        (
            LightGroupActionDecision(
                LightGroupAction.SYNC,
                LightGroupCapabilityReason.VALIDATED,
                "Sync validated on firmware 1.064 with two distinct GLOW children; fresh preflight required",
            ),
            LightGroupActionDecision(
                LightGroupAction.SET,
                LightGroupCapabilityReason.SET_PERSISTED_FLAGS,
                "Local Set lacked a terminal edge and left cross-group action flags ON",
            ),
            LightGroupActionDecision(
                LightGroupAction.SWIM,
                LightGroupCapabilityReason.SWIM_PERSISTED_FLAGS
                if controller.transport == "websocket"
                else LightGroupCapabilityReason.SWIM_LATE_MIXED_STATE,
                "WebSocket Swim left action flags ON"
                if controller.transport == "websocket"
                else "TCP Swim reached terminal at 74.6s but children reverted OFF at 83.6s",
            ),
        )
    )
