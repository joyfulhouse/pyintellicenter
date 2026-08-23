"""mDNS discovery for Pentair IntelliCenter units.

This module provides discovery functionality to find IntelliCenter units
on the local network using mDNS (Zeroconf).

Example:
    ```python
    import asyncio
    from pyintellicenter.discovery import discover_intellicenter_units

    async def main():
        units = await discover_intellicenter_units(discovery_timeout=5.0)
        for unit in units:
            print(f"Found: {unit.name} at {unit.host}:{unit.port}")

    asyncio.run(main())
    ```
"""

from __future__ import annotations

import asyncio
import contextlib
import enum
import logging
from dataclasses import dataclass
from typing import TYPE_CHECKING

from zeroconf import ServiceStateChange
from zeroconf.asyncio import AsyncServiceBrowser, AsyncServiceInfo, AsyncZeroconf

if TYPE_CHECKING:
    from zeroconf import ServiceInfo, Zeroconf

_LOGGER = logging.getLogger(__name__)

# IntelliCenter service type for mDNS discovery
INTELLICENTER_SERVICE_TYPE = "_http._tcp.local."
INTELLICENTER_SERVICE_NAME_PREFIX = "Pentair"

# Additional service type some IntelliCenter firmwares advertise
_PENTAIR_SERVICE_TYPE = "_pentair._tcp.local."

# Default discovery timeout
DEFAULT_DISCOVERY_TIMEOUT = 10.0

# Timeout for resolving a single service's records (milliseconds)
_RESOLVE_TIMEOUT_MS = 3000.0

# Timeout for probing the raw TCP port of a candidate unit (seconds)
_TCP_PROBE_TIMEOUT = 2.0

# Size of the worker pool draining the candidate queue; bounds both task
# count and concurrent resolutions
_RESOLUTION_WORKERS = 8


class _ResolutionState(enum.Enum):
    """Resolution lifecycle of a browsed service."""

    PENDING = "pending"  # queued or currently resolving
    RESOLVED = "resolved"  # definitive outcome (unit added, or non-IntelliCenter)
    FAILED = "failed"  # transient failure; a later Added/Updated event retries


@dataclass(frozen=True)
class ICUnit:
    """Represents a discovered IntelliCenter unit.

    Attributes:
        name: The unit name from mDNS
        host: IP address or hostname
        port: Raw TCP port for protocol communication (typically 6681)
        ws_port: WebSocket port from mDNS (typically 6680)
        model: Model information if available
    """

    name: str
    host: str
    port: int
    ws_port: int
    model: str | None = None

    def __repr__(self) -> str:
        return f"ICUnit(name={self.name!r}, host={self.host!r}, port={self.port}, ws_port={self.ws_port})"


class ICDiscoveryListener:
    """Tracks services reported by an ``AsyncServiceBrowser``.

    The state-change handler runs on the event loop (no threads), so plain
    ``asyncio`` primitives are safe here. Added/Updated events are
    deduplicated per ``(service_type, name)`` pair while a resolution is
    pending or definitively resolved; after a transient failure a later
    event re-queues the service for another attempt.

    Each service carries a generation counter that ``Removed`` bumps, so a
    resolution that started before the removal reports a stale generation
    and cannot resurrect the removed service (issue #76).
    """

    def __init__(self) -> None:
        self._units: dict[str, ICUnit] = {}
        self._states: dict[tuple[str, str], _ResolutionState] = {}
        self._generations: dict[tuple[str, str], int] = {}
        self._candidates: asyncio.Queue[tuple[Zeroconf, str, str, int]] = asyncio.Queue()

    @property
    def units(self) -> list[ICUnit]:
        """Return list of discovered units."""
        return list(self._units.values())

    def async_on_service_state_change(
        self,
        zeroconf: Zeroconf,
        service_type: str,
        name: str,
        state_change: ServiceStateChange,
    ) -> None:
        """Handle a service state change (runs in the event loop)."""
        key = (service_type, name)
        if state_change is ServiceStateChange.Removed:
            # Bump the generation so an in-flight resolution that started
            # before this removal cannot re-add the unit when it completes.
            self._generations[key] = self._generations.get(key, 0) + 1
            self._units.pop(name, None)
            self._states.pop(key, None)
            return

        state = self._states.get(key)
        if state in (_ResolutionState.PENDING, _ResolutionState.RESOLVED):
            # Deduplicate repeated Added/Updated events; only a service whose
            # last resolution failed (or was removed) is worth retrying.
            return
        self._states[key] = _ResolutionState.PENDING
        self._candidates.put_nowait((zeroconf, service_type, name, self._generations.get(key, 0)))

    async def async_get_candidate(self) -> tuple[Zeroconf, str, str, int]:
        """Wait for the next candidate service to resolve."""
        return await self._candidates.get()

    def _is_current(self, key: tuple[str, str], generation: int) -> bool:
        """Return True if a resolution outcome is not stale."""
        return self._generations.get(key, 0) == generation

    def mark_resolved(
        self, service_type: str, name: str, generation: int, unit: ICUnit | None
    ) -> None:
        """Record a definitive resolution outcome, unless it is stale.

        ``unit`` is the discovered IntelliCenter, or None when the service
        resolved as something other than an IntelliCenter.
        """
        key = (service_type, name)
        if not self._is_current(key, generation):
            return
        self._states[key] = _ResolutionState.RESOLVED
        if unit is not None:
            self.add_unit(name, unit)

    def mark_failed(self, service_type: str, name: str, generation: int) -> None:
        """Record a transient resolution failure, unless it is stale.

        A later Added/Updated event for the service re-queues it.
        """
        key = (service_type, name)
        if not self._is_current(key, generation):
            return
        self._states[key] = _ResolutionState.FAILED

    def add_unit(self, name: str, unit: ICUnit) -> None:
        """Add a discovered unit."""
        self._units[name] = unit


def _is_intellicenter(name: str, info: ServiceInfo) -> bool:
    """Check if the service is an IntelliCenter unit."""
    # Check name prefix
    if name.lower().startswith("pentair") or "intellicenter" in name.lower():
        return True

    # Check properties
    if info.properties:
        for key, value in info.properties.items():
            key_str = key.decode("utf-8", errors="ignore").lower()
            if value is not None:
                value_str = value.decode("utf-8", errors="ignore").lower()
                if "pentair" in value_str or "intellicenter" in value_str:
                    return True
            if "pentair" in key_str or "intellicenter" in key_str:
                return True

    return False


async def _check_tcp_port(host: str, port: int) -> bool:
    """Check if a TCP port is connectable."""
    try:
        _, writer = await asyncio.wait_for(
            asyncio.open_connection(host, port),
            timeout=_TCP_PROBE_TIMEOUT,
        )
        writer.close()
        await writer.wait_closed()
        return True
    except (OSError, TimeoutError):
        return False


async def _resolve_service(
    listener: ICDiscoveryListener,
    zc: Zeroconf,
    service_type: str,
    name: str,
    generation: int,
) -> None:
    """Resolve service info and record the outcome on the listener.

    Definitive outcomes — an IntelliCenter unit discovered, or a service
    identified as something else — are marked resolved. Transient failures
    (records not resolving, no advertised addresses, TCP probe failing) are
    marked failed so a later Added/Updated event retries. ``generation`` is
    validated by the listener before any state is recorded, so a service
    removed while this resolution was in flight is not resurrected.
    """
    try:
        info = AsyncServiceInfo(service_type, name)
        if not await info.async_request(zc, _RESOLVE_TIMEOUT_MS):
            listener.mark_failed(service_type, name, generation)
            return

        # Check if this is a Pentair/IntelliCenter device
        service_name = info.name or name
        if not _is_intellicenter(service_name, info):
            listener.mark_resolved(service_type, name, generation, None)
            return

        # Extract addresses; scoped addresses keep the scope id that
        # link-local IPv6 needs to be connectable
        addresses = info.parsed_scoped_addresses()
        if not addresses:
            listener.mark_failed(service_type, name, generation)
            return

        # mDNS advertises WebSocket port (typically 6680)
        ws_port = info.port or 6680
        # Raw TCP port is WebSocket port + 1 (typically 6681)
        tcp_port = ws_port + 1

        # Probe advertised addresses in order until one is connectable; a
        # dual-stack panel may advertise an unreachable address first. The
        # discovery deadline in _process_candidates cancels this loop when
        # the remaining time elapses.
        host: str | None = None
        for address in addresses:
            if await _check_tcp_port(address, tcp_port):
                host = address
                break

        if host is None:
            _LOGGER.warning(
                "IntelliCenter %s found at %s but TCP port %d not accessible",
                service_name,
                addresses,
                tcp_port,
            )
            listener.mark_failed(service_type, name, generation)
            return

        # Extract model from properties if available
        model = None
        if info.properties:
            model_bytes = info.properties.get(b"model")
            if model_bytes is not None:
                model = model_bytes.decode("utf-8", errors="ignore")

        unit = ICUnit(
            name=service_name, host=host, port=tcp_port, ws_port=ws_port, model=model or None
        )
        listener.mark_resolved(service_type, name, generation, unit)
        _LOGGER.debug(
            "Discovered IntelliCenter: %s at %s (TCP:%d, WS:%d)",
            service_name,
            host,
            tcp_port,
            ws_port,
        )

    except Exception:
        _LOGGER.exception("Error resolving service %s", name)
        listener.mark_failed(service_type, name, generation)


async def _resolution_worker(listener: ICDiscoveryListener) -> None:
    """Drain and resolve candidate services until cancelled."""
    while True:
        zc, service_type, name, generation = await listener.async_get_candidate()
        await _resolve_service(listener, zc, service_type, name, generation)


async def _process_candidates(
    listener: ICDiscoveryListener,
    discovery_timeout: float,
) -> None:
    """Resolve candidate services concurrently until the deadline expires.

    A fixed pool of workers drains the candidate queue, bounding both task
    count and concurrent resolutions, so a noisy network full of slow
    ``_http._tcp`` services can neither starve the IntelliCenter unit nor
    accumulate unbounded tasks. The overall deadline is enforced on the
    whole pool.
    """
    try:
        async with asyncio.timeout(discovery_timeout), asyncio.TaskGroup() as task_group:
            for _ in range(_RESOLUTION_WORKERS):
                task_group.create_task(_resolution_worker(listener))
    except TimeoutError:
        # Discovery window elapsed; workers and in-flight resolutions
        # were cancelled.
        pass


async def discover_intellicenter_units(
    discovery_timeout: float = DEFAULT_DISCOVERY_TIMEOUT,
    zeroconf: Zeroconf | None = None,
) -> list[ICUnit]:
    """Discover IntelliCenter units on the local network.

    Uses mDNS (Zeroconf) to find IntelliCenter units broadcasting
    on the local network.

    Args:
        discovery_timeout: How long to wait for discovery (seconds)
        zeroconf: Optional existing Zeroconf instance to use. If not provided,
            a new instance will be created and closed after discovery. A
            caller-provided instance is never closed by this function.
            When integrating with Home Assistant, pass the shared Zeroconf
            instance obtained via `async_get_instance(hass)`.

    Returns:
        List of discovered ICUnit instances
    """
    # Only close a Zeroconf instance this function created (issue #53)
    aiozc: AsyncZeroconf | None = None
    if zeroconf is None:
        aiozc = AsyncZeroconf()
        zc = aiozc.zeroconf
    else:
        zc = zeroconf

    listener = ICDiscoveryListener()
    browsers: list[AsyncServiceBrowser] = []

    try:
        # Browse for HTTP services (IntelliCenter uses HTTP on port 6681).
        # Handlers run in the event loop; no threads are involved.
        browsers.append(
            AsyncServiceBrowser(
                zc,
                INTELLICENTER_SERVICE_TYPE,
                handlers=[listener.async_on_service_state_change],
            )
        )

        # Also try to browse for any specific IntelliCenter service types
        with contextlib.suppress(Exception):
            browsers.append(
                AsyncServiceBrowser(
                    zc,
                    _PENTAIR_SERVICE_TYPE,
                    handlers=[listener.async_on_service_state_change],
                )
            )

        await _process_candidates(listener, discovery_timeout)

        return listener.units

    finally:
        # Cancel browsers before (possibly) closing zeroconf; async_cancel
        # does not block the event loop.
        for browser in browsers:
            await browser.async_cancel()
        # Close our own zeroconf if we created it; never touch a borrowed one
        if aiozc is not None:
            await aiozc.async_close()


async def find_unit_by_name(
    name: str,
    discovery_timeout: float = DEFAULT_DISCOVERY_TIMEOUT,
    zeroconf: Zeroconf | None = None,
) -> ICUnit | None:
    """Find a specific IntelliCenter unit by name.

    Args:
        name: Name or partial name to search for (case-insensitive)
        discovery_timeout: How long to wait for discovery
        zeroconf: Optional existing Zeroconf instance to use; a
            caller-provided instance is never closed

    Returns:
        ICUnit if found, None otherwise
    """
    units = await discover_intellicenter_units(
        discovery_timeout=discovery_timeout, zeroconf=zeroconf
    )
    name_lower = name.lower()

    for unit in units:
        if name_lower in unit.name.lower():
            return unit

    return None


async def find_unit_by_host(
    host: str,
    discovery_timeout: float = DEFAULT_DISCOVERY_TIMEOUT,
    zeroconf: Zeroconf | None = None,
) -> ICUnit | None:
    """Find a specific IntelliCenter unit by IP address.

    Args:
        host: IP address to search for
        discovery_timeout: How long to wait for discovery
        zeroconf: Optional existing Zeroconf instance to use; a
            caller-provided instance is never closed

    Returns:
        ICUnit if found, None otherwise
    """
    units = await discover_intellicenter_units(
        discovery_timeout=discovery_timeout, zeroconf=zeroconf
    )

    for unit in units:
        if unit.host == host:
            return unit

    return None
