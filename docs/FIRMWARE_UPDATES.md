# Firmware observations and installation gates

The library exposes a typed observation API on `ICBaseController` and
`ICModelController`. **No firmware installation is enabled for any hardware or
firmware version.** The reviewed device support registry is empty; there is no
public force/enable option. This is the supported implementation portion of
[pyintellicenter #106](https://github.com/joyfulhouse/pyintellicenter/issues/106).
The device research and installation-validation portions remain open.

## Read-only use

```python
from contextlib import aclosing

# Use ICModelController with the normal ICConnectionHandler lifecycle.
state = controller.firmware_update
print(state.available, state.installed_version, state.capability)

async with aclosing(controller.watch_firmware_update()) as observations:
    async for state in observations:
        print(state.phase, state.raw.get("PROGRESS"), state.reason)
```

The model controller's existing system subscriptions now include `IN`,
`PROGRESS`, and `AUTO`, alongside `VER`, `PROPNAME`, and `UPDATE`. The base
controller observes its normal startup version read and subsequent notifications;
it does not automatically subscribe to all system fields. Setup and reconnect
perform reads/subscriptions only. Existing availability attributes remain intact.

`FirmwareUpdateState` separates connection state, availability, raw observations,
request acknowledgement, and verified version. Each snapshot owns its raw data;
mutating a returned dictionary cannot change the monitor or another watcher.
`available` recognizes the existing integer/string `UPDATE` flags 0 and 1.
Other values, including app-style compound strings, remain unknown and are
preserved in `raw`. Missing keys, nulls, malformed values and unknown-key echoes
are not converted into fabricated progress or success. `raw` contains only the
six firmware keys above; `_FDR.EVENTSTATUS` and `EVENTID` are excluded.

Watchers receive an initial snapshot followed by the latest coalesced state.
Each listener has a bounded one-snapshot queue, so this is an observation stream,
not an event log. Closing/cancelling a watcher removes only its listener. It
sends no panel command and does not cancel an install. The monitor uses the
connection's additive enqueue-time observers independently of HA/model callbacks.
A replaced connection's notifications are ignored; a subscription response does
not overwrite keys notified since that subscription began. Raw observations
are cleared when a new connection is attached.

## Client lifecycle scaffolding

These phase names describe library observations, not panel protocol codes:

| Phase | Meaning |
| --- | --- |
| `unknown` | Insufficient data, uncertain outcome, deadline expiry, or unverified target |
| `available` | The existing `UPDATE=1` flag was observed; installation eligibility is separate |
| `requested` | One explicit request was admitted under a support contract |
| `acknowledged` | A correlated `200` response arrived; installation is unverified |
| `progress_observed` | A scalar PROGRESS value arrived after dispatch; units and meaning remain unknown |
| `reconnecting` | An active lifecycle lost its connection; reboot is not assumed |
| `verified` | A fresh explicit VER read equals the requested target and differs from the baseline |
| `failed` | The panel explicitly rejected the install request; this does not identify a panel installation failure code |

The gated API is `await controller.request_firmware_install(target_version,
verification_timeout=600.0)`. With the current empty registry it raises `ICError`
before any write. A future reviewed contract must match an exact source/target
version pair, evidence reference, and all required eligibility fields. Admission
and the actual transport write recheck eligibility; the request captures its
connection and shares the controller's mutation lock with existing writers.
The app-established install encoding is `_5451.IN="YES"`.

At most one install request is admitted per controller instance, including after
rejection, timeout, caller cancellation, stop/start and reconnect. There is no
automatic replay, retry, decline or reset action. This conservative guard is
in-memory, not a cross-process installation ledger. Recreating a controller is
not evidence that an uncertain panel operation stopped.

The verification deadline covers request queueing and acknowledgement, then
observation/reconnect time. Transport errors, malformed acknowledgement and
cancellation propagate; uncertain delivery remains `unknown`. An acknowledged
request that is not verified before its deadline becomes `unknown`, with
`reason="verification_timeout"`. Timers are cancelled on stop and resolution.
Neither raw progress nor version notifications verify the target. Consumers
explicitly call `await controller.verify_firmware_update()` after the request
settles; it performs a fresh read on the captured current connection. Missing,
malformed, unchanged or unexpected versions cannot produce `verified`. An
uncertain dispatched request can still be resolved by a later fresh read.
`verified_version` records the observed target, not proof of what caused it.

Decline (`IN="NO"`) is a separate app builder. Its effect during installation
is unproven. No decline/cancel method or corresponding capability is enabled.

## Evidence and remaining gates

Static evidence: Pentair Pool 4.2.21/build 21615, package
`com.pentair.pentairhome`, Hermes HBC v96, SHA-256
`ed262bd769b4ce8ba25e3faf5594f1a7d611b4db61d6b7cddd364e61be7f4526`.
Function 79341 (`0x0132ed4b`) builds the install/decline writes and the six-key
query/subscription. Supplemental functions 84346-84390 and 79467/79507 describe
client UI/controller state. UI flag resets are not device completion.
Functions 79485/79486 instead concern scheduled FDR/FDP events.
See the independently published evidence in
[PR #108](https://github.com/joyfulhouse/pyintellicenter/pull/108) and
[intellicenter PR #189](https://github.com/joyfulhouse/intellicenter/pull/189).
The implementation does not depend on merging those documentation PRs.

Before adding a real support contract, collect authorized, sanitized, correlated
device evidence for the exact hardware and source/target firmware combination:

1. Read-only baseline and install eligibility, including missing/unsupported keys,
   offer format, role/topology restrictions, and target version provenance.
2. One explicitly authorized install request and its correlated acceptance or
   rejection. An acknowledgement alone proves no completion.
3. Progress values, units/range, state transitions, terminal and failure values,
   with time ordering. Do not assume a 0..100 percentage scale.
4. Actual disconnect/reboot and reconnect timing, subscription restoration, stale
   notifications, and fresh target-version verification after reconnect.
5. Separate authorized evidence for decline and any cancel capability. Never use
   decline as an assumed cancellation operation.

### Evidence intake and support matrix (#106)

The 2026-10-25 review checked the owning issue and comments, merged lifecycle
PR #110, the linked static-analysis PRs #108 / intellicenter #189, repository
history and firmware fixtures. No correlated real-panel install capture was
found. The configured resource catalogs supplied no additional device evidence.
The support matrix therefore remains:

| Scope | Proven behavior | Missing before installation can be enabled |
| --- | --- | --- |
| Every real hardware/source/target combination | No validated install contract | All device gates below |
| Static app asset identified above | Install/decline request construction and queried keys | Eligibility, acceptance, progress semantics, terminal/failure states, reboot timing and version proof |
| Synthetic fixture | Client lifecycle and request/observation isolation | Hardware compatibility; this fixture cannot certify a real panel |
| Decline / cancellation | Distinct decline builder; no validated device effect | Independent acceptance and effect evidence for each operation |

Attach sanitized evidence to #106 with a stable capture identifier and an
ordered timeline. Retain field types and exact tokens; redact identifiers
consistently so command/response/notification correlation remains reviewable.
Record hardware model/revision, exact raw source and target version strings,
transport, app build, role, topology and target-offer provenance. Include
elapsed times, connection generations, request correlation, and whether each
observation is a snapshot, subscription response, notification or independent
panel observation. Do not publish credentials, addresses or private panel IDs.

| Case | Required evidence and expected client outcome |
| --- | --- |
| Eligibility | Complete fresh baseline for every proposed required parameter, including offer and target; missing/echoed keys, unsupported versions, roles or topology must fail closed |
| Acceptance / rejection | Exact request and correlated response; distinguish rejection from missing/malformed acknowledgement; `200` establishes acknowledgement only |
| Progress | Ordered exact values/types before dispatch, during the send/ack window and after acknowledgement; establish units, range, repeats, regressions and missing-progress behavior independently |
| Device failure | Independently confirmed panel failure and its correlated local state; a request rejection is not an installation failure code |
| Disconnect / reconnect | Actual interruption and independent reboot observation if available; elapsed reconnect bounds, connection replacement, restored subscriptions and stale-message handling; socket loss alone proves no reboot |
| Completion | Fresh explicit `VER` response on the current connection, equal to the independently established target and different from baseline; progress and cached/version notifications cannot substitute |
| Unresolved outcome | No progress, unchanged/unexpected/missing version, timeout or caller cancellation must remain unknown; demonstrate no install replay across reconnect or application restart |
| Decline / cancel | Separately authorized action, correlated response and independent observed effect in each claimed state; never infer cancellation from `IN=NO` or closing a watcher |

Collect read-only baselines first. A future install capture needs explicit
authorization for that device and target; repository implementation permission
does not authorize installation or panel mutation. Do not deliberately induce
destructive failures to fill this matrix. Use existing authorized captures or
naturally occurring failures where available; unsupported cases remain gated.

The default 600-second client observation deadline is a software bound, not a
measured firmware installation duration or reconnect SLA. Evidence must justify
any supported device-specific bounds. Later fresh reads may reconcile an
uncertain dispatched request, but must never automatically reinstall. Duplicate
protection currently ends with the controller instance: a future HA install
surface must also retain an unresolved-operation guard across reload/restart,
or establish an independently validated fresh reconciliation procedure before
allowing another request. Do not treat process recreation as retry permission.

`tests/fixtures/firmware/synthetic_contract.json` is deliberately synthetic. It
exercises the guarded lifecycle, not device compatibility; it must never enter
the production registry. Existing sanitized test/server fixtures validate the
library read/subscription mechanics. No live panel writes, installs, reboots or
LAN discovery were performed for this implementation.

Home Assistant's `FirmwareUpdateBinarySensor` and curated `firmware.py`
advisories are preserved. No HA update entity or install action is added. A
future entity can consume this typed API, but must advertise install capability
only after hardware support is validated. This change is additive and independent
of the concurrent schedule, alert, light and configuration work tracked by
[intellicenter #188](https://github.com/joyfulhouse/intellicenter/issues/188).
