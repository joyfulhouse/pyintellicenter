# pyintellicenter

Python library for communicating with Pentair IntelliCenter pool control systems over a local network.

[![PyPI Version][pypi-shield]][pypi]
[![Python Versions][pyversions-shield]][pypi]
[![License][license-shield]](LICENSE)
[![CI][ci-shield]][ci]
[![GitHub Sponsors][sponsors-shield]][sponsors]
[![Ko-fi][kofi-shield]][kofi]

## What It Does

`pyintellicenter` is an async Python library for communicating directly with Pentair
IntelliCenter pool control systems (i5P, i8P, i10P, and similar) over your local network.
It supports both TCP and WebSocket transports, provides real-time push-based equipment
state updates, and is the underlying library powering the
[Pentair IntelliCenter Home Assistant integration][intellicenter].

## Features

- **Dual Transport Support**: TCP (port 6681) and WebSocket (port 6680) connections
- **Local Communication**: Direct connection to IntelliCenter — no cloud required
- **Real-time Updates**: Push-based notifications via the NotifyList protocol
- **mDNS Discovery**: Automatically find IntelliCenter units on your network
- **Async/Await**: Built on Python asyncio for efficient I/O
- **Type Annotations**: Full type hints for IDE support and static analysis
- **Robust Connection Handling**: Automatic reconnection with exponential backoff
- **Circuit Breaker Pattern**: Prevents connection storms during outages
- **Home Assistant Ready**: Convenience helpers for integration development, including
  read-only accessors for temperature, chemistry, sensors, heaters, and schedules

## Installation

See **[INSTALL.md](INSTALL.md)** for the complete guide.

```bash
pip install pyintellicenter
# or
uv add pyintellicenter
```

Requires Python 3.13+.

## Quick Start

### Basic Connection (TCP)

```python
import asyncio
from pyintellicenter import ICModelController, PoolModel, ICConnectionHandler

async def main():
    model = PoolModel()
    controller = ICModelController("192.168.1.100", model)
    handler = ICConnectionHandler(controller)
    await handler.start()

    print(f"Connected to: {controller.system_info.prop_name}")
    print(f"Software version: {controller.system_info.sw_version}")

    for obj in model:
        print(f"{obj.sname} ({obj.objtype}): {obj.status}")

    await controller.set_circuit_state("POOL", True)
    await handler.stop()

asyncio.run(main())
```

### WebSocket Connection

```python
from pyintellicenter import ICConnection

async def main():
    async with ICConnection("192.168.1.100", transport="websocket") as conn:
        response = await conn.send_request(
            "GetParamList",
            condition="",
            objectList=[{"objnam": "INCR", "keys": ["VER", "SNAME"]}]
        )
        print(response)
```

### Auto-Discovery

```python
from pyintellicenter import discover_intellicenter_units

async def main():
    units = await discover_intellicenter_units(timeout=5.0)
    for unit in units:
        print(f"Found: {unit.name} at {unit.host}:{unit.port}")
        print(f"  Model: {unit.model}")
        print(f"  WebSocket port: {unit.ws_port}")
```

## Usage

See [docs/USAGE.md](docs/USAGE.md) for full usage patterns. The sections below cover
the main concepts.

### Connection Behavior

**Connection Flow:**

1. Connect — establishes TCP or WebSocket connection
2. Initialize — fetches system info and all equipment objects
3. Monitor — receives real-time NotifyList push updates
4. Keepalive — sends queries every 90 seconds (configurable)

**Reconnection Strategy:**

1. Debounce: 15-second grace period before marking disconnected
2. Exponential Backoff: starts at 30 s, doubles each attempt (max 5 min)
3. Circuit Breaker: after 5 consecutive failures, pauses for 5 minutes
4. Reset: successful connection resets failure counters

**Notification Processing:**

- Push notifications are queued (default: 100 items max)
- Queue prevents slow callbacks from blocking I/O
- When full, oldest notifications are dropped (prefers fresh state)
- Both sync and async callbacks are supported

### Error Handling

```python
from pyintellicenter import (
    ICError,            # Base exception
    ICConnectionError,  # Connection failures
    ICResponseError,    # Bad response from IntelliCenter
    ICCommandError,     # Command execution error
    ICTimeoutError,     # Request timeout
)

try:
    await controller.start()
except ICConnectionError as e:
    print(f"Connection failed: {e}")
except ICTimeoutError as e:
    print(f"Request timed out: {e}")
```

### Equipment Types

| Type | Constant | Description | Common Subtypes |
|------|----------|-------------|-----------------|
| Body | `BODY_TYPE` | Body of water | `POOL`, `SPA` |
| Pump | `PUMP_TYPE` | Variable speed pump | `SPEED`, `FLOW`, `VSF` |
| Circuit | `CIRCUIT_TYPE` | Circuit/Feature | `GENERIC`, `LIGHT`, `INTELLI`, `GLOW`, `DIMMER` |
| Circuit Group | `CIRCGRP_TYPE` | Group of circuits | — |
| Heater | `HEATER_TYPE` | Heater | `GENERIC`, `SOLAR`, `ULTRA`, `HYBRID` |
| Chem | `CHEM_TYPE` | Chemistry controller | `ICHLOR`, `ICHEM` |
| Sensor | `SENSE_TYPE` | Temperature sensor | `POOL`, `AIR`, `SOLAR` |
| Schedule | `SCHED_TYPE` | Schedule | — |
| Valve | `VALVE_TYPE` | Valve | `LEGACY` |

### Heater Modes

```python
from pyintellicenter import HeaterType

HeaterType.OFF              # Heater off
HeaterType.HEATER           # Gas/electric heater only
HeaterType.SOLAR_PREF       # Solar preferred, heater backup
HeaterType.SOLAR_ONLY       # Solar only
HeaterType.ULTRA_TEMP       # UltraTemp heat pump only
HeaterType.ULTRA_TEMP_PREF  # UltraTemp preferred
HeaterType.HYBRID           # Hybrid mode
# ... and more
```

### Light Effects

```python
from pyintellicenter import LIGHT_EFFECTS

# Available effects for IntelliBrite/MagicStream lights
# PARTY, ROMAN, CARIB, AMERCA, SSET, ROYAL, BLUER, GREENR, REDR, WHITER, MAGNTAR

await controller.set_light_effect("C0003", "PARTY")
```

## API Reference

Full API reference lives in [docs/](docs/). Key entry points:

| Class / Function | Purpose |
|---|---|
| `ICConnectionHandler` | Auto-reconnection wrapper with lifecycle callbacks |
| `ICModelController` | State management and all convenience helpers |
| `ICBaseController` | Basic command handling and metrics |
| `ICConnection` | Low-level transport (TCP or WebSocket) |
| `PoolModel` | Collection of all pool equipment objects |
| `PoolObject` | Individual equipment item |
| `discover_intellicenter_units()` | mDNS discovery of IntelliCenter units on LAN |

See [docs/API.md](docs/API.md) for the detailed per-class reference.

## Architecture

```
+----------------------------------------------------------+
|                    ICConnectionHandler                    |
|              (Auto-reconnection, callbacks)               |
+----------------------------------------------------------+
|                    ICModelController                      |
|           (State management, helper methods)              |
+----------------------------------------------------------+
|                     ICBaseController                      |
|              (Command handling, metrics)                  |
+----------------------------------------------------------+
|                      ICConnection                         |
|               (Transport selection, flow control)         |
+----------------------+-----------------------------------+
|      ICProtocol      |       ICWebSocketTransport        |
|    (TCP transport)   |      (WebSocket transport)        |
+----------------------+-----------------------------------+
```

| Layer | Class | Purpose |
|-------|-------|---------|
| Handler | `ICConnectionHandler` | Auto-reconnection, lifecycle callbacks |
| Controller | `ICModelController` | State management, convenience methods |
| Controller | `ICBaseController` | Basic command handling, metrics |
| Connection | `ICConnection` | Transport selection, request flow control |
| Transport | `ICProtocol` | TCP communication (port 6681) |
| Transport | `ICWebSocketTransport` | WebSocket communication (port 6680) |
| Model | `PoolModel` | Equipment collection |
| Model | `PoolObject` | Individual equipment item |

## Development

See [docs/DEVELOPMENT.md](docs/DEVELOPMENT.md). In short:

```bash
git clone https://github.com/joyfulhouse/pyintellicenter.git
cd pyintellicenter
uv sync --extra dev
uv run pytest
uv run ruff check
uv run mypy src/pyintellicenter
```

## Support

- **Issues:** <https://github.com/joyfulhouse/pyintellicenter/issues>
- **PyPI:** <https://pypi.org/project/pyintellicenter/>

## Support Development

This library powers the [Pentair IntelliCenter Home Assistant integration][intellicenter]
and is maintained in spare time with real hardware and tooling costs behind every release.
If it is useful to you, please consider supporting its development:

- [GitHub Sponsors][sponsors]
- [Ko-fi][kofi]

## License

This project is licensed under the **MIT** License — see
[LICENSE](LICENSE) for details.

## Related Projects

- [Pentair IntelliCenter][intellicenter] — the Home Assistant integration built on this
  library.
- [node-intellicenter](https://github.com/pent-house/node-intellicenter) — Node.js library
  (protocol reference).

<!-- Badge links -->
[pypi-shield]: https://img.shields.io/pypi/v/pyintellicenter.svg?style=for-the-badge
[pypi]: https://pypi.org/project/pyintellicenter/
[pyversions-shield]: https://img.shields.io/pypi/pyversions/pyintellicenter.svg?style=for-the-badge
[license-shield]: https://img.shields.io/github/license/joyfulhouse/pyintellicenter.svg?style=for-the-badge
[ci-shield]: https://img.shields.io/github/actions/workflow/status/joyfulhouse/pyintellicenter/test.yml?style=for-the-badge&label=CI
[ci]: https://github.com/joyfulhouse/pyintellicenter/actions
[sponsors-shield]: https://img.shields.io/badge/sponsor-GitHub-EA4AAA.svg?style=for-the-badge&logo=githubsponsors&logoColor=white
[sponsors]: https://github.com/sponsors/btli
[kofi-shield]: https://img.shields.io/badge/Ko--fi-donate-FF5E5B.svg?style=for-the-badge&logo=ko-fi&logoColor=white
[kofi]: https://ko-fi.com/bryanli
[intellicenter]: https://github.com/joyfulhouse/intellicenter
