"""Read-only FDR observations; no device support or subscription is implied."""

from collections.abc import Mapping
from copy import deepcopy
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any


class EventObservationReason(StrEnum):
    """Observation quality, separate from panel event status codes."""

    UNAVAILABLE = "unavailable"
    STALE = "stale"
    MISSING_STATUS = "missing_status"
    UNKNOWN_STATUS = "unknown_status"
    RUNNING = "running"


@dataclass(frozen=True, slots=True)
class EventState:
    """One independent observation, never a claim of device capability.

    ``active`` is tri-state. No inactive wire value is established yet, so
    this version returns only True or None. Raw fields remain available even
    when stale or unavailable. Properties return copies owned by the caller.
    """

    active: bool | None
    reason: EventObservationReason
    _raw: dict[str, Any] = field(repr=False)

    @property
    def raw(self) -> dict[str, Any]:
        """Preserve field presence, nulls, types, and unknown values."""
        return deepcopy(self._raw)

    @property
    def raw_status(self) -> Any:
        """Return EVENTSTATUS without normalization."""
        return deepcopy(self._raw.get("EVENTSTATUS"))

    @property
    def event_id(self) -> Any:
        """Return EVENTID without coercion or inferred identity semantics."""
        return deepcopy(self._raw.get("EVENTID"))


def observe_fdr_event(
    params: Mapping[str, Any] | None,
    *,
    connected: bool = False,
    fresh: bool = False,
) -> EventState:
    """Interpret one supplied _FDR parameter snapshot, without network I/O.

    Callers must establish connection and freshness explicitly. Do not merge
    an old status with a changed ID, or mark cached data fresh on reconnect.
    Missing fields in this observation are absent, not carried forward.
    ``fresh`` is caller evidence, not a timestamp or automatic expiry policy.
    """
    raw = deepcopy(
        {key: params[key] for key in ("EVENTSTATUS", "EVENTID") if key in params}
        if params is not None
        else {}
    )
    if not connected:
        reason = EventObservationReason.UNAVAILABLE
    elif not fresh:
        reason = EventObservationReason.STALE
    elif "EVENTSTATUS" not in raw or raw["EVENTSTATUS"] is None:
        reason = EventObservationReason.MISSING_STATUS
    elif isinstance(raw["EVENTSTATUS"], str) and raw["EVENTSTATUS"] == "running":
        reason = EventObservationReason.RUNNING
    else:
        reason = EventObservationReason.UNKNOWN_STATUS
    return EventState(
        active=True if reason == EventObservationReason.RUNNING else None,
        reason=reason,
        _raw=raw,
    )
