"""Evidence-bounded firmware observations and installation lifecycle scaffolding.

No hardware installation contract is currently validated. App request builders
establish encoding, not eligibility, progress units, or terminal device states.
"""

from __future__ import annotations

import asyncio
import math
from copy import deepcopy
from dataclasses import dataclass
from enum import StrEnum
from typing import TYPE_CHECKING, Any

from .exceptions import ICCommandError, ICConnectionError, ICError, ICResponseError

if TYPE_CHECKING:
    from collections.abc import AsyncIterator, Callable

    from .connection import ICConnection
    from .controller import ICBaseController

FIRMWARE_KEYS = ("VER", "PROPNAME", "UPDATE", "IN", "PROGRESS", "AUTO")


class FirmwareUpdatePhase(StrEnum):
    """Client lifecycle states; these are not panel progress codes."""

    UNKNOWN = "unknown"
    AVAILABLE = "available"
    REQUESTED = "requested"
    ACKNOWLEDGED = "acknowledged"
    PROGRESS_OBSERVED = "progress_observed"
    RECONNECTING = "reconnecting"
    VERIFIED = "verified"
    FAILED = "failed"


@dataclass(frozen=True)
class FirmwareUpdateCapability:
    """Installation support and current eligibility are separate from availability."""

    install_supported: bool = False
    eligible: bool = False
    decline_supported: bool = False
    cancel_supported: bool = False
    evidence: str | None = None


@dataclass(frozen=True)
class FirmwareUpdateState:
    """Detached observation snapshot. Raw progress has no assumed unit or range.

    ``available`` retains the existing numeric UPDATE flag interpretation;
    unrecognized values remain in ``raw``. ``acknowledged`` never means installed.
    ``verified_version`` comes only from an explicit fresh verification read.
    """

    phase: FirmwareUpdatePhase
    capability: FirmwareUpdateCapability
    connected: bool
    raw: dict[str, Any]
    available: bool | None
    installed_version: str | None
    acknowledged: bool
    target_version: str | None
    verified_version: str | None
    reason: str | None


@dataclass(frozen=True)
class _FirmwareSupportContract:
    """Internal gate to populate only with reviewed, correlated device fixtures.

    A contract identifies an exact source/target pair and every eligibility
    field. Synthetic test contracts exercise scaffolding without certifying a
    real panel. Decline/cancel and progress interpretation remain unsupported.
    """

    source_version: str
    target_version: str
    required_params: tuple[tuple[str, str], ...]
    evidence: str


# Static app evidence cannot populate this table. No public enable/force switch.
_VALIDATED_INSTALL_CONTRACTS: tuple[_FirmwareSupportContract, ...] = ()


def _version(value: Any) -> str | None:
    return value if isinstance(value, str) and value.strip() and value != "VER" else None


class _FirmwareLifecycle:
    """One controller's observations and at most one admitted install request."""

    def __init__(self, controller: ICBaseController) -> None:
        self.controller = controller
        self.raw: dict[str, Any] = {}
        self.phase = FirmwareUpdatePhase.UNKNOWN
        self.acknowledged = False
        self.target: str | None = None
        self.baseline: str | None = None
        self.verified: str | None = None
        self.reason: str | None = None
        self.admitted = False
        self.dispatched = False
        self._progress_observed = False
        self._request_pending = False
        self._verification_lock = asyncio.Lock()
        self.revision = 0
        self._key_revisions: dict[str, int] = {}
        self._generation = 0
        self._timer: asyncio.TimerHandle | None = None
        self._remove_observer: Callable[[], None] | None = None
        self._watchers: set[asyncio.Queue[FirmwareUpdateState]] = set()

    def _contract(self, target: str | None = None) -> _FirmwareSupportContract | None:
        info = self.controller.system_info
        if info is None or info.objnam != "_5451":
            return None
        return next(
            (
                contract
                for contract in _VALIDATED_INSTALL_CONTRACTS
                if contract.evidence
                and contract.required_params
                and contract.source_version != contract.target_version
                and contract.source_version == _version(self.raw.get("VER"))
                and (target is None or contract.target_version == target)
            ),
            None,
        )

    def _eligible(self, contract: _FirmwareSupportContract) -> bool:
        return (
            self.controller.connected
            and not self.admitted
            and all(self.raw.get(key) == value for key, value in contract.required_params)
        )

    @property
    def state(self) -> FirmwareUpdateState:
        contract = self._contract()
        value = self.raw.get("UPDATE")
        available = None
        if type(value) in (str, int) and value in ("0", "1", 0, 1):
            available = value in ("1", 1)
        return FirmwareUpdateState(
            phase=self.phase,
            capability=FirmwareUpdateCapability(
                install_supported=contract is not None,
                eligible=contract is not None and self._eligible(contract),
                evidence=contract.evidence if contract else None,
            ),
            connected=self.controller.connected,
            raw=deepcopy(self.raw),
            available=available,
            installed_version=_version(self.raw.get("VER")),
            acknowledged=self.acknowledged,
            target_version=self.target,
            verified_version=self.verified,
            reason=self.reason,
        )

    def _publish(self) -> None:
        for queue in self._watchers:
            if queue.full():
                queue.get_nowait()
            queue.put_nowait(self.state)

    def attach(self, connection: ICConnection) -> None:
        if self._remove_observer:
            self._remove_observer()
        self.raw.clear()
        self._key_revisions.clear()
        self._generation += 1
        generation = self._generation
        self._progress_observed = False
        if self.admitted and self.phase in (
            FirmwareUpdatePhase.REQUESTED,
            FirmwareUpdatePhase.ACKNOWLEDGED,
            FirmwareUpdatePhase.PROGRESS_OBSERVED,
            FirmwareUpdatePhase.RECONNECTING,
        ):
            self.phase = FirmwareUpdatePhase.RECONNECTING
        elif not self.admitted:
            self.phase = FirmwareUpdatePhase.UNKNOWN

        def observe(_sequence: int, message: dict[str, Any]) -> None:
            if (
                self._generation == generation
                and self.controller._connection is connection
                and connection.connected
            ):
                self.observe_entries(message.get("objectList"), from_notification=True)

        self._remove_observer = connection.add_notification_observer(observe)
        self._publish()

    def observe_entries(
        self, entries: Any, *, from_notification: bool = False, snapshot_revision: int | None = None
    ) -> None:
        info = self.controller.system_info
        if info is None or not isinstance(entries, list):
            return
        self.revision += 1
        changed = False
        progress_received = False
        for entry in entries:
            if not isinstance(entry, dict) or entry.get("objnam") != info.objnam:
                continue
            params = entry.get("params")
            if not isinstance(params, dict):
                continue
            for key in FIRMWARE_KEYS:
                if key in params and (
                    snapshot_revision is None
                    or self._key_revisions.get(key, 0) <= snapshot_revision
                ):
                    self.raw[key] = deepcopy(params[key])
                    self._key_revisions[key] = self.revision
                    changed = True
                    progress_received |= key == "PROGRESS"
        if not changed:
            return
        if not self.admitted:
            self.phase = (
                FirmwareUpdatePhase.AVAILABLE
                if self.state.available is True
                else FirmwareUpdatePhase.UNKNOWN
            )
        # Record receipt only, never interpret a percentage or terminal code.
        elif (
            self.dispatched
            and from_notification
            and progress_received
            and self.phase
            in (
                FirmwareUpdatePhase.REQUESTED,
                FirmwareUpdatePhase.ACKNOWLEDGED,
                FirmwareUpdatePhase.PROGRESS_OBSERVED,
            )
        ):
            progress = self.raw.get("PROGRESS")
            self._progress_observed = (
                isinstance(progress, str) and progress.strip() not in ("", "PROGRESS")
            ) or (
                type(progress) is int or (isinstance(progress, float) and math.isfinite(progress))
            )
            if self.acknowledged:
                self.phase = (
                    FirmwareUpdatePhase.PROGRESS_OBSERVED
                    if self._progress_observed
                    else FirmwareUpdatePhase.ACKNOWLEDGED
                )
        self._publish()

    def disconnected(self, *, stopped: bool = False) -> None:
        self._generation += 1
        if self._remove_observer:
            self._remove_observer()
            self._remove_observer = None
        if self.admitted and self.phase in (
            FirmwareUpdatePhase.REQUESTED,
            FirmwareUpdatePhase.ACKNOWLEDGED,
            FirmwareUpdatePhase.PROGRESS_OBSERVED,
            FirmwareUpdatePhase.RECONNECTING,
        ):
            self.phase = (
                FirmwareUpdatePhase.UNKNOWN if stopped else FirmwareUpdatePhase.RECONNECTING
            )
            self.reason = "controller_stopped" if stopped else "connection_lost"
        if stopped:
            self._cancel_timer()
        self._publish()

    def _cancel_timer(self) -> None:
        if self._timer:
            self._timer.cancel()
            self._timer = None

    def _uncertain(self, reason: str) -> None:
        if self.verified is None and self.phase != FirmwareUpdatePhase.FAILED:
            self.phase = FirmwareUpdatePhase.UNKNOWN
            self.reason = reason
            self._publish()
        self._cancel_timer()

    async def request_install(
        self, target_version: str, verification_timeout: float
    ) -> FirmwareUpdateState:
        if self.admitted:
            raise ICError("Firmware install already requested; reconcile without replaying it")
        contract = self._contract(target_version)
        if contract is None:
            raise ICError("No validated firmware installation support contract")
        if not self._eligible(contract):
            raise ICError("Firmware installation eligibility is not established")
        if not math.isfinite(verification_timeout) or verification_timeout <= 0:
            raise ValueError("verification_timeout must be finite and positive")
        if self.controller._light_group_mutation_pending:
            raise ICError("Color Sync mutation lifecycle is in progress")
        connection = self.controller._connection
        if connection is None:
            raise ICConnectionError("Not connected")
        generation = self._generation
        self.admitted = True
        self.baseline = _version(self.raw.get("VER"))
        self.target = target_version
        self.phase = FirmwareUpdatePhase.REQUESTED
        self._publish()

        def before_write(_sequence: int, _when: float) -> None:
            # Transport queueing can outlast the controller's admission checks.
            if (
                generation != self._generation
                or self.controller._connection is not connection
                or not connection.connected
            ):
                raise ICConnectionError("Connection changed before firmware write")
            if _version(self.raw.get("VER")) != contract.source_version or any(
                self.raw.get(key) != value for key, value in contract.required_params
            ):
                raise ICError("Firmware eligibility changed before write")
            self.dispatched = True

        deadline = asyncio.get_running_loop().time() + verification_timeout
        self._request_pending = True
        try:
            async with asyncio.timeout_at(deadline):
                async with self.controller._mutation_lifecycle():
                    if self.controller._connection is not connection or not connection.connected:
                        raise ICConnectionError("Connection changed before firmware request")
                    # Recheck captured eligibility after waiting for older writes.
                    if any(self.raw.get(k) != v for k, v in contract.required_params):
                        raise ICError("Firmware installation eligibility changed")
                    if _version(self.raw.get("VER")) != contract.source_version:
                        raise ICError("Firmware source version changed")
                    response = await self.controller._send_firmware_request(
                        connection,
                        "SetParamList",
                        objectList=[{"objnam": "_5451", "params": {"IN": "YES"}}],
                        _before_write_callback=before_write,
                    )
                    if response.get("response") != "200":
                        raise ICResponseError("MALFORMED", "No positive acknowledgement")
        except ICResponseError as err:
            if err.code != "MALFORMED":
                self.phase = FirmwareUpdatePhase.FAILED
                self.reason = f"request_rejected:{err.code}"
                self._publish()
                raise ICCommandError(err.code) from err
            self._uncertain("malformed_acknowledgement")
            raise
        except (ICError, OSError, TimeoutError, asyncio.CancelledError):
            self._uncertain("request_outcome_uncertain" if self.dispatched else "request_not_sent")
            raise
        except Exception:
            self._uncertain("request_outcome_uncertain" if self.dispatched else "request_not_sent")
            raise
        finally:
            self._request_pending = False
        self.acknowledged = True
        if self.controller._connection is connection and connection.connected:
            self.phase = (
                FirmwareUpdatePhase.PROGRESS_OBSERVED
                if self._progress_observed
                else FirmwareUpdatePhase.ACKNOWLEDGED
            )
        self._timer = asyncio.get_running_loop().call_at(
            deadline, self._uncertain, "verification_timeout"
        )
        self._publish()
        return self.state

    async def verify(self) -> FirmwareUpdateState:
        async with self._verification_lock:
            return await self._verify()

    async def _verify(self) -> FirmwareUpdateState:
        if self.verified is not None:
            return self.state
        if self._request_pending:
            raise ICError("Firmware request is still awaiting its acknowledgement")
        if not self.admitted or not self.dispatched or self.phase == FirmwareUpdatePhase.FAILED:
            raise ICError("No dispatched firmware installation to verify")
        connection = self.controller._connection
        info = self.controller.system_info
        if connection is None or not connection.connected or info is None:
            raise ICConnectionError("Not connected")
        generation = self._generation
        revision = self.revision
        try:
            response = await self.controller._send_firmware_request(
                connection, "GetParamList", objectList=[{"objnam": info.objnam, "keys": ["VER"]}]
            )
        except (ICError, OSError, TimeoutError, asyncio.CancelledError):
            self._uncertain("verification_read_failed")
            raise
        if (
            generation != self._generation
            or self.controller._connection is not connection
            or not connection.connected
        ):
            self._uncertain("connection_changed_during_verification")
            raise ICConnectionError("Connection changed during firmware verification")
        entries = response.get("objectList")
        versions = (
            [
                _version(entry.get("params", {}).get("VER"))
                for entry in entries or []
                if isinstance(entry, dict)
                and entry.get("objnam") == info.objnam
                and isinstance(entry.get("params"), dict)
            ]
            if isinstance(entries, list)
            else []
        )
        if len(versions) != 1 or versions[0] is None:
            self._uncertain("missing_verification_version")
            raise ICResponseError("MALFORMED", "No unique firmware version in fresh read")
        if (
            self._key_revisions.get("VER", 0) > revision
            and _version(self.raw.get("VER")) != versions[0]
        ):
            self._uncertain("version_changed_during_verification")
            return self.state
        self.revision += 1
        self._key_revisions["VER"] = self.revision
        self.raw["VER"] = versions[0]
        if versions[0] == self.target and versions[0] != self.baseline:
            self.verified = versions[0]
            self.phase = FirmwareUpdatePhase.VERIFIED
            self.reason = None
            self._cancel_timer()
        else:
            self._uncertain("target_version_not_observed")
        self._publish()
        return self.state

    async def watch(self) -> AsyncIterator[FirmwareUpdateState]:
        queue: asyncio.Queue[FirmwareUpdateState] = asyncio.Queue(maxsize=1)
        self._watchers.add(queue)
        try:
            yield self.state
            while True:
                yield await queue.get()
        finally:
            self._watchers.discard(queue)
