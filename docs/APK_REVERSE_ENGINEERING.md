# Reproducing Pentair Android APK Analysis

This workflow supports the dated
[Pentair app local protocol report](PENTAIR_APP_LOCAL_PROTOCOL.md). It covers
static inspection of Android resources, DEX, and React Native Hermes bytecode.
It does not execute the app or send commands to equipment.

## Artifact Identity

The analyzed package is `com.pentair.pentairhome`, branded Pentair Pool,
version 4.2.21 / build 21615. The input was an APKPure XAPK containing a base
APK and arm64-v8a, English, and xxxhdpi splits. The report records the download
endpoint, sizes, hashes, and the limits of third-party artifact provenance.

The endpoint uses `version=latest`: it is not a reproducible version pin.
Obtain an artifact matching the report's hashes for exact reproduction. A newer
version requires a new evidence index; function IDs and offsets are not stable
across builds. Keep binaries and generated decompiled output outside the source
tree. Record acquisition source/date and tool versions with each analysis.

Use a new analysis directory containing the input as `app.xapk`:

```sh
unzip -t app.xapk
sha256sum app.xapk
unzip app.xapk -d bundle
unzip -t bundle/com.pentair.pentairhome.apk
unzip -p bundle/com.pentair.pentairhome.apk assets/index.android.bundle > index.android.bundle
sha256sum bundle/com.pentair.pentairhome.apk index.android.bundle
file index.android.bundle
```

Compare all three hashes with the report before using its function references.
The bundle is Hermes bytecode version 96, not plain JavaScript. An HTML challenge
page downloaded with an `.xapk` filename is not an APK archive.

## Tool Setup and Extraction

The original analysis used JADX 1.5.3, Apktool 3.0.3, and this hermes-dec commit:

```sh
git clone https://github.com/P1sec/hermes-dec.git hermes-dec
git -C hermes-dec checkout --detach 2e796663e1fedb93dca51060797ebf3327b3fedb
python3 hermes-dec/hbc-disassembler index.android.bundle app.hasm
python3 hermes-dec/hbc-decompiler index.android.bundle app.js
```

The pinned hermes-dec source runs with Python 3.10+ and uses the standard
library. Obtain the pinned JADX distribution and Apktool JAR from their upstream
releases, put JADX on PATH, and place the Apktool JAR at `apktool.jar`:

```sh
jadx --version
java -jar apktool.jar --version
jadx --no-res -d java bundle/com.pentair.pentairhome.apk
java -jar apktool.jar d -s -o decoded bundle/com.pentair.pentairhome.apk
```

JADX's full run reported 17 decompilation errors. Record these rather than
claiming every DEX method was recovered. The protocol findings principally
come from Hermes, while DEX/resources corroborate native discovery and network
configuration. Apktool's `-s` skips smali generation.

| Output | Use |
|---|---|
| `decoded/AndroidManifest.xml`, `decoded/res/xml/` | Package/SDK metadata and network-security configuration |
| `java/sources/` | Native modules, including the Zeroconf bridge |
| `app.hasm` | Function headers, bytecode instructions, resolved strings and object/array literals |
| `app.js` | Decompiled pseudocode for navigation and preliminary control-flow understanding |

## Find and Extract Evidence

Start with bounded searches rather than dumping the whole bundle:

```sh
rg -n --max-columns 1000 --max-columns-preview 'RequestParamList|NotifyList|GetStatusMessageFlags|ReadHistoryMessage' app.hasm
rg '^=> \[Function #' app.hasm > function-index.txt
```

Extract individual functions by their headers. This example writes the Color
Set builder without relying on line numbers in the large disassembly:

```python
from pathlib import Path
import re

target = 80713
selected = False
lines = []
with Path("app.hasm").open() as source:
    for line in source:
        header = re.match(r"=> \[Function #(\d+) ", line)
        if header:
            if selected:
                break
            selected = int(header.group(1)) == target
        if selected:
            lines.append(line)
if not lines:
    raise ValueError(f"Function {target} not found; verify artifact identity")
Path(f"function-{target}.hasm").write_text("".join(lines))
```

For every capability, follow the path from UI/controller through request
construction to sender, and separately trace response/model handling. Record
function ID, function-start bytecode offset, relevant relative instruction
offsets, literals, predicates, and unresolved dependencies. Where a closure is
created, inspect the referenced function and captured environment rather than
guessing from its name or size.

The APK contains multiple Pentair product families, SDKs, translations, and
embedded assets. A string match alone is not attribution to IntelliCenter.
Establish the screen/module and local-vs-cloud branch, especially for shared
senders, history, registration, and Bluetooth provisioning.

## Interpretation Pitfalls Found in This Analysis

- **Computed property keys:** the generated pseudocode can render a
  `PutOwnByVal` key as a register-number literal instead of the computed key.
  Check register assignments in `app.hasm` before reconstructing JSON.
- **Template values vs final requests:** `activty_status` is an initial
  message-ID value, not a boolean request field. The heartbeat sender replaces
  it with a UUID. Trace mutations after template creation.
- **Client state vs panel state:** local resets of `SET`, `SYNC`, or `SWIM`
  to OFF do not prove that a physical light action completed. Keep authoritative
  readback and device observations separate from app UI normalization.
- **Field names vs semantics:** `_FDR` feeds a scheduled-event banner/details
  path. It is not firmware-update progress. Persistent `VALVE`/`HEATING` delay
  settings do not imply transient delay cancellation.
- **Flags vs development status:** IntelliBlue's `hyp1.itelliblueEnabled`
  gate has substantial handlers behind it. A flag or firmware condition is not
  evidence that a feature is abandoned, unfinished, or universally supported.
- **Requested fields vs support:** query keys can be absent, unsupported, or
  echoed by a panel. Do not turn a client-requested key list into a guaranteed
  device schema.

## Evidence and Publication Checklist

1. Record package/build, hashes, tools and errors. Separate app observations,
   inferred behavior, and device-confirmed behavior.
2. Reconstruct only the necessary payloads with placeholder object IDs. Check
   JSON syntax and confirm each field against bytecode and subsequent mutations.
3. Cite UI gates and transport dependencies. Document missing paths instead
   of extrapolating from other Pentair products.
4. Compare with current library/HA code and existing issues; do not recreate
   shipped features from an old backlog. Preserve prior device evidence where
   app builders do not resolve a known limitation.
5. Publish concise evidence, not entire decompiled applications or binaries.
   Redact credentials, permission responses, and device/account identifiers
   from any future captured fixtures.
6. Validate hashes, evidence offsets, JSON examples, and documentation links.
   Use the issue tracker for implementation progress; static analysis alone
   does not complete a feature or justify changing firmware capability gates.

The [capability tracker](https://github.com/joyfulhouse/intellicenter/issues/188)
links the research and implementation requests from this analysis. Future
device validation should record firmware, topology, transport, request/response
ordering, final readback, and uncertain outcomes before proposing supported writes.
