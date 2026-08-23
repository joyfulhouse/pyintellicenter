"""Tests for pyintellicenter discovery module."""

import asyncio
import time
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from zeroconf import ServiceStateChange

from pyintellicenter.discovery import (
    DEFAULT_DISCOVERY_TIMEOUT,
    INTELLICENTER_SERVICE_TYPE,
    ICDiscoveryListener,
    ICUnit,
    _is_intellicenter,
    _resolve_service,
    discover_intellicenter_units,
    find_unit_by_host,
    find_unit_by_name,
)

HTTP_TYPE = INTELLICENTER_SERVICE_TYPE
PENTAIR_NAME = "Pentair: i10PS._http._tcp.local."
DECOY_NAME = "Living Room TV._http._tcp.local."


class FakeAsyncServiceBrowser:
    """Stand-in for zeroconf.asyncio.AsyncServiceBrowser used in tests."""

    def __init__(self, zeroconf, type_, handlers=None, **kwargs):
        self.zeroconf = zeroconf
        self.type_ = type_
        self.handlers = list(handlers or [])
        self.cancelled = False

    async def async_cancel(self):
        self.cancelled = True

    def fire(self, service_type, name, state_change):
        """Invoke registered handlers the way zeroconf does (kwargs, on loop)."""
        for handler in self.handlers:
            handler(
                zeroconf=self.zeroconf,
                service_type=service_type,
                name=name,
                state_change=state_change,
            )


def _browser_factory(created):
    """Return an AsyncServiceBrowser factory recording created instances."""

    def factory(*args, **kwargs):
        browser = FakeAsyncServiceBrowser(*args, **kwargs)
        created.append(browser)
        return browser

    return factory


def _make_fake_info_cls(delays=None, addresses=None):
    """Build a fake AsyncServiceInfo class resolving with optional per-name delay."""

    class FakeServiceInfo:
        def __init__(self, service_type, name):
            self.type = service_type
            self.name = name
            self.port = 6680
            self.properties = {}

        async def async_request(self, zc, timeout_ms):
            delay = (delays or {}).get(self.name, 0.0)
            if delay:
                await asyncio.sleep(delay)
            return True

        def parsed_scoped_addresses(self):
            return list(addresses or ["192.168.1.50"])

    return FakeServiceInfo


class TestICUnit:
    """Test ICUnit dataclass."""

    def test_init(self):
        """Test ICUnit creation."""
        unit = ICUnit(name="Pentair Pool", host="192.168.1.100", port=6681, ws_port=6680)

        assert unit.name == "Pentair Pool"
        assert unit.host == "192.168.1.100"
        assert unit.port == 6681
        assert unit.ws_port == 6680
        assert unit.model is None

    def test_init_with_model(self):
        """Test ICUnit creation with model."""
        unit = ICUnit(
            name="Pentair Pool",
            host="192.168.1.100",
            port=6681,
            ws_port=6680,
            model="IntelliCenter",
        )

        assert unit.model == "IntelliCenter"

    def test_repr(self):
        """Test ICUnit repr."""
        unit = ICUnit(name="Pentair Pool", host="192.168.1.100", port=6681, ws_port=6680)
        repr_str = repr(unit)

        assert "ICUnit" in repr_str
        assert "Pentair Pool" in repr_str
        assert "192.168.1.100" in repr_str
        assert "6681" in repr_str
        assert "6680" in repr_str

    def test_frozen(self):
        """Test ICUnit is immutable."""
        unit = ICUnit(name="Pentair Pool", host="192.168.1.100", port=6681, ws_port=6680)

        with pytest.raises(AttributeError):
            unit.name = "New Name"  # type: ignore[misc]


class TestICDiscoveryListener:
    """Test ICDiscoveryListener async state-change handling."""

    @pytest.fixture
    def listener(self):
        """Create listener instance."""
        return ICDiscoveryListener()

    def test_init(self, listener):
        """Test listener initialization."""
        assert listener.units == []

    def test_units_property(self, listener):
        """Test units property returns list copy."""
        units1 = listener.units
        units2 = listener.units
        assert units1 is not units2

    @pytest.mark.asyncio
    async def test_added_event_queues_candidate(self, listener):
        """Test an Added state change queues a candidate for resolution."""
        mock_zc = MagicMock()
        listener.async_on_service_state_change(
            zeroconf=mock_zc,
            service_type=HTTP_TYPE,
            name=PENTAIR_NAME,
            state_change=ServiceStateChange.Added,
        )

        zc, service_type, name = await asyncio.wait_for(listener.async_get_candidate(), 1.0)
        assert zc is mock_zc
        assert service_type == HTTP_TYPE
        assert name == PENTAIR_NAME

    @pytest.mark.asyncio
    async def test_updated_event_queues_candidate(self, listener):
        """Test an Updated state change queues a candidate for resolution."""
        mock_zc = MagicMock()
        listener.async_on_service_state_change(
            zeroconf=mock_zc,
            service_type=HTTP_TYPE,
            name=PENTAIR_NAME,
            state_change=ServiceStateChange.Updated,
        )

        zc, service_type, name = await asyncio.wait_for(listener.async_get_candidate(), 1.0)
        assert zc is mock_zc
        assert service_type == HTTP_TYPE
        assert name == PENTAIR_NAME

    def test_added_then_updated_deduplicated(self, listener):
        """Test Added followed by Updated only queues one candidate."""
        mock_zc = MagicMock()
        for state_change in (
            ServiceStateChange.Added,
            ServiceStateChange.Updated,
            ServiceStateChange.Added,
        ):
            listener.async_on_service_state_change(
                zeroconf=mock_zc,
                service_type=HTTP_TYPE,
                name=PENTAIR_NAME,
                state_change=state_change,
            )

        assert listener._candidates.qsize() == 1

    def test_removed_event_drops_unit(self, listener):
        """Test a Removed state change removes a discovered unit."""
        unit = ICUnit(name="Pentair", host="192.168.1.100", port=6681, ws_port=6680)
        listener.add_unit(PENTAIR_NAME, unit)

        listener.async_on_service_state_change(
            zeroconf=MagicMock(),
            service_type=HTTP_TYPE,
            name=PENTAIR_NAME,
            state_change=ServiceStateChange.Removed,
        )

        assert listener.units == []

    def test_removed_event_unknown_service(self, listener):
        """Test a Removed state change for an unknown service does not raise."""
        listener.async_on_service_state_change(
            zeroconf=MagicMock(),
            service_type=HTTP_TYPE,
            name="Unknown._http._tcp.local.",
            state_change=ServiceStateChange.Removed,
        )

        assert listener.units == []

    def test_removed_then_added_requeues_candidate(self, listener):
        """Test a service re-added after removal is queued for resolution again."""
        mock_zc = MagicMock()
        listener.async_on_service_state_change(
            zeroconf=mock_zc,
            service_type=HTTP_TYPE,
            name=PENTAIR_NAME,
            state_change=ServiceStateChange.Added,
        )
        listener.async_on_service_state_change(
            zeroconf=mock_zc,
            service_type=HTTP_TYPE,
            name=PENTAIR_NAME,
            state_change=ServiceStateChange.Removed,
        )
        listener.async_on_service_state_change(
            zeroconf=mock_zc,
            service_type=HTTP_TYPE,
            name=PENTAIR_NAME,
            state_change=ServiceStateChange.Added,
        )

        assert listener._candidates.qsize() == 2

    def test_add_unit(self, listener):
        """Test add_unit adds a unit."""
        unit = ICUnit(name="Pentair Pool", host="192.168.1.100", port=6681, ws_port=6680)
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


class TestResolveService:
    """Test _resolve_service resolution behavior."""

    @pytest.mark.asyncio
    async def test_resolve_uses_scoped_addresses(self):
        """Test resolution uses parsed_scoped_addresses (IPv6 scope id preserved)."""
        listener = ICDiscoveryListener()
        info = MagicMock()
        info.name = PENTAIR_NAME
        info.port = 6680
        info.properties = {}
        info.async_request = AsyncMock(return_value=True)
        info.parsed_scoped_addresses.return_value = ["fe80::1%en0"]
        # parsed_addresses strips the scope id and must NOT be used
        info.parsed_addresses.return_value = ["fe80::1"]

        with (
            patch("pyintellicenter.discovery.AsyncServiceInfo", return_value=info),
            patch(
                "pyintellicenter.discovery._check_tcp_port",
                new_callable=AsyncMock,
                return_value=True,
            ) as mock_probe,
        ):
            await _resolve_service(
                listener, MagicMock(), asyncio.Semaphore(1), HTTP_TYPE, PENTAIR_NAME
            )

        mock_probe.assert_awaited_once_with("fe80::1%en0", 6681)
        info.parsed_addresses.assert_not_called()
        assert len(listener.units) == 1
        assert listener.units[0].host == "fe80::1%en0"

    @pytest.mark.asyncio
    async def test_resolve_extracts_model(self):
        """Test resolution extracts model from service properties."""
        listener = ICDiscoveryListener()
        info = MagicMock()
        info.name = PENTAIR_NAME
        info.port = 6680
        info.properties = {b"model": b"i10PS"}
        info.async_request = AsyncMock(return_value=True)
        info.parsed_scoped_addresses.return_value = ["192.168.1.50"]

        with (
            patch("pyintellicenter.discovery.AsyncServiceInfo", return_value=info),
            patch(
                "pyintellicenter.discovery._check_tcp_port",
                new_callable=AsyncMock,
                return_value=True,
            ),
        ):
            await _resolve_service(
                listener, MagicMock(), asyncio.Semaphore(1), HTTP_TYPE, PENTAIR_NAME
            )

        assert listener.units[0].model == "i10PS"
        assert listener.units[0].port == 6681
        assert listener.units[0].ws_port == 6680

    @pytest.mark.asyncio
    async def test_resolve_skips_unresolved_service(self):
        """Test a service that fails to resolve is not added."""
        listener = ICDiscoveryListener()
        info = MagicMock()
        info.async_request = AsyncMock(return_value=False)

        with patch("pyintellicenter.discovery.AsyncServiceInfo", return_value=info):
            await _resolve_service(
                listener, MagicMock(), asyncio.Semaphore(1), HTTP_TYPE, PENTAIR_NAME
            )

        assert listener.units == []

    @pytest.mark.asyncio
    async def test_resolve_skips_non_intellicenter(self):
        """Test a non-IntelliCenter service is filtered out."""
        listener = ICDiscoveryListener()
        info = MagicMock()
        info.name = DECOY_NAME
        info.port = 8080
        info.properties = {}
        info.async_request = AsyncMock(return_value=True)
        info.parsed_scoped_addresses.return_value = ["192.168.1.60"]

        with patch("pyintellicenter.discovery.AsyncServiceInfo", return_value=info):
            await _resolve_service(
                listener, MagicMock(), asyncio.Semaphore(1), HTTP_TYPE, DECOY_NAME
            )

        assert listener.units == []

    @pytest.mark.asyncio
    async def test_resolve_skips_unreachable_tcp_port(self):
        """Test a unit whose TCP port probe fails is not added."""
        listener = ICDiscoveryListener()
        info = MagicMock()
        info.name = PENTAIR_NAME
        info.port = 6680
        info.properties = {}
        info.async_request = AsyncMock(return_value=True)
        info.parsed_scoped_addresses.return_value = ["192.168.1.50"]

        with (
            patch("pyintellicenter.discovery.AsyncServiceInfo", return_value=info),
            patch(
                "pyintellicenter.discovery._check_tcp_port",
                new_callable=AsyncMock,
                return_value=False,
            ),
        ):
            await _resolve_service(
                listener, MagicMock(), asyncio.Semaphore(1), HTTP_TYPE, PENTAIR_NAME
            )

        assert listener.units == []


class TestDiscoverIntellicenterUnits:
    """Test discover_intellicenter_units function."""

    @pytest.mark.asyncio
    async def test_discover_success(self):
        """Test successful discovery with an owned Zeroconf instance."""
        created = []
        mock_aiozc = MagicMock()
        mock_aiozc.zeroconf = MagicMock()
        mock_aiozc.async_close = AsyncMock()

        with (
            patch("pyintellicenter.discovery.AsyncZeroconf", return_value=mock_aiozc),
            patch(
                "pyintellicenter.discovery.AsyncServiceBrowser",
                side_effect=_browser_factory(created),
            ),
        ):
            units = await discover_intellicenter_units(discovery_timeout=0.05)

        assert isinstance(units, list)
        assert created, "expected at least one AsyncServiceBrowser"

    @pytest.mark.asyncio
    async def test_discover_uses_async_service_browser_handlers(self):
        """Test discovery registers async state-change handlers (no threaded listener)."""
        created = []
        mock_aiozc = MagicMock()
        mock_aiozc.zeroconf = MagicMock()
        mock_aiozc.async_close = AsyncMock()

        with (
            patch("pyintellicenter.discovery.AsyncZeroconf", return_value=mock_aiozc),
            patch(
                "pyintellicenter.discovery.AsyncServiceBrowser",
                side_effect=_browser_factory(created),
            ),
        ):
            await discover_intellicenter_units(discovery_timeout=0.05)

        assert any(HTTP_TYPE in browser.type_ for browser in created)
        for browser in created:
            assert browser.handlers, "browser must be created with state-change handlers"

    @pytest.mark.asyncio
    async def test_discover_finds_unit_from_events(self):
        """Test a full discovery pass driven by browser events."""
        created = []
        fake_info_cls = _make_fake_info_cls()

        with (
            patch(
                "pyintellicenter.discovery.AsyncServiceBrowser",
                side_effect=_browser_factory(created),
            ),
            patch("pyintellicenter.discovery.AsyncServiceInfo", fake_info_cls),
            patch(
                "pyintellicenter.discovery._check_tcp_port",
                new_callable=AsyncMock,
                return_value=True,
            ),
        ):
            task = asyncio.create_task(
                discover_intellicenter_units(discovery_timeout=0.3, zeroconf=MagicMock())
            )
            await asyncio.sleep(0)
            assert created
            created[0].fire(HTTP_TYPE, PENTAIR_NAME, ServiceStateChange.Added)
            units = await task

        assert len(units) == 1
        assert units[0].name == PENTAIR_NAME
        assert units[0].port == 6681
        assert units[0].ws_port == 6680

    @pytest.mark.asyncio
    async def test_discover_closes_owned_zeroconf(self):
        """Test discovery closes an AsyncZeroconf instance it created."""
        created = []
        mock_aiozc = MagicMock()
        mock_aiozc.zeroconf = MagicMock()
        mock_aiozc.async_close = AsyncMock()

        with (
            patch("pyintellicenter.discovery.AsyncZeroconf", return_value=mock_aiozc),
            patch(
                "pyintellicenter.discovery.AsyncServiceBrowser",
                side_effect=_browser_factory(created),
            ),
        ):
            await discover_intellicenter_units(discovery_timeout=0.05)

        mock_aiozc.async_close.assert_called_once()

    @pytest.mark.asyncio
    async def test_discover_closes_owned_zeroconf_on_error(self):
        """Test discovery closes an owned AsyncZeroconf even when browsing fails."""
        mock_aiozc = MagicMock()
        mock_aiozc.zeroconf = MagicMock()
        mock_aiozc.async_close = AsyncMock()

        with (
            patch("pyintellicenter.discovery.AsyncZeroconf", return_value=mock_aiozc),
            patch(
                "pyintellicenter.discovery.AsyncServiceBrowser",
                side_effect=RuntimeError("browse failed"),
            ),
            pytest.raises(RuntimeError),
        ):
            await discover_intellicenter_units(discovery_timeout=0.05)

        mock_aiozc.async_close.assert_called_once()

    @pytest.mark.asyncio
    async def test_discover_never_closes_borrowed_zeroconf(self):
        """Regression #53: a caller-provided Zeroconf must never be closed."""
        created = []
        borrowed = MagicMock()

        with (
            patch("pyintellicenter.discovery.AsyncZeroconf") as mock_aiozc_cls,
            patch(
                "pyintellicenter.discovery.AsyncServiceBrowser",
                side_effect=_browser_factory(created),
            ),
        ):
            units = await discover_intellicenter_units(discovery_timeout=0.05, zeroconf=borrowed)

        assert units == []
        # Never wrapped in an owned AsyncZeroconf, never closed in any form.
        mock_aiozc_cls.assert_not_called()
        borrowed.close.assert_not_called()
        borrowed._async_close.assert_not_called()
        borrowed.async_close.assert_not_called()
        # Browsers on the borrowed instance are still torn down.
        assert created
        assert all(browser.cancelled for browser in created)

    @pytest.mark.asyncio
    async def test_discover_never_closes_borrowed_zeroconf_on_error(self):
        """Regression #53: a caller-provided Zeroconf survives a discovery failure."""
        borrowed = MagicMock()

        with (
            patch("pyintellicenter.discovery.AsyncZeroconf") as mock_aiozc_cls,
            patch(
                "pyintellicenter.discovery.AsyncServiceBrowser",
                side_effect=RuntimeError("browse failed"),
            ),
            pytest.raises(RuntimeError),
        ):
            await discover_intellicenter_units(discovery_timeout=0.05, zeroconf=borrowed)

        mock_aiozc_cls.assert_not_called()
        borrowed.close.assert_not_called()
        borrowed._async_close.assert_not_called()
        borrowed.async_close.assert_not_called()

    @pytest.mark.asyncio
    async def test_discover_cancels_browsers(self):
        """Test discovery cancels browsers on completion without blocking the loop."""
        created = []
        mock_aiozc = MagicMock()
        mock_aiozc.zeroconf = MagicMock()
        mock_aiozc.async_close = AsyncMock()

        with (
            patch("pyintellicenter.discovery.AsyncZeroconf", return_value=mock_aiozc),
            patch(
                "pyintellicenter.discovery.AsyncServiceBrowser",
                side_effect=_browser_factory(created),
            ),
        ):
            await discover_intellicenter_units(discovery_timeout=0.05)

        assert created
        assert all(browser.cancelled for browser in created)

    @pytest.mark.asyncio
    async def test_discover_concurrent_resolution_with_slow_decoy(self):
        """Regression #54: a slow non-Pentair service must not starve the real unit.

        The decoy is reported first and takes far longer than the discovery
        window to resolve; with concurrent bounded resolution the Pentair unit
        is still found and the overall deadline is respected.
        """
        created = []
        fake_info_cls = _make_fake_info_cls(delays={DECOY_NAME: 30.0})

        with (
            patch(
                "pyintellicenter.discovery.AsyncServiceBrowser",
                side_effect=_browser_factory(created),
            ),
            patch("pyintellicenter.discovery.AsyncServiceInfo", fake_info_cls),
            patch(
                "pyintellicenter.discovery._check_tcp_port",
                new_callable=AsyncMock,
                return_value=True,
            ),
        ):
            start = time.monotonic()
            task = asyncio.create_task(
                discover_intellicenter_units(discovery_timeout=0.5, zeroconf=MagicMock())
            )
            await asyncio.sleep(0)
            assert created
            # Slow decoy is discovered before the Pentair unit.
            created[0].fire(HTTP_TYPE, DECOY_NAME, ServiceStateChange.Added)
            created[0].fire(HTTP_TYPE, PENTAIR_NAME, ServiceStateChange.Added)
            units = await task
            elapsed = time.monotonic() - start

        assert [unit.name for unit in units] == [PENTAIR_NAME]
        # Deadline respected: nowhere near the decoy's 30s resolution time.
        assert elapsed < 3.0

    @pytest.mark.asyncio
    async def test_discover_deduplicates_add_and_update_events(self):
        """Test repeated add/update events resolve a service only once."""
        created = []
        resolved = []

        class CountingServiceInfo:
            def __init__(self, service_type, name):
                self.type = service_type
                self.name = name
                self.port = 6680
                self.properties = {}

            async def async_request(self, zc, timeout_ms):
                resolved.append(self.name)
                return True

            def parsed_scoped_addresses(self):
                return ["192.168.1.50"]

        with (
            patch(
                "pyintellicenter.discovery.AsyncServiceBrowser",
                side_effect=_browser_factory(created),
            ),
            patch("pyintellicenter.discovery.AsyncServiceInfo", CountingServiceInfo),
            patch(
                "pyintellicenter.discovery._check_tcp_port",
                new_callable=AsyncMock,
                return_value=True,
            ),
        ):
            task = asyncio.create_task(
                discover_intellicenter_units(discovery_timeout=0.3, zeroconf=MagicMock())
            )
            await asyncio.sleep(0)
            assert created
            created[0].fire(HTTP_TYPE, PENTAIR_NAME, ServiceStateChange.Added)
            created[0].fire(HTTP_TYPE, PENTAIR_NAME, ServiceStateChange.Updated)
            created[0].fire(HTTP_TYPE, PENTAIR_NAME, ServiceStateChange.Added)
            units = await task

        assert resolved == [PENTAIR_NAME]
        assert len(units) == 1


class TestFindUnitByName:
    """Test find_unit_by_name function."""

    @pytest.mark.asyncio
    async def test_find_by_name_found(self):
        """Test finding unit by name."""
        mock_units = [
            ICUnit(name="Pentair Pool", host="192.168.1.100", port=6681, ws_port=6680),
            ICUnit(name="Other Device", host="192.168.1.101", port=80, ws_port=79),
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
            ICUnit(name="Other Device", host="192.168.1.101", port=80, ws_port=79),
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
            ICUnit(name="PENTAIR Pool", host="192.168.1.100", port=6681, ws_port=6680),
        ]

        with patch(
            "pyintellicenter.discovery.discover_intellicenter_units",
            new_callable=AsyncMock,
            return_value=mock_units,
        ):
            unit = await find_unit_by_name("pentair")

            assert unit is not None
            assert unit.name == "PENTAIR Pool"

    @pytest.mark.asyncio
    async def test_find_by_name_passes_zeroconf_through(self):
        """Regression #54: find_unit_by_name must forward a shared Zeroconf instance."""
        borrowed = MagicMock()

        with patch(
            "pyintellicenter.discovery.discover_intellicenter_units",
            new_callable=AsyncMock,
            return_value=[],
        ) as mock_discover:
            unit = await find_unit_by_name("Pentair", discovery_timeout=2.0, zeroconf=borrowed)

        assert unit is None
        mock_discover.assert_awaited_once_with(discovery_timeout=2.0, zeroconf=borrowed)


class TestFindUnitByHost:
    """Test find_unit_by_host function."""

    @pytest.mark.asyncio
    async def test_find_by_host_found(self):
        """Test finding unit by host."""
        mock_units = [
            ICUnit(name="Pentair Pool", host="192.168.1.100", port=6681, ws_port=6680),
            ICUnit(name="Other Device", host="192.168.1.101", port=80, ws_port=79),
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
            ICUnit(name="Other Device", host="192.168.1.101", port=80, ws_port=79),
        ]

        with patch(
            "pyintellicenter.discovery.discover_intellicenter_units",
            new_callable=AsyncMock,
            return_value=mock_units,
        ):
            unit = await find_unit_by_host("192.168.1.100")

            assert unit is None

    @pytest.mark.asyncio
    async def test_find_by_host_passes_zeroconf_through(self):
        """Regression #54: find_unit_by_host must forward a shared Zeroconf instance."""
        borrowed = MagicMock()

        with patch(
            "pyintellicenter.discovery.discover_intellicenter_units",
            new_callable=AsyncMock,
            return_value=[],
        ) as mock_discover:
            unit = await find_unit_by_host(
                "192.168.1.100", discovery_timeout=2.0, zeroconf=borrowed
            )

        assert unit is None
        mock_discover.assert_awaited_once_with(discovery_timeout=2.0, zeroconf=borrowed)


class TestDefaultTimeout:
    """Test default discovery timeout."""

    def test_default_timeout_value(self):
        """Test default timeout is reasonable."""
        assert DEFAULT_DISCOVERY_TIMEOUT == 10.0
