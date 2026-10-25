# FDR/FDP read-only observations and evidence gates

Issue [#107](https://github.com/joyfulhouse/pyintellicenter/issues/107) remains
open for local schema validation and automatic observation. The offline typed
API is `EventState`, `EventObservationReason`, and `observe_fdr_event`:

```python
from pyintellicenter import observe_fdr_event

# Supplied parameters must belong to one observation of _FDR.
state = observe_fdr_event(params, connected=connected, fresh=fresh)
print(state.active, state.event_id, state.raw_status, state.reason, state.raw)
```

This helper sends no requests, subscribes to nothing, and is not attached to
the controller lifecycle. It does not establish a hardware support contract.
It accepts the parameter mapping, not an entire response envelope. No firmware
fields are included. Each result and each raw property owns its copied values.
`raw` distinguishes an absent field from an explicit null. IDs are opaque;
zero, null, strings and unknown types are not normalized or used to infer state.

| Input/quality | `active` | Reason |
| --- | --- | --- |
| Disconnected/unavailable | `None` | `unavailable` |
| Connected but not explicitly fresh | `None` | `stale` |
| Fresh absent/null EVENTSTATUS | `None` | `missing_status` |
| Fresh exact string `running` | `True` | `running` |
| Any other fresh status, including a key echo | `None` | `unknown_status` |

The return annotation is `bool | None`, but **no False mapping is enabled**:
no inactive value is device-validated. The exact `running` comparison comes
from the app, not a captured panel status. No case folding, truthiness, numeric
mapping, event cancellation or completion is inferred. A missing/empty object
does not prove unsupported hardware or inactivity. Raw fields survive stale
and unavailable observations for diagnostics; their presence does not make
them current. Default connection and freshness flags are false.

Observations replace rather than merge fields. A changed ID without status
cannot inherit a previous event's running flag. Callers must invalidate fresh
state on disconnect and require new evidence after reconnect, including a fast
reconnect. Merely reattaching cached parameters is insufficient. This API does
not choose a TTL, track generations, or claim a subscription notification proves
freshness of an omitted field. A future automatic monitor must handle those
rules using validated local snapshot/notification behavior.

## Evidence reviewed

- [Issue #107](https://github.com/joyfulhouse/pyintellicenter/issues/107) and
  [protocol PR #108](https://github.com/joyfulhouse/pyintellicenter/pull/108):
  function 79341 (`0x0132ed4b`) has `_FDR` snapshot/subscription templates;
  79486 (`0x01335c53`) reads EVENTSTATUS/EVENTID and compares with `running`;
  79485 (`0x01335b45`) navigates to FDP scheduled-event details.
- Function 79651 (`0x0133cde6`) derives the UI gate from
  `featureConfigReducer.cecConfig.isEnable`. This reducer path does not establish
  a local panel enable flag or prove the configuration's cloud origin. Local
  observation without enrollment/the flag remains unverified.
- [Issue #12, captured definition response](https://github.com/joyfulhouse/pyintellicenter/issues/12#issuecomment-3765379001)
  contains `_FDR` with OBJTYP/SUBTYP/SNAME/PARENT key echoes. This proves that
  object-name visibility alone is insufficient; it contains no event status.
  Existing model tests preserve rejection of such pruned definition artifacts.
- Repository fixtures/history contain no captured active/inactive event values
  or correlated local subscription lifecycle. Synthetic tests in
  `tests/test_events.py` are explicitly not captured panel fixtures.

Static provenance: Pentair Pool 4.2.21/build 21615,
`com.pentair.pentairhome`, APKPure arm64 XAPK, Hermes v96 SHA-256
`ed262bd769b4ce8ba25e3faf5594f1a7d611b4db61d6b7cddd364e61be7f4526`.
Analysis dated 2026-10-20; mirror signing identity was not independently compared
with Google Play. See #107 and PR #108 for the reproduction details. No live
panel requests, enrollment, firmware operations or event actions were performed.

## Required evidence before automatic subscriptions and HA delivery

Collect authorized, sanitized, time-ordered local read responses and NotifyList
messages, preserving keys, types, explicit nulls, missing fields, object names,
request correlation, hardware/firmware and transport. Do not include credentials
or identifying account details; replace event IDs consistently if sensitive.

1. Snapshot and subscription success/rejection for an enabled/supported panel,
   and an unavailable/unsupported or feature-disabled case. Separate a missing
   object, key echo and missing status from confirmed inactivity.
2. Naturally observed active and confirmed inactive states, with independently
   verified meaning of each exact wire value. Capture changed EVENTID, partial
   updates, unknown values and event end. Do not trigger enrollment or event
   cancellation to manufacture these examples.
3. Disconnect/reconnect and fresh snapshot/subscription restoration, including
   fast reconnect, response/notification ordering and whether omitted fields
   retain meaning for the same or a changed ID.
4. Establish the source/meaning of `cecConfig.isEnable`, enrollment dependencies,
   and whether local fields can be read without the app/cloud feature gate.

Then add a separately reviewed controller observation/subscription contract and
HA diagnostic entity. Reuse existing bounded additive notifications and
reconnect handling; do not admit `_FDR` as a normal PoolObject by inventing
OBJTYP. Keep firmware progress separate. Details retrieval, opt-out, enrollment
and cancellation are outside this read-only scope.
