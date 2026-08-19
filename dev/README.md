# dev/ — development-time verification tools

Verification tools kept for whoever works on the skill: regression suites for
the validator and the local save server, and **probes** for the two outside
boundaries the template depends on — the browser capability its save path
needs, and the public routing service its transport feature calls. None of this
is part of the skill itself; `npx skills add` does not install them.

**Acceptance rule — this is not optional.** Any change under
`skills/to-where-for-what/scripts/` or to `assets/template-trip.html` must have
all three suites run and green *before* it is committed. They reach no outside
network and take seconds; a suite that fails is either a regression to fix or an
assertion whose contract the change deliberately replaced — say which, in the
commit.

```bash
python3 dev/test_enrich_images.py
python3 dev/test_validate.py
python3 dev/test_server.py
```

## test_enrich_images.py

Regression tests for `enrich.py`'s image candidate pipeline — identity grading,
family order and the candidate cap, the glance/full tiering, the run cache and
dedupe, 429 backoff, candidate byte saving into `image-review/` (extensions,
byte-dedupe, the 2MB ceiling, incremental carry-over) with the cap-aware cache
that keeps a 64KB check body from being served as the full image, and
`--apply-image-review`'s atomic merge and cleanup. No network: all
HTTP is stubbed at `enrich.http_get`, and the retry/method cases one level
deeper at `urllib.request.urlopen`. Run after any change to the image pipeline
or to the audit contract the visual review pass reads.

```bash
python3 dev/test_enrich_images.py
```

## test_validate.py

Regression tests for `scripts/validate.py` — corrupt the data deliberately,
assert the validator catches it. Run before and after any change to the
validator or to the data contract it enforces.

```bash
python3 dev/test_validate.py
```

## test_server.py

Black-box tests for `build.py`'s local save server: builds a throwaway trip,
starts a real `--serve` process on a random port, and talks to it over HTTP.
Asserts the prep round-trip, the save-token / Origin / Content-Type gates, and
that dotfiles are never served. Run after any change to `build()`, `merge()`,
`SERVER_SRC`, or the template's save path.

```bash
python3 dev/test_server.py
```

## capability-probe.html

Probes the real-world availability of the File System Access API and related
capabilities under the current browser and protocol.

```bash
# via file://
open dev/capability-probe.html

# via http:// (for comparison)
python3 -m http.server 8901 --directory dev
# then open http://localhost:8901/capability-probe.html
```

### Verified findings (2026-07-31, Chromium)

During planning, the "secure context (HTTPS)" wording in
[MDN](https://developer.mozilla.org/en-US/docs/Web/API/Window/showSaveFilePicker)
and Chrome's documentation led to the assumption that `showSaveFilePicker`
would be unavailable under `file://`. **Testing refuted that assumption:**

| | `file://` | `http://localhost` |
|---|---|---|
| `isSecureContext` | `true` | `true` |
| `showSaveFilePicker` | `function` | `function` |
| Actual call | opens the native save dialog | opens the native save dialog |

The two protocols behaved identically; neither threw a `SecurityError`.

**The real capability boundary is the browser engine, not the protocol**
(source: [MDN BCD](https://github.com/mdn/browser-compat-data)):

| Chrome 86+ | Edge | Opera | Firefox | Safari desktop |
|---|---|---|---|---|
| ✅ | ✅ | ✅ | ❌ | ❌ |

So the skill's save-capability detection **must use feature detection**:

```js
const canWriteBack = typeof window.showSaveFilePicker === 'function';
```

Never `location.protocol === 'http:'` — that would needlessly strip
direct-write from Chrome users who opened the file by double-clicking, and it
still wouldn't catch the Firefox/Safari users who genuinely need the fallback.

The protocol affects **something else entirely**: `file://` sends no
`Referer`, so the official OSM raster tiles are unavailable (see the map
sections under `skills/to-where-for-what/references/`). The two dimensions must
be judged separately.

## osrm-probe.html

Health check for the outside service behind "generate transport": the FOSSGIS
public OSRM instances at `routing.openstreetmap.de`. It hardcodes one Osaka
segment and asks `routed-foot` and `routed-car` for it with the exact query the
template sends, printing HTTP status, the body's `code`, distance/duration,
geometry length and the decoded endpoints.

**Not a regression test** — it reaches the network on purpose, so it is
deliberately outside the three commands above. Open it when the feature
misbehaves and you need to know whether the code broke or the service did.

```bash
open dev/osrm-probe.html
```

Baseline (2026-08-16, Chromium, `file://`): both profiles HTTP 200 / `code: Ok`;
same 4.5 km segment comes back as 3604.6 s on foot and 523.2 s by car —
distinct profiles, not one instance answering twice. `overview=simplified` +
`polyline6` yields 228 chars / 49 points (foot) and 112 chars / 21 points (car).
The car route's endpoints snap up to a few hundred metres onto the nearest
drivable road, which is why the template stitches the real markers back on.
