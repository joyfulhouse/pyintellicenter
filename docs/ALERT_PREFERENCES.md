# Panel Alert Preferences: Evidence and Delivery Gates

Panel alert-preference reads and updates are **unavailable**. There is no
validated preference wire schema, device/firmware capability table, or captured
before/write/readback round trip in the evidence reviewed for
[#102](https://github.com/joyfulhouse/pyintellicenter/issues/102). Proposed
`get_alert_preferences()` and `update_alert_preferences()` names in that issue
are design suggestions, not public APIs. Do not send guessed arguments.

`get_chem_alerts()` and `has_chem_alert()` describe active chemistry faults.
They do not read notification preferences. A disabled notification must never
clear an active fault, and a quiet panel does not establish disabled preferences.
Transient delays and delay cancellation are separate, unverified operations.

## Evidence Reviewed

The owning issue and [protocol report PR #108](https://github.com/joyfulhouse/pyintellicenter/pull/108)
identify these static app observations:

| Reference | Established observation | Still unresolved |
|---|---|---|
| Function 83391, `0x013e57ae` | `GetQuery` / `GetStatusMessageFlags`, `SetCommand` / `SetStatusMessageFlags`, and `ALL_ALERTS_ENABLE` / `ALL_ALERTS_DISABLE` exports | Argument population, target identity, value encoding, defaults, response envelope, partial versus replacement writes, bulk behavior |
| Function 83477, `0x013e9c7d` | Configurable/critical alert and CDN/schema compatibility helpers; supported schema array includes `1.0` | Critical flag semantics, device applicability, metadata URL/provenance and loading behavior |
| Function 83490, `0x013ea001` | Reads `configurableAlerts` metadata | Exact definitions and relationship to panel flag IDs |

These references identify Pentair Pool 4.2.21/build 21615,
`com.pentair.pentairhome`, HBC v96, Hermes SHA-256
`ed262bd769b4ce8ba25e3faf5594f1a7d611b4db61d6b7cddd364e61be7f4526`.
The APKPure mirror signing identity was not independently compared with Google
Play. Function offsets are specific to this asset. Static exports do not prove
that a particular panel supports a command or that bulk disable excludes
critical alerts.

On 2026-10-25, the repository source, history, issue comments, open protocol
report, sibling integration audit, local artifact filenames, and configured
MCP resources supplied no panel captures or matching APK/disassembly. The
report locates artifacts at `/tmp/pentair-analysis` on the original analysis
machine; that directory is absent in this sandbox. Repository memory recall
found no library bank and no relevant integration facts. This is a bounded
evidence gap, not proof that the panel lacks the feature.

## Required Read and Update Contract

The following are requirements for a future implementation, not observed panel
behavior or permission to perform device writes:

1. Trace the exact app argument population and response processing. Capture a
   sanitized correlated read request/response with panel model, firmware,
   transport, device identifier, schema version, timestamp and provenance.
   Record unsupported-command, missing-data and malformed-response cases.
   Unknown support is distinct from supported with no configurable alerts.
2. Obtain metadata that maps each writable flag to its device and schema, and
   establishes which flags are critical, configurable, or unknown. Unknown
   flags retain their original representation. Missing metadata must not
   produce defaults, enable writes, or turn unknown values into false.
3. With separately authorized device testing, capture a targeted preference
   change and an independent fresh read. Compare all returned flags, including
   critical and unrecognized flags, with the before snapshot. Establish whether
   the command patches flags or replaces a complete preference set. Do not
   expose bulk enable/disable until its critical/unknown behavior is verified.
4. For replacement writes, define conflict detection using a device revision
   if available. Otherwise re-read immediately before writing, serialize local
   preference updates, and reject an observed stale baseline. Local locking
   cannot protect against the app or another client; document the remaining
   race and keep writes disabled if preservation cannot be guaranteed.
5. Verify the target device and fresh readback independently of the write
   acknowledgement. Compare the requested values and preservation of unrelated
   flags; distinguish rejected, partially applied, mismatched and unverified
   outcomes. A timeout/disconnect after submission is uncertain. Do not blindly
   retry, optimistically claim success, or restore an entire stale snapshot.
6. Cover critical/unknown flag preservation, unsupported devices, unknown schema
   versions, rejection, concurrent changes, stale reads, readback mismatches,
   timeouts and reconnects with independently sourced fixtures. Synthetic
   protocol examples must be labeled as such and cannot establish capability.

## Metadata Caching and Offline Policy

No external definitions are fetched or cached by this feature today. The
following policy must be implemented and tested before external metadata can
enable configuration controls:

- Keep descriptive metadata separate from panel preference values and active
  faults. Store provenance, schema version, device applicability, retrieval
  time and content digest with each validated metadata snapshot. Schema `1.0`
  in an app array alone does not establish a validated library schema.
- Key caches by verified source, schema and applicable device family. Validate
  the entire replacement before atomically accepting it; a failed refresh must
  preserve the last validated snapshot. Define bounded payload size, request
  timeout, refresh interval and expiry from the traced source contract before
  adding a network client. Do not fetch arbitrary device-supplied URLs.
- Offline metadata may supply last-known descriptive labels with explicit
  staleness. Missing, incompatible or expired definitions must not grant write
  capability or reinterpret unknown flags. Never overwrite panel values from
  cached metadata defaults.
- Panel disconnect invalidates preference freshness and disables writes. Any
  retained preference values are last-known observations, not current state.
  Reconnection requires a fresh supported preference read and applicable
  metadata before re-enabling writes. Metadata refresh alone cannot freshen
  panel state. A metadata outage must not fail ordinary pool-control setup.

## Downstream Dependency

Home Assistant configuration entities/actions depend on a published library
contract with validated capability and readback behavior. No library version
bump, package publication, integration dependency change or live device mutation
is needed for this evidence report. Track remaining delivery in
[intellicenter #188](https://github.com/joyfulhouse/intellicenter/issues/188).
