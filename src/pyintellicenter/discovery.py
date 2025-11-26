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
    """Listener for IntelliCenter mDNS service discovery."""

    def __init__(self, aiozc: AsyncZeroconf) -> None:
        self._units: dict[str, ICUnit] = {}
        self._event = asyncio.Event()
        self._aiozc = aiozc
        # Store task references to prevent "Task was destroyed" warnings
        self._pending_tasks: set[asyncio.Task[None]] = set()

    @property
    def units(self) -> list[ICUnit]:
        """Return list of discovered units."""
        return list(self._units.values())

    def _create_resolve_task(self, service_type: str, name: str) -> None:
        """Create a task to resolve a service, with proper reference tracking."""
        task = asyncio.create_task(self._resolve_service(service_type, name))
        self._pending_tasks.add(task)
        task.add_done_callback(self._pending_tasks.discard)

    def add_service(
        self,
        zc: Zeroconf,  # noqa: ARG002
        service_type: str,
        name: str,
    ) -> None:
        """Called when a service is discovered."""
        self._create_resolve_task(service_type, name)

    def remove_service(
        self,
        zc: Zeroconf,  # noqa: ARG002
        service_type: str,  # noqa: ARG002
        name: str,
    ) -> None:
        """Called when a service is removed."""
        if name in self._units:
            del self._units[name]

    def update_service(
        self,
        zc: Zeroconf,  # noqa: ARG002
        service_type: str,
        name: str,
    ) -> None:
        """Called when a service is updated."""
        self._create_resolve_task(service_type, name)

    async def _resolve_service(self, service_type: str, name: str) -> None:
        """Resolve service info and add to units if it's an IntelliCenter."""
        try:
            info: ServiceInfo | None = await self._aiozc.async_get_service_info(service_type, name)
            if info is None:
                return

            # Check if this is a Pentair/IntelliCenter device
            service_name = info.name or name
            if not self._is_intellicenter(service_name, info):
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
            self._units[name] = unit
            self._event.set()
            _LOGGER.debug("Discovered IntelliCenter: %s at %s:%d", service_name, host, port)

        except Exception:
            _LOGGER.exception("Error resolving service %s", name)

    def _is_intellicenter(self, name: str, info: ServiceInfo) -> bool:
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

    aiozc = AsyncZeroconf()
    listener = ICDiscoveryListener(aiozc)

    try:
        # Browse for HTTP services (IntelliCenter uses HTTP on port 6681)
        ServiceBrowser(aiozc.zeroconf, INTELLICENTER_SERVICE_TYPE, listener)  # type: ignore[arg-type]

        # Also try to browse for any specific IntelliCenter service types
        # that Pentair may register
        with contextlib.suppress(Exception):
            ServiceBrowser(aiozc.zeroconf, "_pentair._tcp.local.", listener)  # type: ignore[arg-type]

        # Wait for discovery
        await asyncio.sleep(discovery_timeout)

        return listener.units

    finally:
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
