# Access capabilities: evidence and capture contract

Investigation for [#105](https://github.com/joyfulhouse/pyintellicenter/issues/105),
2026-10-23. This is a bounded schema/security report, not a hardware support
claim. No panel session, cloud login, permission change, or remote deletion was
performed. Unknown access state must remain unknown; it never grants admin access.

## Sources and boundaries

The issue body and comments were inspected on 2026-10-23 (no comments).
Static evidence comes from documentation at evidence commit
`872d63089e6a9fe19935b28ff4fb0fe803fa4d90` (PR #108), read without merging it:

- [Local protocol report](https://github.com/joyfulhouse/pyintellicenter/blob/872d63089e6a9fe19935b28ff4fb0fe803fa4d90/docs/PENTAIR_APP_LOCAL_PROTOCOL.md)
- [Reproduction instructions](https://github.com/joyfulhouse/pyintellicenter/blob/872d63089e6a9fe19935b28ff4fb0fe803fa4d90/docs/APK_REVERSE_ENGINEERING.md)

Those reports identify Pentair Pool `com.pentair.pentairhome` 4.2.21 / 21615,
Hermes v96 SHA-256
`ed262bd769b4ce8ba25e3faf5594f1a7d611b4db61d6b7cddd364e61be7f4526`.
The APKPure mirror signing identity was not independently verified against
Google Play. Function references apply only to that artifact. This investigation
reviewed the reports, not the original APK or disassembly; detailed bit masks,
role mappings, timing units, and request arguments remain unresolved.

| Surface | Evidence | Boundary |
|---|---|---|
| Local panel permissions | App local connect flow 79292 / `0x0132c255`; permission predicates 79305 / `0x0132c92c`, 79306 / `0x0132c963` | App compares enabled role records and entered passcode. Panel enforcement and authentication exchange are unverified. |
| Cloud accounts / invitations | Shared remote connection path 84324 / `0x0140d104` supplies installation ID and access token | Separate identity/authorization domain. Local permission records do not prove cloud membership, ownership, or invitation rights. No cloud account API validated. |
| Physical remote controllers | Module 82555 / `0x013bc229` contains `GetRemotes` / `DeleteRemote` templates | Inventory lead for panel-connected remotes, not cloud users. Response schema, authorization, remote types, and deletion effects are unknown. No inventory API validated. |

The issue additionally identifies `PERMISSION_ARRAY` at 82769 / `0x013c5689`
and a local permission component at 82773 / `0x013c6067`. UI choices do not
establish a stable wire role enum or hardware authorization contract.

## Permission fields

Function 79341 / `0x0132ed4b` contains the permission query template, with
condition `OBJTYP = PERMIT` and requested keys `ENABLE`, `PASSWRD`, `SHOMNU`,
`TIMOUT`. Requested keys are not a guaranteed device response schema.

| Field | Established evidence | Unresolved interpretation / safe treatment |
|---|---|---|
| `PERMIT` | Object type in permission query; library also defines a system `PERMIT` attribute | Do not conflate object type, system flag, and caller authority. System flag scope and enabled/disabled encodings require readback. |
| `ENABLE` | Requested by app; enabled-record predicates exist | Exact values, missing-field behavior, role association, and panel enforcement unknown. Missing/echoed values do not mean enabled or administrator. |
| `PASSWRD` | Requested by app; entered-passcode comparison in app predicates | Sensitive even when empty. Existing source comments describe four digits or empty, but neither format nor exchange is device-validated here. Do not expose in diagnostics or invent a login command. |
| `SHOMNU` | Requested by app; existing library calls it privileges/menu permissions | Encoding, masks, precedence, and relation to actual panel authorization unknown. Do not convert to an admin boolean. |
| `TIMOUT` | Requested by app; library comment describes session timeout in minutes | Units, sentinel values, expiry/reset behavior, and app versus panel enforcement unverified. Preserve raw data privately; no automatic timeout semantics. |
| `SUBTYP` | Existing library comments label `ADV` administrator / `BASIC` guest | Historical labels are not validated authority. Unknown/missing subtypes remain unknown. |

The app includes a warning for security-disabled local mode. This establishes
an app UI branch, not universal unauthenticated access or proof that the panel
rejects unauthorized writes. A successful socket connection or permission read
also does not establish authorization. Passcode transmission, session binding,
expiry, and panel-side enforcement need separate evidence. A read-only study
cannot prove enforcement of writes; leave that cell unverified.

## Firmware and transport support

Each cell concerns access/remote administration, not basic equipment support.
There are no device-confirmed access fixtures in this investigation.

| Firmware / evidence | Transport | Permission reads / field schema | Passcode / enforcement | Physical remote inventory | Administration writes |
|---|---|---|---|---|---|
| Unspecified panel; app 4.2.21 static code | Local WebSocket / 6680 | Builder observed; device support unverified | App predicates observed; panel behavior unverified | Template observed; arguments/schema unverified | Not supported by this work |
| Unspecified panel | Local TCP / 6681 | Unverified | Unverified | Unverified | Not supported by this work |
| 3.008+ mentioned in model pruning comments | TCP / WebSocket separately | Unverified; key echoes may be pruned | Unverified | Unverified | Not supported by this work |
| IC 1.064 / ICWEB 2021-10-19 1.007 in production soak | TCP / 6681 | Access-specific behavior unverified; equipment soak is not access evidence | Unverified | Unverified | Not supported by this work |
| Other firmware, including future versions | Any local transport | Unverified | Unverified | Unverified | Not supported by this work |
| Any firmware | Cloud / remote connection | Separate domain; unverified | Token flow is not local permission evidence | Unverified | Not supported by this work |

The [production soak report](https://github.com/joyfulhouse/intellicenter/blob/fa395ef921521241af7ad9a488701d98007b7a85/docs/PRODUCTION_SOAK_3.12.0.md)
identifies integration 3.12.0b2 promoted to 3.12.0 with library 0.3.0;
those are software release versions, not controller firmware. It establishes
no access-specific support, and supplies no WebSocket access evidence.

No new public API or capability flag is added. Existing `send_cmd`, `get_query`,
raw connection reads, model values, and attribute constants remain generic
interfaces, not validated access-management APIs. No role/passcode/remote delete
write is added. Calibration, firmware, commissioning, and light-action guards
remain governed by their existing evidence requirements.

## Diagnostic disclosure correction

Synthetic tests demonstrate that earlier code disclosed permission material in
non-object JSON frame logs, malformed model entry logs, controller malformed
system-info/subscription exceptions, and `PoolObject` string representations.
The correction omits entire rejected payloads from those logs/exceptions, so
malformed shape cannot bypass a key-based filter. Error codes and rejection
reasons remain available. `PoolObject.__str__` / `__repr__` recursively mask
case-insensitive `PASSWRD`, `password`, and `passcode` dictionary fields, including
nested lists/tuples. Returned model and protocol values remain unchanged.

This is scoped diagnostic protection, not a general secret scrubber. Generic
`ICResponseError` accepts caller-supplied text; arbitrary application exceptions,
callback tracebacks, raw dictionaries, user logging, packet captures, other
credential key names, identifiers, and account/location data are not sanitized
by this change. JSON parse errors log parser descriptions, not raw frames.
Raw broad system reads and permission responses must still be handled privately.
Do not publish object/model dumps as sanitized evidence. A caller that logs raw
responses or wraps them into exception text must sanitize at its own boundary.

## Read-only capture protocol

An owner with an authorized test panel can supply the following evidence. This
is a future manual capture protocol, not an automated probe or permission to
contact production. No credentials or production access are needed for this PR.

1. Record firmware for panel/modules, app version, topology, transport/port,
   local versus cloud branch, and a pseudonymous session ID. Record the panel's
   already-configured security mode and role as owner-reported observations;
   do not change roles, passcodes, or security settings for this capture.
2. Use an owner-approved local session with payload logging disabled. Record
   open/read/response/close ordering and correlated message IDs with timestamps.
   Do not connect through cloud or submit credentials to an invented endpoint.
3. Send one app-derived snapshot, without subscriptions or writes:

   ```json
   {"command":"GetParamList","condition":"OBJTYP = PERMIT","objectList":[{"objnam":"ALL","keys":["ENABLE","SHOMNU","TIMOUT"]}],"messageID":"capture-permit-1"}
   ```

   This intentionally omits `PASSWRD` to minimize collection; it is a reduced
   research request, not a validated request contract. If denied, timed out,
   echoed, absent, or malformed, record that result and stop. Do not retry with
   broader reads or infer authorization. If an owner already has a private app
   trace containing `PASSWRD`, report only presence/type/empty-versus-present;
   never retain or share its value or hash (short codes are guessable).
4. Keep field presence, JSON type, response code, and key-echo observations
   distinct from interpreted values. A key equal to its own value is unsupported
   or ambiguous evidence, not a capability. Correlate security-disabled UI
   observations with the same existing session; do not infer a role from absence.
5. For physical remotes, first obtain a sanitized existing app read trace that
   establishes `GetRemotes` arguments and response structure. The template name
   alone is insufficient for a new probe. Do not run `DeleteRemote`, `SetCommand`,
   `SetParamList`, create/edit/delete, passcode, role, or account operations.
6. Before sharing, recursively remove all passcodes/tokens and personal fields,
   replace device/account/remote IDs consistently, and review error text and
   malformed payloads manually. Preserve schema/type information separately.
   Keep original sensitive captures private; never commit them. Supply sanitized
   request/response pairs, firmware/transport, observation ordering, and explicit
   unknowns. A fixture must be labelled device-captured versus synthetic.
7. Repeat only on separately authorized firmware/transport configurations. Add
   a validated read API only after reviewing actual schemas, denial behavior,
   reconnect behavior, and redaction. Write enforcement and recovery-capable
   administration testing remain a separate investigation requiring approval.

Remaining evidence needed: correlated permission snapshots for each firmware
and transport, app passcode-flow traces with secrets removed, observed existing
security-disabled behavior, and physical-remote inventory read arguments/schema.
Cloud invitations/accounts require a separate cloud contract. Issue #105 remains
open; this report and synthetic regression tests do not close hardware research.

## Follow-up audit: 2026-10-25

Reviewed current issue #105 and tracker intellicenter #188 (including comments),
merged access PR #114 and release PR #115, the current analysis branch for #108,
and the companion integration analysis PR #189. None supplies device-captured
permission or physical-remote request/response evidence. Historical delay/light
capture plans contain synthetic `PASSWRD` examples, not permission captures;
equipment soak results do not fill the access matrix above. Configured MCP
resource and resource-template listings expose no additional capture source.
The repository memory skill is installed, but no recall tool is exposed in this
session; memory is not evidence of device behavior.

Library 0.3.1 masks credential fields in object string representations and omits
rejected payloads from its own diagnostic failures. Consumers serializing raw
`PoolObject.properties` must still redact at their export boundary. In particular,
Home Assistant diagnostics export raw properties rather than these string
representations; library masking alone cannot protect that export. Unstructured
exception text must also be omitted rather than assumed safe after key redaction.

The next evidence submission must include the following, with credentials and
personal identifiers removed as described above:

| Question | Required evidence before a supported read API |
|---|---|
| Permission schema | Correlated request/response pairs and field JSON types for each actual panel/module firmware and TCP or WebSocket transport; include absent, echoed, malformed, denied and timeout results where observed. |
| Role and passcode behavior | Existing authorized app-session traces showing record selection, whether credentials cross the wire, and session/reconnect/expiry ordering. Record app-side versus panel-side enforcement separately; read success cannot prove write authority. |
| Security disabled | Owner-observed existing security mode correlated with the same session and returned field values. Do not disable security for collection or infer admin from missing records. |
| Physical remotes | Existing app `GetRemotes` request with exact argument names, types and values replaced by stable aliases, plus response envelope, inventory record schema, empty result, denial and reconnect observations. Do not guess arguments or execute deletion. |
| Administration | Separately authorized recovery-capable testing establishing enforcement, denial, mutation readback and recovery. No write API is enabled by completion of the read investigation. |

These are outstanding evidence requirements, not assertions that the scenarios
have been tested. The cloud identity/invitation contract remains a separate
investigation. No library release or integration dependency change is required
for this report; the integration can continue using published 0.3.1.
