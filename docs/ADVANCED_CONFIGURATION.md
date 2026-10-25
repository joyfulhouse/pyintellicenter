# Advanced panel configuration evidence contract

Owning request: [HA #186](https://github.com/joyfulhouse/intellicenter/issues/186).
Delivery tracker: [HA #188](https://github.com/joyfulhouse/intellicenter/issues/188).
The [HA settings matrix](https://github.com/joyfulhouse/intellicenter/blob/main/docs/advanced-system-settings.md)
describes the existing guarded MANOVR switch and read-only diagnostics.
Clock, persistent-delay and solar-relay editing remain unsupported; generic
`request_changes()` is transport capability, not a validated commissioning API.

## Evidence and schema limits

Pentair Pool 4.2.21 / build 21615 function 83088 (`0x013d5f00`) constructs
MANOVR, clock, VALVE/HEATING and SASHP/SASHP2 saves. Functions 83020/83136
gate solar-relay UI using topology and a comparison involving OCP_VERSION_2029.
Hermes asset SHA-256:
`ed262bd769b4ce8ba25e3faf5594f1a7d611b4db61d6b7cddd364e61be7f4526`.
These are static client observations, not captured successful panel commands.
The 2026-10-25 review of available repository/history/PR evidence found no
correlated advanced-setting device captures establishing the remaining contracts.

| Field | Existing evidence | Unresolved contract before editing |
| --- | --- | --- |
| MANOVR | App writes ON/OFF through manualHeatObjectName; HA discovers canonical readback | Actual owner/type by firmware, independent write/readback and reconnect behavior; MANHT is separate |
| SOURCE | Library documents a separate SYSTIM source object and URL observation; app uses clockSourceObjectName | Actual owner, allowed values, manual/network interlocks and ownership transitions |
| DAY, TIME, MIN | Library comments record DAY as MM,DD,YY and MIN as HH,MM,SS; app save uses a DAY helper and TIME formatted HH,mm,00 | Captured read/write schemas, date/year convention, seconds and midnight rollover; TIME and MIN are not proven interchangeable |
| TIMZON | Attribute listed on SYSTEM and SYSTIM; historical example -8 | Authoritative target, units, sign, supported fractional offsets and relation to DST; no IANA conversion or integer restriction is established |
| CLK24A, DLSTIM | AMPM/HR24 and ON/OFF observations | Write/readback, spring/fall behavior, repeated/skipped local times and source interactions |
| VALVE, HEATING | App saves persistent SYSTEM flags | Firmware/topology applicability, independent readback and associated pump behavior; not transient delay state or cancellation |
| SASHP, SASHP2 | App saves SYSTEM flags with conditional UI | Exact version predicate, single/shared/dual-body eligibility, heater/body association changes and configuration reconciliation |

Attribute sets describe discovery candidates and historical observations. They
are neither firmware profiles nor permission to edit a field. Do not add TIME,
solar-relay attributes, version gates or guessed owner constants merely to make
a synthetic fixture writable. Preserve unknown and unsupported state.

## Capture and failure requirements

For each supported firmware/topology profile, obtain sanitized timestamped
initial inventory/readback, explicitly authorized single-setting edits, complete
request/response/notification correlation, and independent subsequent reads.
Preserve stable aliases, types, values, ordering and failures while stripping
credentials and personal/device identifiers. Include independent panel/app
observations; an ACK does not prove a changed setting or successful physical
action. No live mutation or disruptive experiment is authorized by this document.

Clock ownership and data can require multiple object writes. Establish ordering
and interlocks from evidence before adding a writer. Tests must cover rejection
on either owner, timeout after send, disconnect and cancellation between writes.
A future implementation must stop dependent writes after failure, report partial
application, invalidate uncertain fields and reread all affected owners. Do not
claim atomicity or automatically roll back/replay a save. If reread fails,
editing remains unavailable until fresh readback reconciles state. Successful
source updates must not be interpreted as permission for unrequested manual
clock takeover.

Validate fractional offsets (including supported half/quarter-hour cases), date
boundaries, DST transitions and manual/network source changes independently.
Delay and solar-relay profiles require their own version/topology evidence;
clock or MANOVR validation does not enable them. Solar edits also require a fresh
configuration/association snapshot, preserving unknown or removed objects through
normal model reconciliation rather than inventing heater mappings.

Synthetic regression fixtures must remain labeled synthetic. No advanced writer,
hardware support profile, release, or dependency change is delivered by this
contract. HA #186 remains unfinished until device-dependent acceptance passes;
its prior closed status must not be interpreted as completion.
