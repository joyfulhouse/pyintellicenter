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
    bodies = controller.get_bodies()
    circuits = controller.get_circuits()
    pumps = controller.get_pumps()
    heaters = controller.get_heaters()
    sensors = controller.get_sensors()

    await handler.astop()


asyncio.run(main())
```

`await handler.astop()` stops the handler and waits for the connection teardown
to complete. Use the synchronous `handler.stop()` where you cannot await (for
example inside a callback); it schedules the teardown in the background. See
[Shutdown](#shutdown) below.

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
        if attrs is None:
            print(f"{objnam} was removed")  # equipment deleted at the panel
        else:
            print(f"{objnam} changed: {attrs}")


controller.set_updated_callback(on_update)
```

The `changes` payload maps each objnam to a dict of its changed attributes.
A value of `None` marks a removal: on every (re)connect the controller
reconciles the model against the authoritative object snapshot, prunes
equipment that was deleted at the panel (it is also dropped from the
attribute re-subscription queries), and reports each pruned objnam through
this callback with value `None`. Consumers should tear down anything they
created for a removed objnam (e.g. Home Assistant entities).

`set_updated_callback` is a single slot — and `ICConnectionHandler` claims it
for its `on_updated` hook — so consumers needing multiple listeners (e.g. one
per Home Assistant entity) should use per-object subscriptions instead:

```python
# On the controller, or via the handler (handler.subscribe forwards):
unsubscribe = handler.subscribe("B1101", on_update)  # one object
unsub_all = handler.subscribe(None, on_update)  # all objects

unsubscribe()  # stop listening (idempotent; safe even during dispatch)
```

The callback signature is identical to `set_updated_callback`, including the
`None`-for-removal contract; a per-objnam subscriber receives only its
object's entry, still as a mapping (`{objnam: attrs}`). Any number of
subscriptions can coexist with the legacy callback, and a subscriber raising
is logged without affecting other subscribers or update processing. Treat the
`changes` payload as read-only — it is shared between the legacy callback and
all subscribers, so never mutate it (copy first if needed). See
[API.md](API.md#per-object-subscriptions) for full semantics.

### Discovery

```python
from pyintellicenter import discover_intellicenter_units

units = await discover_intellicenter_units(discovery_timeout=5.0)
for unit in units:
    print(f"{unit.name} at {unit.host}:{unit.port}")
```

## Error Handling

```python
from pyintellicenter import (
    ICError,  # Base exception
    ICConnectionError,  # Connection failures
    ICResponseError,  # Bad response from IntelliCenter
    ICCommandError,  # Command execution error
    ICTimeoutError,  # Request timeout
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

### Custom reconnection parameters and lifecycle callbacks

Lifecycle events are handled by assigning to (or overriding) the handler's
callback methods. `ICConnectionHandlerCallbacks` is a `typing.Protocol` used
for static typing only — it is not instantiated or passed to the handler.

```python
from pyintellicenter import ICConnectionHandler

handler = ICConnectionHandler(
    controller,
    time_between_reconnects=30,  # Initial reconnect delay (seconds)
    disconnect_debounce_time=15,  # Grace period before disconnect callback (seconds)
)

handler.on_started = lambda ctrl: print("Connected!")
handler.on_reconnected = lambda ctrl: print("Reconnected!")
handler.on_disconnected = lambda ctrl, exc: print(f"Disconnected: {exc}")
handler.on_retrying = lambda delay: print(f"Retrying in {delay}s")
```

See [API.md](API.md#icconnectionhandler) for the full callback signatures.

### Shutdown

```python
# Async code that must not proceed until the connection is fully closed
# (e.g. Home Assistant's async_unload_entry): stop and await the teardown.
await handler.astop()

# Sync best-effort form (e.g. from inside a callback): cancels reconnection
# and schedules the controller teardown in a tracked background task.
handler.stop()

# Handler-level (debounced) availability
if handler.connected:
    ...
```

`handler.stop()` is synchronous and returns `None` — it is not awaitable.
After `stop()`/`astop()` the handler can be started again with
`await handler.start()`.

### Using a shared Zeroconf instance (Home Assistant)

```python
from zeroconf import Zeroconf
from pyintellicenter import discover_intellicenter_units

zc = Zeroconf()
units = await discover_intellicenter_units(discovery_timeout=5.0, zeroconf=zc)
```

### Low-level raw request

```python
async with ICConnection("192.168.1.100") as conn:
    response = await conn.send_request(
        "GetParamList", condition="", objectList=[{"objnam": "INCR", "keys": ["VER", "SNAME"]}]
    )
```
