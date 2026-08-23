# API Reference

Detailed reference for all public classes and functions in pyintellicenter.

## ICConnection

Low-level connection wrapper supporting both TCP and WebSocket transports.

```python
from pyintellicenter import ICConnection

# TCP connection (default)
conn = ICConnection("192.168.1.100")
conn = ICConnection("192.168.1.100", transport="tcp")
conn = ICConnection("192.168.1.100", port=6681)

# WebSocket connection
conn = ICConnection("192.168.1.100", transport="websocket")
conn = ICConnection("192.168.1.100", port=6680, transport="websocket")

# Full configuration
conn = ICConnection(
    host="192.168.1.100",
    port=6681,  # Default: 6681 (TCP), 6680 (WebSocket)
    transport="tcp",  # "tcp" or "websocket"
    response_timeout=30.0,  # Request timeout in seconds
    keepalive_interval=90.0,  # Keepalive interval in seconds
    notification_queue_size=100,  # Max queued notifications
    notification_batching=True,  # Merge queued notification bursts (see below)
)

# Usage as context manager
async with ICConnection("192.168.1.100") as conn:
    response = await conn.send_request("GetParamList", ...)

# Manual connection management
await conn.connect()
response = await conn.send_request("GetParamList", ...)
await conn.disconnect()

# Callbacks
conn.set_notification_callback(lambda msg: print(msg))
conn.set_disconnect_callback(lambda exc: print(f"Disconnected: {exc}"))
```

### Notification batching

The panel emits NotifyList bursts (e.g. a scene change produces several
back-to-back frames). With `notification_batching=True` (the default), any
messages already queued behind the one just received are drained — at most
25 per callback invocation, so a lone message is still delivered immediately —
and merged into a single synthetic NotifyList. Its `objectList` is coalesced
per `objnam`: an object updated by several frames of the burst contributes one
entry whose params are folded in arrival order (newest value wins per
attribute), so the merged frame yields exactly the same final model state as
per-message delivery — and the changed-attributes callback payload carries
every attribute the burst touched — with one callback invocation per burst
instead of one per message. Set `notification_batching=False` to restore
strict per-message delivery.

On notification-queue overflow, the oldest queued frame is no longer dropped
wholesale: its `objectList` entries are coalesced by `objnam` into the
incoming frame (newest attribute values win), so attribute deltas from
overflowed partial frames are not silently lost.

## ICModelController

Controller that maintains equipment state in a PoolModel.

```python
from pyintellicenter import (
    HeaterType,
    ICError,
    ICLightGroupError,
    ICModelController,
    PoolModel,
)

model = PoolModel()
controller = ICModelController(
    host="192.168.1.100",
    model=model,
    port=6681,
    keepalive_interval=90.0,
)

await controller.start()

# System information
info = controller.system_info
print(f"Name: {info.prop_name}")
print(f"Version: {info.sw_version}")
print(f"Unique ID: {info.unique_id}")
print(f"Uses Metric: {info.uses_metric}")

# Equipment control
await controller.set_circuit_state("POOL", True)
await controller.set_circuit_state("SPA", False)
await controller.set_heat_mode("B1101", HeaterType.HEATER)
await controller.set_heating_setpoint("B1101", 84)
await controller.set_cooling_setpoint("B1101", 88)
await controller.set_super_chlorinate("C0001", True)
await controller.set_light_effect("C0003", "PARTY")

# Batch operations
await controller.set_multiple_circuit_states(["AUX1", "AUX2"], True)

# Entity getters
bodies = controller.get_bodies()
circuits = controller.get_circuits()
pumps = controller.get_pumps()
heaters = controller.get_heaters()
sensors = controller.get_sensors()
schedules = controller.get_schedules()
lights = controller.get_lights()
color_lights = controller.get_color_lights()
chem_controllers = controller.get_chem_controllers()
valves = controller.get_valves()

# All entities grouped by type (for Home Assistant discovery)
entities = controller.get_all_entities()
# Returns: {"bodies": [...], "circuits": [...], "lights": [...],
#           "circuit_groups": [...], "color_light_groups": [...], ...}

# Circuit group helpers
# Parent CIRCUIT objects are groups; CIRCGRP objects are membership rows.
groups = controller.get_circuit_groups()
rows = controller.get_circuit_group_members(groups[0].objnam)
children = controller.get_circuits_in_group(groups[0].objnam)
color_groups = controller.get_color_light_groups()

# Verified Color Sync for an evidence-supported light-group parent.
try:
    await controller.run_light_group_sync(groups[0].objnam)
except ValueError:
    # Cached firmware or topology is outside the supported action envelope.
    raise
except ICLightGroupError as err:
    if err.acknowledged or err.onset_seen:
        # The action was acknowledged or visibly started, but completion was
        # not proven. Inspect the physical lights before any deliberate retry.
        raise
    if err.dispatch_started and not err.response_received:
        # Dispatch began, but whether the controller received it is unknown.
        raise
    # The controller returned an explicit rejection or malformed response.
    raise
except ICError:
    # Subscription or fresh state/preflight failed before dispatch began.
    raise

# Hardware discovery queries
config = await controller.get_configuration()  # Bodies and circuits
hardware = await controller.get_hardware_definition()  # Full equipment hierarchy

# Temperature helpers
unit = controller.get_temperature_unit()  # "F" or "C"
temp = controller.get_body_temperature("B1101")
last_temp = controller.get_body_last_temperature("B1101")
heat_setpt = controller.get_body_heating_setpoint("B1101")
cool_setpt = controller.get_body_cooling_setpoint("B1101")
heat_mode = controller.get_body_heat_mode("B1101")
is_heating = controller.is_body_heating("B1101")

# Heater helpers
heater = controller.get_heater_for_body("B1101")
heater_ready = controller.is_heater_ready("H0001")

# Chemistry helpers
ph = controller.get_chem_reading("C0001", "PH")
orp = controller.get_chem_reading("C0001", "ORP")
salt = controller.get_chem_reading("C0001", "SALT")
alerts = controller.get_chem_alerts("C0001")
sindex = controller.get_saturation_index("C0001")  # Langelier Saturation Index (IntelliChem)

# Chemistry setpoint control (IntelliChem)
await controller.set_ph_setpoint("CHEM1", 7.4)
await controller.set_orp_setpoint("CHEM1", 700)
ph_target = controller.get_ph_setpoint("CHEM1")
orp_target = controller.get_orp_setpoint("CHEM1")

# Chlorinator output control (IntelliChlor)
await controller.set_chlorinator_output("CHEM1", 50)  # 50% primary
await controller.set_chlorinator_output("CHEM1", 50, 100)  # 50% pool, 100% spa
output = controller.get_chlorinator_output("CHEM1")  # {"primary": 50, "secondary": 100}

# Vacation mode
await controller.set_vacation_mode(True)
is_vacation = controller.is_vacation_mode()

# Pump helpers
is_running = controller.is_pump_running("P0001")
rpm = controller.get_pump_rpm("P0001")
gpm = controller.get_pump_gpm("P0001")
watts = controller.get_pump_watts("P0001")
metrics = controller.get_pump_metrics("P0001")  # {"rpm": ..., "gpm": ..., "watts": ...}

# Sensor helpers
air_sensors = controller.get_air_sensors()
solar_sensors = controller.get_solar_sensors()
reading = controller.get_sensor_reading("S0001")  # Calibrated reading (SOURCE)
probe = controller.get_sensor_probe_reading("S0001")  # Raw probe reading (PROBE)
calibration = controller.get_sensor_calibration("S0001")  # Calibration offset (CALIB)

# Light helpers
effect = controller.get_light_effect("C0003")
effect_name = controller.get_light_effect_name("C0003")
available = controller.get_available_light_effects("C0003")

# Schedule helpers
enabled = controller.is_schedule_enabled("SCH01")  # STATUS=ON
circuit = controller.get_schedule_circuit("SCH01")  # objnam of controlled circuit
start = controller.get_schedule_start_time("SCH01")  # "HH,MM,SS" 24-hour
stop = controller.get_schedule_stop_time("SCH01")  # "HH,MM,SS" 24-hour
days = controller.get_schedule_days("SCH01")  # e.g. "MTWRFAU"


# Update callback
def on_update(controller, changes):
    for objnam, attrs in changes.items():
        if attrs is None:
            # Removal: the object disappeared from the panel and was pruned
            # from the model during (re)connect reconciliation.
            print(f"{objnam} was removed")
        else:
            print(f"{objnam} changed: {attrs}")


controller.set_updated_callback(on_update)
await controller.stop()
```

### Per-object subscriptions

`set_updated_callback` is a single overwrite-slot (and `ICConnectionHandler`
claims it), so consumers that need many listeners — e.g. one per Home
Assistant entity — should use `subscribe()` instead. Any number of
subscriptions can coexist with the legacy callback, whose behavior is
unchanged.

```python
# Listen for one object. The callback signature matches the updated
# callback; a per-objnam subscriber receives only its object's entry,
# still as a mapping ({objnam: attrs}).
unsubscribe = controller.subscribe("B1101", lambda ctrl, changes: print(changes))

# objnam=None receives updates for all objects (the full mapping).
unsub_all = controller.subscribe(None, lambda ctrl, changes: print(changes))

unsubscribe()  # remove the subscription (idempotent, safe during dispatch)
```

Semantics:

- Subscribers are dispatched from the same place as the legacy updated
  callback (after it), so ordering and the removal contract are identical:
  an entry value of `None` marks the object's removal from the model.
- Each subscriber invocation is exception-guarded — one subscriber raising
  is logged and never affects other subscribers, the legacy callback, or
  update processing.
- All applicable listener lists are snapshotted before any callback runs, so
  subscribing or unsubscribing from within a callback only affects future
  dispatches, never the one in flight.
- Callback payloads (including the attribute dicts) are **read-only**: they
  are shared between the legacy updated callback and all subscribers, so
  mutating them would be visible to every other listener. Copy first if you
  need to modify.
- `ICConnectionHandler.subscribe(objnam, callback)` forwards to the managed
  `ICModelController`, so consumers holding only the handler can subscribe
  directly (raises `TypeError` if the handler manages a non-model controller).

### Snapshot reconciliation and removals

On every `start()` — the initial connect and each automatic reconnect — the
controller fetches an authoritative snapshot of all objects and reconciles the
model against it (`PoolModel.reconcile()`). Any object in the model that is
absent from the snapshot (equipment deleted at the panel) is:

- removed from the model (and from the attribute-subscription queries built
  during startup, so it is never re-subscribed),
- logged at INFO, and
- reported to the updated callback as an entry with value `None`
  (`{objnam: None}`), so consumers such as Home Assistant can remove the
  corresponding entities.

Attribute-change entries passed to the callback are always non-`None` dicts;
`None` is reserved for removals. The callback payload is typed
`Mapping[str, dict[str, Any] | None]`.

Partial snapshots are surfaced by the model layer: `PoolModel.add_objects()`
returns the ingested objnams and logs one WARNING when a snapshot contains
malformed entries, while expected skips (a missing or untracked `OBJTYP`,
such as the firmware 3.008+ `_FDR` artifacts) are logged at DEBUG only. The
controller reports the ingested/snapshot counts in its INFO startup line
(`Model contains N objects (I of S snapshot entries ingested)`) instead of
emitting a separate warning.

For compatibility, a legacy standalone `CIRCGRP` object with a direct
space-separated `CIRCUIT` list can still be passed to
`get_circuits_in_group()`. It is not returned by `get_circuit_groups()` or
`get_color_light_groups()`; only parent `CIRCUIT` objects are enumerated as
groups.

`run_light_group_sync()` is deliberately narrower than the read helpers. It is
available only when fresh and cached state both report the exact raw firmware
token `1.064`, the parent is `CIRCUIT/LITSHO`, membership resolves to exactly two
distinct `CIRCUIT/GLOW` children, and the parent plus both children are uniformly
all off or all on. Color Set, Color Swim, and member-position writes are not
implemented.

The call is blocking and commonly occupies roughly 96–97 seconds plus request
latency on the observed firmware: a one-second subscription settle, roughly
35–36 seconds to the physical terminal edge, a full 60-second post-terminal
observation, and a final same-connection read. It never retries or sends an
automatic recovery command. During that complete interval, later object-changing
calls through the same controller fail immediately with `ICError`; read-only
commands and model notifications continue. Physical-panel writes and writes made
through a separate raw `ICConnection` are outside that isolation boundary and
make Sync incomplete if they alter the monitored safety projection.

`ICLightGroupError` is used only after transport dispatch begins and exposes five
read-only certainty attributes: `phase`, `dispatch_started`, `response_received`,
`acknowledged`, and `onset_seen`. Its phase is one of `acknowledgement`, `onset`,
`terminal`, `observation`, or `final_projection`. Any error with
`dispatch_started=True` requires physical inspection before a deliberate retry,
even when the controller never returned an acknowledgement.

## ICConnectionHandler

Wraps a controller with automatic reconnection and lifecycle callbacks.

Lifecycle events are handled by overriding (or assigning to) the handler's
callback methods. `ICConnectionHandlerCallbacks` is a `typing.Protocol` that
describes these callbacks for static type checking — it is not instantiated
or passed to the handler.

```python
from pyintellicenter import ICConnectionHandler

handler = ICConnectionHandler(
    controller,
    time_between_reconnects=30,  # Initial reconnect delay (seconds)
    disconnect_debounce_time=15,  # Grace period before disconnect callback (seconds)
)

# Assign (or override in a subclass) the lifecycle callbacks
handler.on_started = lambda ctrl: print("Connected!")
handler.on_reconnected = lambda ctrl: print("Reconnected!")
handler.on_disconnected = lambda ctrl, exc: print(f"Disconnected: {exc}")
handler.on_retrying = lambda delay: print(f"Retrying in {delay}s")
handler.on_updated = lambda ctrl, updates: print(f"Updated: {updates}")

await handler.start()
print(handler.controller.system_info.prop_name)
print(f"Connected: {handler.connected}")
await handler.astop()
```

Methods and properties:

- `await handler.start()` — connects and waits for the first successful
  attempt (raising if it fails); reconnection then continues automatically in
  the background. The handler can be started again after `stop()`/`astop()`.
- `handler.stop()` — synchronous best-effort stop: cancels reconnection and
  schedules the controller teardown in a tracked background task. Returns
  `None` (it is not awaitable) and is safe to call from callbacks.
- `await handler.astop()` — stops the handler and waits for the full
  controller teardown to complete. Use this where shutdown must be finished
  before proceeding (e.g. Home Assistant's `async_unload_entry`). The
  teardown is shielded from caller cancellation: cancelling an `astop()`
  caller raises `CancelledError` to that caller while the teardown keeps
  running in the background, and a later `start()`/`astop()` waits for its
  actual completion.
- `handler.connected` — `True` while the handler considers the connection
  established (the debounced handler-level view): it turns `True` after a
  successful connect or reconnect and `False` on disconnect or
  `stop()`/`astop()`.
- `handler.subscribe(objnam, callback)` — forwards to
  `ICModelController.subscribe()` on the managed controller and returns the
  unsubscribe callable (see "Per-object subscriptions" above). Raises
  `TypeError` if the managed controller is not an `ICModelController`.

Callback signatures:

- `on_started(controller)` — called on the initial successful connection
- `on_reconnected(controller)` — called when reconnected after a disconnect
- `on_disconnected(controller, exc)` — called when disconnected (after the
  debounce period); `exc` is the causing exception or `None`
- `on_retrying(delay)` — called before each retry attempt with the delay in
  seconds
- `on_updated(controller, updates)` — called when the model is updated (only
  when wrapping an `ICModelController`); an entry with value `None` marks an
  object removed from the model during reconnect reconciliation (see the
  `ICModelController` section above)

`handler.controller.connected` reports whether the underlying controller
currently has a live connection (the transport-level view, without the
handler's debounce).

## PoolModel

Collection of pool equipment objects.

```python
from pyintellicenter import PoolModel

model = PoolModel()

for obj in model:
    print(f"{obj.objnam}: {obj.sname}")

pump = model["PUMP1"]
bodies = model.get_by_type("BODY")
pools = model.get_by_type("BODY", "POOL")
pumps = model.get_by_type("PUMP")

children = model.get_children(panel)
print(f"Total objects: {model.num_objects}")

# Removal APIs (ICModelController.start() wires reconcile() automatically)
removed_obj = model.remove_object("PUMP1")  # The removed PoolObject, or None
removed_objnams = model.reconcile(snapshot)  # Prune objects absent from an
#                                              authoritative object-list snapshot;
#                                              returns the removed objnams
```

## PoolObject

Individual equipment item.

```python
obj = model["PUMP1"]

obj.objnam  # Object name: "PUMP1"
obj.sname  # Friendly name: "Pool Pump"
obj.objtype  # Type: "PUMP"
obj.subtype  # Subtype: "VSF"
obj.status  # Status: "ON" or "OFF" ("10"/"4" for pumps)

obj.is_a_light  # Is this a light?
obj.is_a_light_show  # Is this a light show circuit?
obj.is_featured  # Is this marked as featured?
obj.supports_color_effects  # Supports IntelliBrite effects?

obj.on_status  # The "on" status value for this type ("ON", or "10" for pumps)
obj.off_status  # The "off" status value for this type ("OFF", or "4" for pumps)
is_on = obj.status == obj.on_status  # Check whether the object is on

rpm = obj["RPM"]
power = obj["PWR"]
temp = obj["TEMP"]
parent = obj["PARENT"]  # Parent object name (objnam), if any

for key in obj.attribute_keys:
    print(f"{key}: {obj[key]}")
```

## Discovery

Find IntelliCenter units on your local network using mDNS/Zeroconf.

```python
from pyintellicenter import (
    discover_intellicenter_units,
    find_unit_by_name,
    find_unit_by_host,
    ICUnit,
)

units = await discover_intellicenter_units(discovery_timeout=5.0)

# With existing Zeroconf instance (for Home Assistant)
from zeroconf import Zeroconf

zc = Zeroconf()
units = await discover_intellicenter_units(discovery_timeout=5.0, zeroconf=zc)

unit = await find_unit_by_name("My Pool", discovery_timeout=5.0)
unit = await find_unit_by_host("192.168.1.100", discovery_timeout=5.0)

unit.name  # Friendly name
unit.host  # IP address
unit.port  # TCP port (6681)
unit.ws_port  # WebSocket port (6680)
unit.model  # Model info (if available)
```
