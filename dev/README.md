# dev/ — development-time verification tools

Verification tools kept for whoever works on the skill: regression suites for
the validator and the local save server, and a **probe** for the
browser-capability boundary the template's save path depends on. None of this
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
dedupe, 429 backoff, and `--apply-image-review`'s atomic merge. No network: all
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
