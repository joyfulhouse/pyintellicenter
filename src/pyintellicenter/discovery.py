"""mDNS discovery for Pentair IntelliCenter units.

This module provides discovery functionality to find IntelliCenter units
on the local network using mDNS (Zeroconf).

Example:
    ```python
    import asyncio
    from pyintellicenter.discovery import discover_intellicenter_units

    async def main():
        units = await discover_intellicenter_units(timeout=5.0)
        for unit in units:
            print(f"Found: {unit.name} at {unit.host}:{unit.port}")

    asyncio.run(main())
    ```
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from zeroconf import ServiceInfo, Zeroconf
    from zeroconf.asyncio import AsyncZeroconf

_LOGGER = logging.getLogger(__name__)

# IntelliCenter service type for mDNS discovery
INTELLICENTER_SERVICE_TYPE = "_http._tcp.local."
INTELLICENTER_SERVICE_NAME_PREFIX = "Pentair"

# Default discovery timeout
DEFAULT_DISCOVERY_TIMEOUT = 10.0


@dataclass(frozen=True)
class ICUnit:
    """Represents a discovered IntelliCenter unit.

    Attributes:
        name: The unit name from mDNS
        host: IP address or hostname
        port: TCP port (typically 6681)
        model: Model information if available
    """

    name: str
    host: str
    port: int
    model: str | None = None

    def __repr__(self) -> str:
        return f"ICUnit(name={self.name!r}, host={self.host!r}, port={self.port})"


class ICDiscoveryListener:
    """Listener for IntelliCenter mDNS service discovery.

    Uses a queue to communicate between zeroconf's sync callbacks
    and async processing, avoiding deprecated event loop patterns.
    """

    def __init__(self, queue: asyncio.Queue[tuple[str, str, str]]) -> None:
        self._queue = queue
        self._units: dict[str, ICUnit] = {}

    @property
    def units(self) -> list[ICUnit]:
        """Return list of discovered units."""
        return list(self._units.values())

    def add_service(
        self,
        zc: Zeroconf,  # noqa: ARG002
        service_type: str,
        name: str,
    ) -> None:
        """Called when a service is discovered (sync, from zeroconf thread)."""
        # Queue for async processing - thread-safe
        try:
            self._queue.put_nowait(("add", service_type, name))
        except asyncio.QueueFull:
            _LOGGER.warning("Discovery queue full, dropping service: %s", name)

    def remove_service(
        self,
        zc: Zeroconf,  # noqa: ARG002
        service_type: str,  # noqa: ARG002
        name: str,
    ) -> None:
        """Called when a service is removed (sync, from zeroconf thread)."""
        if name in self._units:
            del self._units[name]

    def update_service(
        self,
        zc: Zeroconf,  # noqa: ARG002
        service_type: str,
        name: str,
    ) -> None:
        """Called when a service is updated (sync, from zeroconf thread)."""
        try:
            self._queue.put_nowait(("update", service_type, name))
        except asyncio.QueueFull:
            _LOGGER.warning("Discovery queue full, dropping update: %s", name)

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


async def _process_discovery_queue(
    queue: asyncio.Queue[tuple[str, str, str]],
    listener: ICDiscoveryListener,
    aiozc: AsyncZeroconf,
    discovery_timeout: float,
) -> None:
    """Process discovery events from the queue."""
    end_time = asyncio.get_running_loop().time() + discovery_timeout

    while True:
        remaining = end_time - asyncio.get_running_loop().time()
        if remaining <= 0:
            break

        try:
            action, service_type, name = await asyncio.wait_for(
                queue.get(), timeout=min(remaining, 1.0)
            )
        except TimeoutError:
            continue

        if action in ("add", "update"):
            await _resolve_service(listener, aiozc, service_type, name)


async def _resolve_service(
    listener: ICDiscoveryListener,
    aiozc: AsyncZeroconf,
    service_type: str,
    name: str,
) -> None:
    """Resolve service info and add to listener if it's an IntelliCenter."""
    try:
        info = await aiozc.async_get_service_info(service_type, name, timeout=3000)
        if info is None:
            return

        # Check if this is a Pentair/IntelliCenter device
        service_name = info.name or name
        if not _is_intellicenter(service_name, info):
            return

        # Extract address
        addresses = info.parsed_addresses()
        if not addresses:
            return

        host = addresses[0]
        port = info.port or 6681

        # Extract model from properties if available
        model = None
        if info.properties:
            model_bytes = info.properties.get(b"model")
            if model_bytes is not None:
                model = model_bytes.decode("utf-8", errors="ignore")

        unit = ICUnit(name=service_name, host=host, port=port, model=model or None)
        listener.add_unit(name, unit)
        _LOGGER.debug("Discovered IntelliCenter: %s at %s:%d", service_name, host, port)

    except Exception:
        _LOGGER.exception("Error resolving service %s", name)


async def discover_intellicenter_units(
    discovery_timeout: float = DEFAULT_DISCOVERY_TIMEOUT,
) -> list[ICUnit]:
    """Discover IntelliCenter units on the local network.

    Uses mDNS (Zeroconf) to find IntelliCenter units broadcasting
    on the local network.

    Args:
        discovery_timeout: How long to wait for discovery (seconds)

    Returns:
        List of discovered ICUnit instances

    Raises:
        ImportError: If zeroconf package is not installed

    Note:
        Requires the 'zeroconf' package to be installed:
        `pip install zeroconf` or `pip install pyintellicenter[discovery]`
    """
    try:
        from zeroconf import ServiceBrowser
        from zeroconf.asyncio import AsyncZeroconf
    except ImportError as err:
        raise ImportError(
            "mDNS discovery requires the 'zeroconf' package. Install it with: pip install zeroconf"
        ) from err

    # Queue for thread-safe communication between zeroconf callbacks and async code
    queue: asyncio.Queue[tuple[str, str, str]] = asyncio.Queue(maxsize=100)

    aiozc = AsyncZeroconf()
    listener = ICDiscoveryListener(queue)
    browsers: list[ServiceBrowser] = []

    try:
        # Browse for HTTP services (IntelliCenter uses HTTP on port 6681)
        browser = ServiceBrowser(
            aiozc.zeroconf,
            INTELLICENTER_SERVICE_TYPE,
            listener,  # type: ignore[arg-type]
        )
        browsers.append(browser)

        # Also try to browse for any specific IntelliCenter service types
        with contextlib.suppress(Exception):
            browser2 = ServiceBrowser(
                aiozc.zeroconf,
                "_pentair._tcp.local.",
                listener,  # type: ignore[arg-type]
            )
            browsers.append(browser2)

        # Process discovery events from the queue
        await _process_discovery_queue(queue, listener, aiozc, discovery_timeout)

        return listener.units

    finally:
        # Cancel browsers before closing zeroconf
        for browser in browsers:
            browser.cancel()
        await aiozc.async_close()


async def find_unit_by_name(
    name: str, discovery_timeout: float = DEFAULT_DISCOVERY_TIMEOUT
) -> ICUnit | None:
    """Find a specific IntelliCenter unit by name.

    Args:
        name: Name or partial name to search for (case-insensitive)
        discovery_timeout: How long to wait for discovery

    Returns:
        ICUnit if found, None otherwise
    """
    units = await discover_intellicenter_units(discovery_timeout)
    name_lower = name.lower()

    for unit in units:
        if name_lower in unit.name.lower():
            return unit

    return None


async def find_unit_by_host(
    host: str, discovery_timeout: float = DEFAULT_DISCOVERY_TIMEOUT
) -> ICUnit | None:
    """Find a specific IntelliCenter unit by IP address.

    Args:
        host: IP address to search for
        discovery_timeout: How long to wait for discovery

    Returns:
        ICUnit if found, None otherwise
    """
    units = await discover_intellicenter_units(discovery_timeout)

    for unit in units:
        if unit.host == host:
            return unit

    return None
