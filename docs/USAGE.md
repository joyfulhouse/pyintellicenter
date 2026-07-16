# Usage Guide

Detailed usage for pyintellicenter. See the [README](../README.md) for a quick
start.

## Authentication

IntelliCenter uses no authentication — the library connects directly over TCP or
WebSocket to the controller on your LAN. Ensure your host machine can reach the
controller's IP address and that ports 6681 (TCP) and 6680 (WebSocket) are not
blocked by a firewall.

## Core Workflows

### Connecting and reading state

```python
import asyncio
from pyintellicenter import ICModelController, PoolModel, ICConnectionHandler

async def main():
    model = PoolModel()
    controller = ICModelController("192.168.1.100", model)
    handler = ICConnectionHandler(controller)
    await handler.start()

    # System info
    print(controller.system_info.prop_name)
    print(controller.system_info.sw_version)

    # Equipment lists
    bodies   = controller.get_bodies()
    circuits = controller.get_circuits()
    pumps    = controller.get_pumps()
    heaters  = controller.get_heaters()
    sensors  = controller.get_sensors()

    await handler.stop()

asyncio.run(main())
```

### Controlling equipment

```python
# Circuits
await controller.set_circuit_state("POOL", True)
await controller.set_circuit_state("SPA", False)
await controller.set_multiple_circuit_states(["AUX1", "AUX2"], True)

# Heating
from pyintellicenter import HeaterType
await controller.set_heat_mode("B1101", HeaterType.HEATER)
await controller.set_heating_setpoint("B1101", 84)
await controller.set_cooling_setpoint("B1101", 88)  # UltraTemp heat pumps

# Lights
await controller.set_light_effect("C0003", "PARTY")

# Chemistry (IntelliChem)
await controller.set_ph_setpoint("CHEM1", 7.4)
await controller.set_orp_setpoint("CHEM1", 700)
await controller.set_chlorinator_output("CHEM1", 50)

# Vacation mode
await controller.set_vacation_mode(True)
```

### Verified light-group Color Sync

The dedicated Color Sync action is evidence-scoped rather than a generic light
group command. The controller must report the exact raw firmware token `1.064`,
the addressed object must be a real `CIRCUIT/LITSHO` parent with exactly two
distinct resolved `CIRCUIT/GLOW` children, and the parent plus children must be
uniformly all off or all on. Color Set, Color Swim, and member-position writes
are not implemented.

```python
from pyintellicenter import ICError, ICLightGroupError

groups = controller.get_circuit_groups()
rows = controller.get_circuit_group_members(groups[0].objnam)
children = controller.get_circuits_in_group(groups[0].objnam)

try:
    acknowledgement = await controller.run_light_group_sync(groups[0].objnam)
except ValueError:
    # Cached firmware or topology is outside the supported action envelope.
    raise
except ICLightGroupError as err:
    if err.acknowledged or err.onset_seen:
        # The action was acknowledged or visibly started but did not prove
        # completion. Inspect the physical lights before any retry.
        raise
    if err.dispatch_started and not err.response_received:
        # Delivery is uncertain; inspect the physical lights before any retry.
        raise
    # An explicit rejection or malformed response was received after dispatch.
    raise
except ICError:
    # A subscription, connection, or fresh state/preflight gate failed before dispatch.
    raise
```

The successful return value is the complete correlated transport
acknowledgement. The call commonly occupies roughly 96–97 seconds plus request
latency on the observed firmware: one second for subscription settling, roughly
35–36 seconds for the physical Sync lifecycle, a mandatory 60-second
post-terminal observation, and a final read on the same connection. There is no
automatic retry or recovery write.

While the call owns the controller mutation lifecycle, later object-changing
calls through that controller fail immediately with `ICError`; read-only commands
and model updates continue. A physical-panel change or write through a separate
raw `ICConnection` is outside this boundary and causes failure if it changes the
monitored projection. `ICLightGroupError` exposes `phase`, `dispatch_started`,
`response_received`, `acknowledged`, and `onset_seen`. Any failure with
`dispatch_started=True` requires physical inspection before a deliberate retry.

### Subscribing to state changes

```python
def on_update(controller, changes):
    for objnam, attrs in changes.items():
        print(f"{objnam} changed: {attrs}")

controller.set_updated_callback(on_update)
```

### Discovery

```python
from pyintellicenter import discover_intellicenter_units

units = await discover_intellicenter_units(timeout=5.0)
for unit in units:
    print(f"{unit.name} at {unit.host}:{unit.port}")
```

## Error Handling

```python
from pyintellicenter import (
    ICError,            # Base exception
    ICConnectionError,  # Connection failures
    ICResponseError,    # Bad response from IntelliCenter
    ICCommandError,     # Command execution error
    ICTimeoutError,     # Request timeout
    ICLightGroupError,  # Color Sync failed after dispatch began
)

try:
    await controller.start()
except ICConnectionError as e:
    print(f"Connection failed: {e}")
except ICTimeoutError as e:
    print(f"Request timed out: {e}")
```

## Advanced

### Custom reconnection parameters

```python
from pyintellicenter import ICConnectionHandler, ICConnectionHandlerCallbacks

callbacks = ICConnectionHandlerCallbacks(
    on_started=lambda: print("Connected!"),
    on_stopped=lambda: print("Stopped"),
    on_disconnected=lambda: print("Disconnected"),
    on_reconnected=lambda: print("Reconnected!"),
    on_retrying=lambda attempt, delay: print(f"Retry {attempt} in {delay}s"),
)

handler = ICConnectionHandler(
    controller,
    callbacks=callbacks,
    time_between_reconnects=30.0,   # Initial reconnect delay
    disconnect_debounce_time=15.0,  # Grace period before disconnect callback
)
```

### Using a shared Zeroconf instance (Home Assistant)

```python
from zeroconf import Zeroconf
from pyintellicenter import discover_intellicenter_units

zc = Zeroconf()
units = await discover_intellicenter_units(timeout=5.0, zeroconf=zc)
```

### Low-level raw request

```python
async with ICConnection("192.168.1.100") as conn:
    response = await conn.send_request(
        "GetParamList",
        condition="",
        objectList=[{"objnam": "INCR", "keys": ["VER", "SNAME"]}]
    )
```
