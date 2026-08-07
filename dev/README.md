# dev/ — development-time verification tools

Two things kept for whoever works on the skill: a **regression suite** for the
validator, and a **probe** for the browser-capability boundary the template's
save path depends on. Neither is part of the skill itself; `npx skills add`
does not install them.

## test_validate.py

Regression tests for `scripts/validate.py` — corrupt the data deliberately,
assert the validator catches it. Run before and after any change to the
validator or to the data contract it enforces.

```bash
python3 dev/test_validate.py
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
