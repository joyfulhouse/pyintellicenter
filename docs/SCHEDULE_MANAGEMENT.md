# Panel schedule management: evidence and delivery contract

Status as of 2026-10-25: configuration writes are **not validated**. Owning
request: [#99](https://github.com/joyfulhouse/pyintellicenter/issues/99).
No firmware is currently qualified for schedule create/edit/delete APIs.
The proposed `ScheduleSpec` and mutation methods in that issue do not exist.

## Evidence available

The current `_mixins/schedule.py` reads schedule objects, circuit references,
enabled state, and raw `DAY`, `TIME`, and `TIMOUT` values. It does not parse,
normalize, convert timezones, or serialize configuration. `STATUS=ON` means
enabled; `ACT=ON` means running. A missing/malformed status is not evidence
that a schedule is disabled; `is_schedule_enabled()` is a boolean convenience
helper, not a three-state observation API.

Issue #99 records static analysis of Pentair Pool 4.2.21 / 21615,
`com.pentair.pentairhome`, Hermes HBC v96 SHA-256
`ed262bd769b4ce8ba25e3faf5594f1a7d611b4db61d6b7cddd364e61be7f4526`.
The APKPure artifact's signing identity was not independently compared with
Google Play. Reproduction anchors:

| Function | Bytecode offset | Observation |
|---|---|---|
| 79341 | `0x0132ed4b` | SCHED creation templates, VACFLO/VACTIM/START/STOP, deletion using STATUS=DSTROY |
| 80769 | `0x01372e62` | Schedule-data conversion helper |
| 80771 | `0x01373317` | Schedule parsing helper |
| 80781 | `0x01373a71` | CreateSchedule controller |
| 80862 | `0x01377a33` | Schedule creation UI |

These are app-code observations, not captured requests or panel responses.
See [analysis PR #108](https://github.com/joyfulhouse/pyintellicenter/pull/108).
The report describes temporary analysis artifacts on the original analysis
machine; those artifacts are not present in this sandbox. Review of repository
source/history, issue comments, associated PRs and available configured MCP
resources found no sanitized schedule mutation round-trip capture. Existing
synthetic schedule tests establish software behavior only. The historical
enable-method revert `415e4d6` is not evidence for CRUD, nor a reason to remove
the downstream enable switches delivered later.

## Unresolved encodings

| Concern | Current observation | Evidence needed before a write contract |
|---|---|---|
| Time versus mode | Getters return TIME/TIMOUT unchanged; attribute comments describe START/STOP as absolute/sun-relative modes | Same-object request/readback showing all four fields; exact absolute token spelling, units, offsets and accepted formats |
| Weekdays | Existing DAY helper documents MTWRFAU (Monday through Sunday) | Single-day and multi-day round trips, ordering, duplicate/empty handling, and whether a day identifies the start or end of an overnight run |
| Overnight | No validated rollover contract | Before/after behavior for a permitted overnight schedule; equal endpoints, day/week boundaries, SINGLE and DNTSTP interactions |
| Timezone/DST | Getters perform no conversion | Panel timezone and clock configuration, wall-clock versus instant semantics, DST gap/fold behavior and sun-relative behavior; host/HA timezone differences |
| Heating | Attribute inventory contains HEATER, LOTMP, HITMP, COOLING, SMTSRT | Valid body/heater associations, sentinel meanings, units/ranges, heat/cool modes and omitted-field behavior |
| Lifecycle | App contains create/delete builders | Accepted envelope, edit patch versus replacement, error schema, allocated ID, notifications, authoritative inventory and subscription behavior |
| Vacation | VACFLO/VACTIM appear in templates | Separate UI-to-wire mapping, types, units, defaults and persistence; no inferred date range or duration |

Existing attribute comments and examples are leads, not validation of these
combinations. Preserve unknown values; do not silently reinterpret START/STOP
as clock values or TIME/TIMOUT as UTC. Vacation on/off is a separate existing
operation and does not qualify vacation schedule configuration.

## Minimum evidence package

Collection needs separate applicable authorization for panel mutations and an
operator-approved target and restoration plan. This document authorizes none.
Do not replay app builders as probes. Supply sanitized real captures, clearly
separated from generated test data, with:

1. Firmware, panel model, app version, transport, timezone/clock settings,
   relevant capability/configuration and capture provenance. Use stable aliases
   for identifiers while preserving cross-message references; remove secrets.
2. An authoritative baseline inventory and complete schedule read; then an
   authorized create/request/response/readback, edit/request/response/readback,
   delete/request/response/absence check and restoration verification. Retain
   correlation IDs, relative timing, notifications and inventory membership.
3. A matrix covering the unresolved encodings above for each advertised
   combination. Unsupported or unobserved combinations remain rejected.
   A successful acknowledgement alone does not prove persistence or execution.
4. Rejection behavior and reconnect observations. Exercise lost replies and
   duplicate prevention with a deterministic test transport first; do not
   intentionally disrupt a live panel to manufacture timeout evidence.

## Required implementation behavior once qualified

Use typed specs and capability-specific validation before I/O. Reject invalid
circuit/body/heater references, unsupported combinations and attempts to write
unknown/read-only fields. Preserve unknown fields on partial edits; if the panel
requires whole-object replacement, defer editing until safe round-tripping is
established. Distinguish omitted optional heating values from explicit clearing.

Await correlated responses through the existing request infrastructure.
Distinguish explicit rejection from success and uncertain outcome. A create
timeout, disconnect, or cancellation after sending can leave an object on the
panel: never automatically resend it. Return an explicit uncertain result and
reconcile from a fresh authoritative inventory. A matching name or matching spec
alone cannot identify the created object when another client can create one.
If identity remains ambiguous, expose candidates for explicit resolution and
block automatic retry; never delete or adopt an arbitrary match.

Confirm create/edit by readback and delete by authoritative absence. Merge
observed objects through normal model notifications/subscription setup, preserving
existing IDs and HA entities. Do not prune objects from a partial/failed read or
treat a cached missing object as confirmed deletion. After reconnect, reconcile
uncertain operations before any retry. Tests must cover rejection, lost reply,
concurrent identical creates, stale/partial inventory, cancellation, subscription
failure, reconnect and removal, in addition to every validated field encoding.

Downstream HA actions/forms depend on this contract and a published compatible
library. See [HA schedule management](https://github.com/joyfulhouse/intellicenter/blob/main/docs/schedule-management.md).
No package publication, dependency bump, or hardware mutation is required for
this evidence/documentation increment. Keep #99 open until its implementation
and device acceptance criteria are met.
