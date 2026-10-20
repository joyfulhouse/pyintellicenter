# Light-group action evidence and diagnostics

`controller.get_light_group_capabilities(parent_objnam)` returns immutable,
per-action cached eligibility decisions without network I/O. Use the enum
`LightGroupCapabilityReason` for programmatic decisions; `detail` is explanatory
text. Eligibility does not promise readiness: `run_light_group_sync()` still
performs both fresh preflights, subscriptions, a single write, sender-side onset
and terminal observation, the full 60-second post-terminal window, and a fresh
final projection under its existing mutation lease.

```python
from pyintellicenter import LightGroupAction

caps = controller.get_light_group_capabilities(parent_objnam)
for decision in caps.decisions:
    print(decision.action, decision.supported, decision.reason, decision.detail)

if LightGroupAction.SYNC in caps.validated_actions:
    await controller.run_light_group_sync(parent_objnam)
```

## Current decisions

Common cached gates apply to every action before action-specific decisions:

| Reason | Meaning |
| --- | --- |
| `unsupported_firmware` | Missing system info or firmware other than exact `1.064` |
| `unsupported_transport` | Transport other than local TCP or WebSocket |
| `unsupported_parent` | Target is not a `CIRCUIT/LITSHO` parent |
| `membership_count` | Target does not have exactly two membership rows |
| `malformed_membership` | Invalid references or list order |
| `unsupported_child` | Missing child or child other than `CIRCUIT/GLOW` |
| `duplicate_child` | Rows reference the same child |
| `incomplete_inventory` | Missing/ambiguous system or incomplete cached membership inventory |
| `malformed_cache` | Malformed cached optional projection fields |

When those gates pass:

| Action | TCP | WebSocket |
| --- | --- | --- |
| Sync | `validated` | `validated` |
| Set | `set_persisted_flags` | `set_persisted_flags` |
| Swim | `swim_late_mixed_state` | `swim_persisted_flags` |

Cached gate failures raised by the existing Sync writer now carry a `reason`
as `ICLightGroupCapabilityError`, inheriting both `ICError` and `ValueError`.
Existing `ValueError` handlers remain compatible. This exception is a
pre-dispatch failure; post-dispatch `ICLightGroupError` certainty/phase semantics
are unchanged. Set/Swim have no production writer. There is no member-position
writer or inferred finite position table.

## Why the app builders do not expand support

The prior hardware investigation ([intellicenter #93 closing comment][prior])
validated Sync on firmware `1.064`, two distinct GLOW children, both local
transports, and both uniform all-off/all-on prestates. The browser observed
`SWIM=ON/OFF` while local observers, including the initiating local connection,
observed `SYNC=ON/OFF`. A signal from another client cannot supply the library's
onset or terminal edge.

Local Set on both transports and WebSocket Swim lacked the terminal local
`SYNC=OFF` edge and left action flags persisted, including cross-group flags.
The longer TCP Swim run acknowledged at 0.008995 seconds, observed sender-side
`SYNC=ON` at 0.593273 and `SYNC=OFF` at 74.567605, then observed the children
return OFF at 83.613525 and 83.614324. Its fresh final projection was mixed:
parent ON, children OFF. A terminal edge and an earlier clean read were
insufficient. The production Sync deadline remains 60 seconds and the
post-terminal observation remains another 60 seconds.

Static evidence from Pentair Pool 4.2.21/build 21615 (Hermes HBC v96, SHA-256
`ed262bd769b4ce8ba25e3faf5594f1a7d611b4db61d6b7cddd364e61be7f4526`)
independently corroborates the selected-parent `SetParamList` shape. Functions
80713/80714/80715 at offsets 0x013705ec/0x0137068c/0x0137071d set exactly one
of `SET`, `SYNC`, `SWIM` to `ON`. It supplies no evidence that `ACT` or `STATUS`
is an equivalent action. The app resets all three flags to OFF in its own
model; those resets are not device terminal signals. See [evidence PR #108][app]
for the static analysis provenance, scope, and transport paths. No APK or
raw decompiled material is needed by this implementation.

## Offline capture review

The tool reads a local JSON file and opens no network connection:

```bash
uv run --frozen python -m pyintellicenter.light_group_diagnostics capture.json
```

It prints JSON with `accepted`, the action's capability decision, and `errors`.
Exit status is zero only for an already supported Sync capture that passes all
implemented checks; missing/malformed evidence or an unsupported action exits
one. A structurally clean Set/Swim trace remains unsupported. Diagnostics for
Set/Swim apply the existing Sync contract to expose known problems; they do not
assert that Sync's timing or final-state contract is appropriate for a future
Set/Swim implementation.

The callable API is
`pyintellicenter.light_group_diagnostics.validate_light_group_capture(capture)`.
It reuses the production topology, projection, subscription, invariant and edge
validators. The tracker accepts an injected clock for replay; production still
uses the running loop's monotonic clock. Invalid capture schema raises
`ValueError`; protocol and preflight failures are returned in the report.

Use `tests/fixtures/light_group/sync-tcp-off.json` as a version-1 format example.
It is a purpose-built regression reconstruction with sanitized role names and
representative timing where the hardware record provides only a range. It is
not a raw capture or new hardware evidence. The adjacent `prior-failures.json`
records the known persisted-flag, client-signal, and late-reversion markers used
by regression tests. Required capture fields are:

| Fields | Meaning |
| --- | --- |
| `schema_version`, `action`, `transport`, `group_objnam` | `1`, uppercase action enum, `tcp`/`websocket`, selected parent role |
| `cached` | Cached `objectList` inventory used for topology decisions |
| `baseline`, `settled`, `final` | Full authoritative safety-projection responses, including successful `response` and nonempty `messageID` |
| `subscriptions` | Ordered initialization responses for `build_subscription_batches(topology)`, with exact coverage |
| `subscription_settle_seconds` | At least one second before the second preflight |
| `request`, `acknowledgement`, `acknowledgement_at` | Exact single-parent action request, correlated response, elapsed seconds |
| `notification_source`, `connection_continuous` | Must be `sender` and `true`; never relabel UI/observer data as sender data |
| `write_watermark` | Enqueue sequence at transport write completion |
| `events` | Ordered `{at, sequence, frame}` records; `frame` is a raw `NotifyList` shape |
| `final_at` | Elapsed seconds at the authoritative final read, after the observation window |

Times are finite, nonnegative seconds relative to transport write initiation.
Sequences must retain strict sender enqueue order; onset must be after the
watermark. The validator rejects missing edges, uncorrelated acknowledgements,
collateral changes, malformed or incomplete projections/subscriptions, timing
violations, and late target reversions. Include the entire observation window,
even when the final read looks clean. Keep identifiers consistent when replacing
them with roles; exclude endpoints, credentials, names, and unrelated attributes.

The tool checks the supplied record. It cannot establish capture authenticity,
complete event coverage, actual connection continuity, physical results,
preflight activity omitted from the record, or restoration. A passing report is
not a substitute for the production lifecycle or independent device validation.
It cannot add firmware/topology support to the capability matrix.

## Remaining device gate

Issue #100 remains open. Before enabling Set/Swim or another Sync firmware or
topology, a separately authorized discovery pass must reproducibly correlate:

1. The initiating connection's exact request, subscription path, watermark,
   correlated acknowledgement, positive onset, and matching terminal edge.
2. Another observer and authoritative reads, explicitly resolving the
   client-dependent SYNC/SWIM field names and excluding app UI normalization.
3. Physical results and stable final/restored state across repeated runs and
   applicable prestates; TCP Swim's late child reversion must be resolved.
4. Collateral/concurrent actions, topology/service changes, cancellation,
   connection loss, and uncertain outcomes, without retrying uncertain writes.

No new live discovery, action replay, commissioning, or firmware installation
was performed for this change. Home Assistant continues to expose only its
existing gated Color Sync service. Group commissioning belongs to #104;
firmware-install lifecycle work belongs to #106. This additive capability/diagnostic
API requires no secondary HA PR or library dependency/version bump.

[prior]: https://github.com/joyfulhouse/intellicenter/issues/93
[app]: https://github.com/joyfulhouse/pyintellicenter/pull/108
