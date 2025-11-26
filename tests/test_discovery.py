"""Tests for pyintellicenter discovery module."""

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from pyintellicenter.discovery import (
    DEFAULT_DISCOVERY_TIMEOUT,
    ICDiscoveryListener,
    ICUnit,
    _is_intellicenter,
    discover_intellicenter_units,
    find_unit_by_host,
    find_unit_by_name,
)


class TestICUnit:
    """Test ICUnit dataclass."""

    def test_init(self):
        """Test ICUnit creation."""
        unit = ICUnit(name="Pentair Pool", host="192.168.1.100", port=6681)

        assert unit.name == "Pentair Pool"
        assert unit.host == "192.168.1.100"
        assert unit.port == 6681
        assert unit.model is None

    def test_init_with_model(self):
        """Test ICUnit creation with model."""
        unit = ICUnit(name="Pentair Pool", host="192.168.1.100", port=6681, model="IntelliCenter")

        assert unit.model == "IntelliCenter"

    def test_repr(self):
        """Test ICUnit repr."""
        unit = ICUnit(name="Pentair Pool", host="192.168.1.100", port=6681)
        repr_str = repr(unit)

        assert "ICUnit" in repr_str
        assert "Pentair Pool" in repr_str
        assert "192.168.1.100" in repr_str
        assert "6681" in repr_str

    def test_frozen(self):
        """Test ICUnit is immutable."""
        unit = ICUnit(name="Pentair Pool", host="192.168.1.100", port=6681)

        with pytest.raises(AttributeError):
            unit.name = "New Name"  # type: ignore[misc]


class TestICDiscoveryListener:
    """Test ICDiscoveryListener class."""

    @pytest.fixture
    def queue(self):
        """Create async queue."""
        return asyncio.Queue(maxsize=100)

    @pytest.fixture
    def listener(self, queue):
        """Create listener instance."""
        return ICDiscoveryListener(queue)

    def test_init(self, listener):
        """Test listener initialization."""
        assert listener.units == []

    def test_units_property(self, listener):
        """Test units property returns list copy."""
        units1 = listener.units
        units2 = listener.units
        assert units1 is not units2

    @pytest.mark.asyncio
    async def test_add_service_queues_event(self, listener, queue):
        """Test add_service queues an event."""
        mock_zc = MagicMock()
        listener.add_service(mock_zc, "_http._tcp.local.", "Pentair._http._tcp.local.")

        action, service_type, name = queue.get_nowait()
        assert action == "add"
        assert service_type == "_http._tcp.local."
        assert name == "Pentair._http._tcp.local."

    def test_remove_service(self, listener):
        """Test remove_service removes unit."""
        # Manually add a unit
        unit = ICUnit(name="Pentair", host="192.168.1.100", port=6681)
        listener._units["Pentair._http._tcp.local."] = unit

        mock_zc = MagicMock()
        listener.remove_service(mock_zc, "_http._tcp.local.", "Pentair._http._tcp.local.")

        assert "Pentair._http._tcp.local." not in listener._units

    def test_remove_service_not_found(self, listener):
        """Test remove_service with non-existent service."""
        mock_zc = MagicMock()
        # Should not raise
        listener.remove_service(mock_zc, "_http._tcp.local.", "Unknown._http._tcp.local.")

    @pytest.mark.asyncio
    async def test_update_service_queues_event(self, listener, queue):
        """Test update_service queues an event."""
        mock_zc = MagicMock()
        listener.update_service(mock_zc, "_http._tcp.local.", "Pentair._http._tcp.local.")

        action, service_type, name = queue.get_nowait()
        assert action == "update"
        assert service_type == "_http._tcp.local."
        assert name == "Pentair._http._tcp.local."

    def test_add_unit(self, listener):
        """Test add_unit adds a unit."""
        unit = ICUnit(name="Pentair Pool", host="192.168.1.100", port=6681)
        listener.add_unit("test_key", unit)

        assert len(listener.units) == 1
        assert listener.units[0] == unit


class TestIsIntelliCenter:
    """Test _is_intellicenter function."""

    def test_is_intellicenter_by_name_pentair(self):
        """Test _is_intellicenter with Pentair in name."""
        mock_info = MagicMock()
        mock_info.properties = {}

        assert _is_intellicenter("Pentair Pool Controller", mock_info) is True

    def test_is_intellicenter_by_name_intellicenter(self):
        """Test _is_intellicenter with IntelliCenter in name."""
        mock_info = MagicMock()
        mock_info.properties = {}

        assert _is_intellicenter("My IntelliCenter", mock_info) is True

    def test_is_intellicenter_by_property_key(self):
        """Test _is_intellicenter with Pentair in property key."""
        mock_info = MagicMock()
        mock_info.properties = {b"pentair_model": b"something"}

        assert _is_intellicenter("Generic Device", mock_info) is True

    def test_is_intellicenter_by_property_value(self):
        """Test _is_intellicenter with Pentair in property value."""
        mock_info = MagicMock()
        mock_info.properties = {b"manufacturer": b"Pentair Water"}

        assert _is_intellicenter("Generic Device", mock_info) is True

    def test_is_intellicenter_false(self):
        """Test _is_intellicenter returns False for non-IntelliCenter."""
        mock_info = MagicMock()
        mock_info.properties = {b"manufacturer": b"SomeOtherCompany"}

        assert _is_intellicenter("Generic Device", mock_info) is False

    def test_is_intellicenter_none_value_in_properties(self):
        """Test _is_intellicenter handles None values in properties."""
        mock_info = MagicMock()
        mock_info.properties = {b"key": None}

        # Should not raise
        result = _is_intellicenter("Generic Device", mock_info)
        assert result is False


class TestDiscoverIntellicenterUnits:
    """Test discover_intellicenter_units function."""

    @pytest.mark.asyncio
    async def test_discover_success(self):
        """Test successful discovery."""
        mock_browser = MagicMock()
        mock_aiozc = MagicMock()
        mock_aiozc.zeroconf = MagicMock()
        mock_aiozc.async_close = AsyncMock()
        mock_aiozc.async_get_service_info = AsyncMock(return_value=None)

        with (
            patch("zeroconf.asyncio.AsyncZeroconf", return_value=mock_aiozc),
            patch("zeroconf.ServiceBrowser", return_value=mock_browser),
        ):
            units = await discover_intellicenter_units(discovery_timeout=0.1)

            assert isinstance(units, list)

    @pytest.mark.asyncio
    async def test_discover_closes_zeroconf(self):
        """Test discovery closes AsyncZeroconf on completion."""
        mock_browser = MagicMock()
        mock_aiozc = MagicMock()
        mock_aiozc.zeroconf = MagicMock()
        mock_aiozc.async_close = AsyncMock()
        mock_aiozc.async_get_service_info = AsyncMock(return_value=None)

        with (
            patch("zeroconf.asyncio.AsyncZeroconf", return_value=mock_aiozc),
            patch("zeroconf.ServiceBrowser", return_value=mock_browser),
        ):
            await discover_intellicenter_units(discovery_timeout=0.1)

            mock_aiozc.async_close.assert_called_once()

    @pytest.mark.asyncio
    async def test_discover_cancels_browsers(self):
        """Test discovery cancels browsers before closing."""
        mock_browser = MagicMock()
        mock_aiozc = MagicMock()
        mock_aiozc.zeroconf = MagicMock()
        mock_aiozc.async_close = AsyncMock()
        mock_aiozc.async_get_service_info = AsyncMock(return_value=None)

        with (
            patch("zeroconf.asyncio.AsyncZeroconf", return_value=mock_aiozc),
            patch("zeroconf.ServiceBrowser", return_value=mock_browser),
        ):
            await discover_intellicenter_units(discovery_timeout=0.1)

            mock_browser.cancel.assert_called()


class TestFindUnitByName:
    """Test find_unit_by_name function."""

    @pytest.mark.asyncio
    async def test_find_by_name_found(self):
        """Test finding unit by name."""
        mock_units = [
            ICUnit(name="Pentair Pool", host="192.168.1.100", port=6681),
            ICUnit(name="Other Device", host="192.168.1.101", port=80),
        ]

        with patch(
            "pyintellicenter.discovery.discover_intellicenter_units",
            new_callable=AsyncMock,
            return_value=mock_units,
        ):
            unit = await find_unit_by_name("Pentair")

            assert unit is not None
            assert unit.name == "Pentair Pool"

    @pytest.mark.asyncio
    async def test_find_by_name_not_found(self):
        """Test finding unit by name when not found."""
        mock_units = [
            ICUnit(name="Other Device", host="192.168.1.101", port=80),
        ]

        with patch(
            "pyintellicenter.discovery.discover_intellicenter_units",
            new_callable=AsyncMock,
            return_value=mock_units,
        ):
            unit = await find_unit_by_name("Pentair")

            assert unit is None

    @pytest.mark.asyncio
    async def test_find_by_name_case_insensitive(self):
        """Test find_unit_by_name is case insensitive."""
        mock_units = [
            ICUnit(name="PENTAIR Pool", host="192.168.1.100", port=6681),
        ]

        with patch(
            "pyintellicenter.discovery.discover_intellicenter_units",
            new_callable=AsyncMock,
            return_value=mock_units,
        ):
            unit = await find_unit_by_name("pentair")

            assert unit is not None
            assert unit.name == "PENTAIR Pool"


class TestFindUnitByHost:
    """Test find_unit_by_host function."""

    @pytest.mark.asyncio
    async def test_find_by_host_found(self):
        """Test finding unit by host."""
        mock_units = [
            ICUnit(name="Pentair Pool", host="192.168.1.100", port=6681),
            ICUnit(name="Other Device", host="192.168.1.101", port=80),
        ]

        with patch(
            "pyintellicenter.discovery.discover_intellicenter_units",
            new_callable=AsyncMock,
            return_value=mock_units,
        ):
            unit = await find_unit_by_host("192.168.1.100")

            assert unit is not None
            assert unit.host == "192.168.1.100"

    @pytest.mark.asyncio
    async def test_find_by_host_not_found(self):
        """Test finding unit by host when not found."""
        mock_units = [
            ICUnit(name="Other Device", host="192.168.1.101", port=80),
        ]

        with patch(
            "pyintellicenter.discovery.discover_intellicenter_units",
            new_callable=AsyncMock,
            return_value=mock_units,
        ):
            unit = await find_unit_by_host("192.168.1.100")

            assert unit is None


class TestDefaultTimeout:
    """Test default discovery timeout."""

    def test_default_timeout_value(self):
        """Test default timeout is reasonable."""
        assert DEFAULT_DISCOVERY_TIMEOUT == 10.0
