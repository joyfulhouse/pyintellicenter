# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

## [0.0.5a10] - 2025-11-27

### Added

- **Dual transport support**: Both TCP and WebSocket transports are now supported
  - `ICConnection` accepts `transport` parameter: `"tcp"` (default) or `"websocket"`
  - Default ports: TCP=6681, WebSocket=6680
  - Custom port overrides default when specified
  - `ICWebSocketTransport` class for WebSocket connections
  - `ICTransportProtocol` interface for transport abstraction
  - `TransportType` literal type for type-safe transport selection
  - New constants: `DEFAULT_TCP_PORT`, `DEFAULT_WEBSOCKET_PORT`

### Changed

- **websockets is now a required dependency** (was optional)
  - Enables runtime transport selection for Home Assistant integration
  - No need for optional extras to use WebSocket transport

### Fixed

- Added diagnostic logging for notification queue race conditions

## [0.0.5a9] - 2025-11-27

### Added

- **Queue-based notification processing**: Push notifications are now processed through an async queue
  - Prevents slow callbacks from blocking the event loop
  - Bounded queue with backpressure handling (default: 100 items)
  - Graceful degradation when queue is full (drops oldest, logs warning)

- **Home Assistant convenience helpers** on `ICModelController`:
  - **Light helpers**: `get_lights()`, `get_color_lights()`, `set_light_effect()`, `get_light_effect()`, `get_light_effect_name()`, `get_available_light_effects()`
  - **Temperature helpers**: `get_temperature_unit()`, `get_body_temperature()`, `get_body_setpoint()`, `get_body_heat_mode()`, `is_body_heating()`
  - **Chemistry helpers**: `get_chem_reading()`, `get_chem_alerts()`, `has_chem_alert()`
  - **Sensor helpers**: `get_sensors_by_type()`, `get_solar_sensors()`, `get_air_sensors()`, `get_pool_temp_sensors()`, `get_sensor_reading()`
  - **Pump helpers**: `is_pump_running()`, `get_pump_rpm()`, `get_pump_gpm()`, `get_pump_watts()`, `get_pump_metrics()`
  - **Discovery helpers**: `get_valves()`, `get_all_entities()`, `get_featured_entities()`

### Changed

- **Callback type caching**: `inspect.iscoroutinefunction()` result is now cached at callback setup time
- **Efficient buffer handling**: Changed from `bytes` to `bytearray` for receive buffer (in-place operations)
- Callbacks can now be set after connection is established (consumer task starts lazily)

### Fixed

- Notification callbacks no longer block `data_received()` in the event loop

## [0.0.5a5] - 2025-11-26

### Changed

- **ICConnectionHandler.start()**: Now waits for first connection attempt before returning
  - Raises exception if first connection fails (enables proper error handling in Home Assistant)
  - Reconnection continues in background after first failure

## [0.0.5a4] - 2025-11-26

### Added

- **Shared Zeroconf support**: `discover_intellicenter_units()` now accepts optional `zeroconf` parameter to use an existing Zeroconf instance (for Home Assistant integration)

## [0.0.5a3] - 2025-11-26

### Fixed

- **Dependency compatibility**: Relax orjson requirement to >=3.10.0 for Home Assistant compatibility

## [0.0.5a2] - 2025-11-26

### Added

- **USER_PRIVILEGES export**: Now exported from main module for consistency with attributes submodule

### Removed

- **Dead code cleanup**: Removed unused `_system_object` from `PoolModel` class
- **Redundant method**: Removed `send_command()` alias method from `ICConnection` (use `send_request()` directly)

### Changed

- Code review and modernization pass confirming all async patterns are up-to-date

## [0.0.5a1] - 2025-11-26

### Added

- **LIGHT_EFFECTS constant**: Protocol-level mapping of IntelliCenter color effect codes to human-readable names
  - Codes: PARTY, CARIB, SSET, ROMAN, AMERCA, ROYAL, WHITER, REDR, BLUER, GREENR, MAGNTAR
  - Used with the `USE` attribute on lights with `COLOR_EFFECT_SUBTYPES`
  - Enables Home Assistant integrations to import effect mappings directly from the library

## [0.0.4] - 2025-11-26

### Changed

- **Zeroconf now a core dependency**: `zeroconf` moved from optional `[discovery]` extra to main dependencies
  - Install with just `pip install pyintellicenter` - no extras needed
  - Simplifies installation for Home Assistant integrations

## [0.0.3] - 2025-11-26

### Added

- **TCP Port Verification**: Discovery now verifies raw TCP port (6681) is accessible before reporting unit
- **Dual Port Support**: `ICUnit` now includes both `port` (TCP, typically 6681) and `ws_port` (WebSocket, typically 6680)
- **Live Discovery Test**: Added `scripts/test_discovery_live.py` for testing against real hardware

### Changed

- **Discovery Architecture**: Replaced deprecated event loop patterns with thread-safe asyncio.Queue
  - Sync zeroconf callbacks enqueue events
  - Async consumer processes queue and resolves services properly
  - No more "coroutine never awaited" warnings
- **Asyncio Best Practices**: Updated CLAUDE.md with guidance on proper async patterns

### Fixed

- Discovery now properly awaits async operations without storing event loop references
- TCP port calculation: mDNS advertises WebSocket port (6680), TCP port is ws_port + 1 (6681)

## [0.0.2] - 2025-11-26

### Added

- **HeaterType Enum**: New enumeration for all 14 heater modes (OFF, HEATER, SOLAR_PREF, SOLAR_ONLY, ULTRA_TEMP, ULTRA_TEMP_PREF, etc.)
- **mDNS Discovery Module** (`pyintellicenter.discovery`):
  - `ICUnit` dataclass for discovered units
  - `ICDiscoveryListener` for Zeroconf service browsing
  - `discover_intellicenter_units()` async function to find units on the network
  - `find_unit_by_name()` and `find_unit_by_host()` convenience functions
  - Optional dependency: install with `pip install pyintellicenter[discovery]`
- **Convenience Methods** on `ICModelController`:
  - `set_circuit_state(objnam, state)` - Turn circuits on/off
  - `set_heat_mode(body_objnam, mode)` - Set heater mode using HeaterType enum
  - `set_setpoint(body_objnam, temperature)` - Set temperature setpoint
  - `set_super_chlorinate(chem_objnam, enabled)` - Enable/disable super chlorination
  - `get_bodies()` - Get all pool/spa body objects
  - `get_circuits()` - Get all circuit objects
  - `get_heaters()` - Get all heater objects
  - `get_schedules()` - Get all schedule objects
  - `get_sensors()` - Get all sensor objects
- **Expanded Attribute Constants**: Added comprehensive attribute constants matching node-intellicenter:
  - Body attributes (HITMP, LOTMP, TEMP, MODE, HTSRC, HTMODE, etc.)
  - Circuit attributes (FEATR, USE, LIMIT, etc.)
  - Equipment attributes for pumps, heaters, chlorinators, chemistry
  - Schedule attributes (STIME, ETIME, TIMEBEG, TIMEEND, etc.)
  - System attributes (VER, PROPNAME, SNAME, MODE, etc.)
- **Integration Test Framework**:
  - `MockIntelliCenterServer` for testing without real hardware
  - Comprehensive integration tests for all controller classes
  - 177 total tests with 93% code coverage

### Changed

- Reorganized attributes into submodules (`attributes/body.py`, `attributes/circuit.py`, etc.)
- Improved type exports in `__init__.py`

### Fixed

- All integration tests now pass (previously 3 were skipped)

### Breaking Changes

- **BREAKING**: Minimum Python version bumped to 3.13+ (aligned with Home Assistant 2025.11)

## [0.0.1] - 2025-11-25

### Added

- Initial alpha release
- Core connection handling with `ICConnection` class
- Modern asyncio streams-based TCP communication
- Automatic keepalive with configurable interval
- `ICBaseController` for basic command handling
- `ICModelController` for maintaining equipment state model
- `ICConnectionHandler` for automatic reconnection with exponential backoff
- `PoolModel` and `PoolObject` classes for equipment state tracking
- Circuit breaker pattern for connection resilience
- Comprehensive exception hierarchy (`ICConnectionError`, `ICResponseError`, `ICCommandError`)
- Full type hints and py.typed marker
- GitHub Actions CI/CD workflows
- pytest test suite with asyncio support
- ruff linting and formatting
- mypy strict type checking

### Dependencies

- `orjson` for fast JSON serialization
- Python 3.11+ required

[Unreleased]: https://github.com/joyfulhouse/pyintellicenter/compare/v0.0.5a10...HEAD
[0.0.5a10]: https://github.com/joyfulhouse/pyintellicenter/compare/v0.0.5a9...v0.0.5a10
[0.0.5a9]: https://github.com/joyfulhouse/pyintellicenter/compare/v0.0.5a8...v0.0.5a9
[0.0.5a5]: https://github.com/joyfulhouse/pyintellicenter/compare/v0.0.5a4...v0.0.5a5
[0.0.5a4]: https://github.com/joyfulhouse/pyintellicenter/compare/v0.0.5a3...v0.0.5a4
[0.0.5a3]: https://github.com/joyfulhouse/pyintellicenter/compare/v0.0.5a2...v0.0.5a3
[0.0.5a2]: https://github.com/joyfulhouse/pyintellicenter/compare/v0.0.5a1...v0.0.5a2
[0.0.5a1]: https://github.com/joyfulhouse/pyintellicenter/compare/v0.0.4...v0.0.5a1
[0.0.4]: https://github.com/joyfulhouse/pyintellicenter/compare/v0.0.3...v0.0.4
[0.0.3]: https://github.com/joyfulhouse/pyintellicenter/compare/v0.0.2...v0.0.3
[0.0.2]: https://github.com/joyfulhouse/pyintellicenter/compare/v0.0.1...v0.0.2
[0.0.1]: https://github.com/joyfulhouse/pyintellicenter/releases/tag/v0.0.1
