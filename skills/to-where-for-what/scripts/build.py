#!/usr/bin/env python3
"""Inject places.json + route.md into the template to produce a single-file trip.html.

Usage:
    python3 build.py <trip-dir>                 # generate trip.html
    python3 build.py <trip-dir> --serve         # generate, start a background server, print the URL and return
    python3 build.py <trip-dir> --stop          # stop that directory's background server
    python3 build.py <trip-dir> --standalone    # output only the guide page guide.html (for sharing/deployment)

Why the JSON is inlined into the HTML instead of fetch()ed by the page:
    Under file://, fetch is killed by CORS. Inlined, both double-click opening
    and http work.

Why --serve is the recommended default:
    file:// sends no Referer, so OSM's official tiles return an "Access
    blocked" image (HTTP 200 — only the eye catches it). Over http://localhost
    everything is compliant.
    Note: the ability to save files is unrelated to the protocol (measured:
    showSaveFilePicker works under file:// too) and depends only on whether
    the browser is Chromium-based.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import signal
import subprocess
import sys
import time
import webbrowser
from pathlib import Path

SKILL_ROOT = Path(__file__).resolve().parent.parent
TEMPLATE = SKILL_ROOT / "assets" / "template-trip.html"

DATA_MARK = "/*__TRIP_DATA__*/null"
ROUTE_MARK = "/*__ROUTE_HTML__*/null"
# The same guide body a second time, as the Markdown the AI actually wrote.
# The page's Markdown export hands it back verbatim; reconstructing it from
# ROUTE_MARK's HTML would be a lossy round-trip, and the ~13KB it costs is 2%
# of a trip page.
ROUTE_MD_MARK = '/*__ROUTE_MD__*/""'
TRANSIT_MARK = "/*__TRANSIT__*/null"
SORTABLE_MARK = "/*__SORTABLE__*/"
BUILT_MARK = "/*__BUILT_AT__*/null"
THEME_MARK = "/*__THEME__*/"
PID_FILE = ".server.pid"


# --------------------------------------------------------------------- theme
# The title band's four pills are one palette per trip, derived from the single
# number trip.theme_hue. Lightness and chroma are frozen and only the hue
# rotates, because freezing lightness is what freezes the contrast: rotating a
# hue then never requires re-checking that black type stays readable on the pill
# or that the pill still separates from the paper behind it. That second one is
# load-bearing — these pills carry no outline, so their fill is the only thing
# holding them off the canvas.
#
# The offsets were not designed, they were recovered: at hue 334 these four
# resolve to #F3A8E4 / #9CB37A / #C6B4E6 / #CE9E9E, the palette the template
# ships as its default, so the original set is simply this system's hue=334
# instance and nothing changes for a trip that doesn't ask for a theme.
#
# (role, css var, L, C, hue offset)
PILLS = [
    ("name", "--pill-name", 0.822, 0.116, 0),
    ("date", "--pill-date", 0.735, 0.082, 152),
    ("who", "--pill-who", 0.802, 0.072, 327),
    ("pace", "--pill-pace", 0.744, 0.057, 45),
]

# There is no reserved navigation hue any more. NAV_HUE_BLOCK = (198, 258)
# lived here to keep the destination pill from being mistaken for the nav,
# on the stated premise that "the nav is a saturated cyan at C .135". That
# stopped being true when the title band was rebuilt: --pill-nav is #E7E2DB,
# oklch(0.915 0.011 76.6), and --pill-nav-on is #F6F6F6, oklch(0.973 0 90) —
# a warm grey and a neutral grey, chroma .011 and .000. Nothing can be
# mistaken for them on hue.
# Left in place the check refused 60° of the circle, all of it blue, and said
# so in a warning that was simply wrong: theme_hue 200 builds #48D1D8 and was
# told "it will read as the nav's cyan".
PAPER_Y = 0.8780  # relative luminance of --paper #F4F4F0
INK_Y = 0.0048    # relative luminance of --ink   #0E0E0E
MIN_ON_PAPER = 1.60   # the pill must stay off the canvas; today's worst is 1.65
MIN_ON_INK = 4.50     # black type on the pill; every role clears this by far


def _oklch_to_srgb(L: float, C: float, H: float) -> tuple[float, float, float]:
    """OKLCH -> linear sRGB. May land outside [0,1]; callers gamut-map."""
    import math

    h = math.radians(H)
    a, b = C * math.cos(h), C * math.sin(h)
    l_ = (L + 0.3963377774 * a + 0.2158037573 * b) ** 3
    m_ = (L - 0.1055613458 * a - 0.0638541728 * b) ** 3
    s_ = (L - 0.0894841775 * a - 1.2914855480 * b) ** 3
    return (
        +4.0767416621 * l_ - 3.3077115913 * m_ + 0.2309699292 * s_,
        -1.2684380046 * l_ + 2.6097574011 * m_ - 0.3413193965 * s_,
        -0.0041960863 * l_ - 0.7034186147 * m_ + 1.7076147010 * s_,
    )


def _encode(v: float) -> float:
    v = min(1.0, max(0.0, v))
    return 12.92 * v if v <= 0.0031308 else 1.055 * (v ** (1 / 2.4)) - 0.055


def _in_gamut(rgb) -> bool:
    return all(-1e-4 <= v <= 1 + 1e-4 for v in rgb)


def _hex_and_luminance(L: float, C: float, H: float) -> tuple[str, float]:
    """Gamut-map by reducing chroma — the same thing a browser does for oklch(),
    and the reason an unreachable colour comes out duller rather than with its
    lightness disturbed."""
    lo, hi = 0.0, C
    if not _in_gamut(_oklch_to_srgb(L, C, H)):
        for _ in range(24):
            mid = (lo + hi) / 2
            if _in_gamut(_oklch_to_srgb(L, mid, H)):
                lo = mid
            else:
                hi = mid
        C = lo
    srgb = [_encode(v) for v in _oklch_to_srgb(L, C, H)]
    chan = [round(v * 255) for v in srgb]
    # Luminance is measured back from the rounded 8-bit channels, not from the
    # float before them: the hex is what ships, and reading the floats instead
    # lets a colour pass the floor by a hair and then fail it once quantised
    # (measured: 1.59 against a 1.60 floor).
    def _decode(c: float) -> float:
        c /= 255
        return c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4

    y = 0.2126 * _decode(chan[0]) + 0.7152 * _decode(chan[1]) + 0.0722 * _decode(chan[2])
    return "#" + "".join(f"{c:02X}" for c in chan), y


def _contrast(y1: float, y2: float) -> float:
    a, b = y1 + 0.05, y2 + 0.05
    return max(a, b) / min(a, b)


def theme_css(hue) -> tuple[str, list[str]]:
    """Return the CSS declarations for one trip's palette, plus any warnings.

    Lightness is nudged down per role when a hue's contrast against the paper
    falls under the floor. Only a script can do this: CSS has no way to branch on
    a computed contrast ratio, which is the other reason these are resolved here
    instead of being written as oklch() in the template."""
    warn: list[str] = []
    if hue is None:
        return "", warn
    try:
        hue = float(hue) % 360
    except (TypeError, ValueError):
        return "", [f"trip.theme_hue is not a number ({hue!r}); using the default palette"]

    decls = []
    for role, var, L, C, off in PILLS:
        h = (hue + off) % 360
        css_hex, y = _hex_and_luminance(L, C, h)
        # Step lightness down until the pill clears the canvas behind it.
        guard = 0
        while _contrast(y, PAPER_Y) < MIN_ON_PAPER and L > 0.60 and guard < 40:
            L -= 0.005
            guard += 1
            css_hex, y = _hex_and_luminance(L, C, h)
        on_ink = _contrast(y, INK_Y)
        if on_ink < MIN_ON_INK:
            warn.append(f"{role} pill {css_hex} carries black type at only {on_ink:.2f}:1")
        decls.append(f"{var}:{css_hex};")
    return "  " + " ".join(decls), warn


# ------------------------------------------------------------------ markdown

def md_to_html(md: str) -> str:
    """Minimal Markdown → HTML. The guide body is written by the AI in
    route.md and only needs the common subset.

    Deliberately no third-party library: the skill must run in any
    environment that has nothing but python3.
    """
    if not md.strip():
        return ""

    lines = md.replace("\r\n", "\n").split("\n")
    out: list[str] = []
    in_ul = in_ol = False
    in_code = False
    in_table = False
    para: list[str] = []      # accumulates the current paragraph
    quote: list[str] = []     # accumulates the current blockquote

    # Markdown paragraphs are separated by blank lines, not by newlines.
    # Without accumulation, consecutive lines belonging to one paragraph would
    # each become their own <p> and the body would read as fragments.
    def flush_para() -> None:
        nonlocal para
        if para:
            out.append("<p>" + "".join(inline(x) for x in para) + "</p>")
            para = []

    def flush_quote() -> None:
        nonlocal quote
        if quote:
            out.append("<blockquote><p>" + "".join(inline(x) for x in quote) + "</p></blockquote>")
            quote = []

    def close_lists() -> None:
        nonlocal in_ul, in_ol, in_table
        flush_para(); flush_quote()
        if in_ul:
            out.append("</ul>"); in_ul = False
        if in_ol:
            out.append("</ol>"); in_ol = False
        if in_table:
            out.append("</tbody></table></div>"); in_table = False

    def inline(t: str) -> str:
        # Quotes must be escaped too. route.md's body is written by the AI
        # from material found on third-party web pages — i.e. untrusted text
        # fed into an HTML generator. & < > block bare tags, but a string like
        # [x](a"onfocus=…), containing no space or closing paren, can escape
        # out of href's quotes.
        t = (t.replace("&", "&amp;").replace("<", "&lt;")
              .replace(">", "&gt;").replace('"', "&quot;"))
        t = re.sub(r"`([^`]+)`", r"<code>\1</code>", t)
        t = re.sub(r"\*\*([^*]+)\*\*", r"<strong>\1</strong>", t)
        t = re.sub(r"(?<!\*)\*([^*]+)\*(?!\*)", r"<em>\1</em>", t)
        t = re.sub(r"~~([^~]+)~~", r"<del>\1</del>", t)
        t = re.sub(r"\[([^\]]+)\]\(([^)\s]+)\)", link, t)
        return t

    # Protocol allowlist. Anything not on it doesn't become a link, but the
    # text and address are kept verbatim — silently swallowing a source is
    # worse than rendering it as plain text.
    SAFE_URL = re.compile(r"(?:https?://|mailto:|#|\./|\.\./|/)", re.I)

    def link(m: "re.Match[str]") -> str:
        text, url = m.group(1), m.group(2)
        if not SAFE_URL.match(url):
            return f"{text}（{url}）"
        # In-page anchors don't open a new tab — that's a jump within the same
        # guide, not an external link
        if url.startswith("#"):
            return f'<a href="{url}">{text}</a>'
        return f'<a href="{url}" target="_blank" rel="noopener">{text}</a>'

    for raw in lines:
        line = raw.rstrip()

        if line.strip().startswith("```"):
            close_lists()
            out.append("</pre>" if in_code else "<pre>")
            in_code = not in_code
            continue
        if in_code:
            out.append(line.replace("&", "&amp;").replace("<", "&lt;"))
            continue

        if not line.strip():
            close_lists()
            continue

        # Tables
        if line.lstrip().startswith("|") and line.rstrip().endswith("|"):
            cells = [c.strip() for c in line.strip().strip("|").split("|")]
            if all(re.fullmatch(r":?-{2,}:?", c) for c in cells):
                continue  # separator row
            if not in_table:
                close_lists()
                out.append('<div class="table-wrap"><table>')
                in_table = "head"          # a markdown table's first row is always the header
            if in_table == "head":
                # The header must be th: rendered as td, a row like
                # "segment/mode/duration/fare" looks identical to the data
                # rows and the reader has to guess which one is the header
                out.append("<thead><tr>"
                           + "".join(f"<th>{inline(c)}</th>" for c in cells)
                           + "</tr></thead><tbody>")
                in_table = "body"
            else:
                out.append("<tr>" + "".join(f"<td>{inline(c)}</td>" for c in cells) + "</tr>")
            continue
        if in_table:
            out.append("</tbody></table></div>"); in_table = False

        m = re.match(r"^(#{1,4})\s+(.*)$", line)
        if m:
            close_lists()
            # Demote everything one level: the page already has an <h1> (the
            # destination name in the header), so rendering route.md's `#` as
            # h1 would create a second top-level heading in the same document,
            # and screen readers navigating by heading would find two parallel
            # tops. The guide is a block of content within the page, not a
            # separate document, so its headings start at h2.
            lv = min(len(m.group(1)) + 1, 6)
            out.append(f"<h{lv}>{inline(m.group(2))}</h{lv}>")
            continue

        if re.match(r"^\s*[-*+]\s+", line):
            if not in_ul:
                close_lists(); out.append("<ul>"); in_ul = True
            out.append(f"<li>{inline(re.sub(r'^\s*[-*+]\s+', '', line))}</li>")
            continue

        if re.match(r"^\s*\d+[.)]\s+", line):
            if not in_ol:
                close_lists(); out.append("<ol>"); in_ol = True
            out.append(f"<li>{inline(re.sub(r'^\s*\d+[.)]\s+', '', line))}</li>")
            continue

        if re.match(r"^\s*>\s?", line):
            flush_para()
            quote.append(re.sub(r"^\s*>\s?", "", line))
            continue
        flush_quote()

        if re.fullmatch(r"\s*([-*_])\s*(\1\s*){2,}", line):
            close_lists(); out.append("<hr>"); continue

        # Ordinary body text: accumulate into the current paragraph and emit
        # it at the next blank line or block element
        if in_ul or in_ol or in_table:
            close_lists()
        para.append(line)

    if in_code:
        out.append("</pre>")
    close_lists()
    return "\n".join(out)


# ------------------------------------------------------------------ build

def build(trip_dir: Path, standalone: bool = False) -> Path:
    places_path = trip_dir / "places.json"
    if not places_path.exists():
        sys.exit(f"Not found: {places_path}")
    if not TEMPLATE.exists():
        sys.exit(f"Template not found: {TEMPLATE}")

    try:
        data = json.loads(places_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as e:
        sys.exit(f"Failed to parse places.json: {e}")

    route_md = ""
    route_path = trip_dir / "route.md"
    if route_path.exists():
        route_md = route_path.read_text(encoding="utf-8")

    # Rail transit layer. Absent is fine — it's a bonus and must never block
    # producing the page.
    transit = None
    transit_path = trip_dir / "transit.geojson"
    if transit_path.exists():
        try:
            transit = json.loads(transit_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as e:
            print(f"  ⚠ Failed to parse transit.geojson; building without the transit layer: {e}")

    html = TEMPLATE.read_text(encoding="utf-8")

    # The third-party drag library is inlined, not loaded from a CDN: the map
    # has a fallback chain and needs the network anyway, but sorting doesn't —
    # losing drag-sort because unpkg is down would be a self-inflicted failure
    # point.
    vendor = SKILL_ROOT / "assets" / "vendor" / "sortable.min.js"
    sortable = vendor.read_text(encoding="utf-8") if vendor.exists() else ""
    if not sortable:
        print("  ⚠ assets/vendor/sortable.min.js not found; drag sorting disabled (the ↑/↓ buttons still work)")

    for mark in (DATA_MARK, BUILT_MARK):
        if mark not in html:
            sys.exit(f"Template is missing placeholder {mark}")

    # A </script> inside a JSON string would close the tag early; escape it.
    data_js = json.dumps(data, ensure_ascii=False, separators=(",", ":")).replace("</", "<\\/")
    route_js = json.dumps(md_to_html(route_md), ensure_ascii=False).replace("</", "<\\/")
    route_md_js = json.dumps(route_md, ensure_ascii=False).replace("</", "<\\/")
    transit_js = json.dumps(transit, ensure_ascii=False, separators=(",", ":")).replace("</", "<\\/")

    theme, theme_warn = theme_css((data.get("trip") or {}).get("theme_hue"))
    for w in theme_warn:
        print(f"  ⚠ {w}")

    html = html.replace(DATA_MARK, data_js)
    html = html.replace(ROUTE_MARK, route_js)
    html = html.replace(ROUTE_MD_MARK, route_md_js)
    html = html.replace(TRANSIT_MARK, transit_js)
    html = html.replace(SORTABLE_MARK, sortable)
    html = html.replace(THEME_MARK, theme)
    html = html.replace(BUILT_MARK, json.dumps(time.strftime("%Y-%m-%d %H:%M")))
    if standalone:
        html = html.replace("__STANDALONE__", "true")
    else:
        html = html.replace("__STANDALONE__", "false")

    out = trip_dir / ("guide.html" if standalone else "trip.html")
    out.write_text(html, encoding="utf-8")

    n = len(data.get("places") or [])
    chosen = sum(1 for p in data.get("places") or [] if p.get("choice"))
    kind = "guide page (standalone, for sharing)" if standalone else "trip page (three views)"
    print(f"✓ {kind}: {out}")
    print(f"  {n} places, {chosen} with a choice, {out.stat().st_size / 1024:.0f} KB"
          + (", guide body included" if route_md else ", guide body not yet written"))
    if transit:
        print(f"  Transit layer: {len(transit.get('lines', {}).get('features') or [])} lines / "
              f"{len(transit.get('stations', {}).get('features') or [])} stations")
    elif not standalone:
        print("  No transit layer (run enrich.py --transit to generate transit.geojson)")
    return out


# ------------------------------------------------------------------ serve

SERVER_SRC = r'''
import json, os, subprocess, sys, threading, time
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

ROOT = Path(sys.argv[2]).resolve()
BUILD_PY = sys.argv[3]
TARGET = ROOT / "places.json"
LOCK = threading.Lock()
_timer = None


def rebuild():
    """Rebuild trip.html after writing places.json back.

    Without the rebuild the page falls out of step with the data: the
    trip.html on disk still shows the previous build, so double-clicking it —
    or sharing that html with a travel companion — shows the choices and
    schedule from *before* the save, with nothing to indicate it's stale.

    A failed rebuild must not fail the save: places.json is already on disk,
    and that's the truth.
    """
    try:
        r = subprocess.run([sys.executable, BUILD_PY, str(ROOT)],
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                           timeout=120)
        return r.returncode == 0
    except Exception:
        return False


def rebuild_soon(delay=12.0):
    """Auto-save fires every few seconds; rebuilding a 360KB page each time
    is unnecessary.

    trip.html only serves "double-click to open / share with others", where a
    dozen extra seconds change nothing; places.json is the copy the AI reads,
    and that one is written immediately every time.
    """
    global _timer
    if _timer is not None:
        _timer.cancel()
    _timer = threading.Timer(delay, rebuild)
    _timer.daemon = True
    _timer.start()


def merge(incoming):
    """The page sends back only choice / choice_reason / itinerary; for
    everything else the disk wins.

    Wholesale replacement won't do: the page's in-memory DATA is a snapshot
    from *build time*. If the AI runs enrich.py to fill in coordinates or
    images while the page is open, one save would wipe them — and neither side
    would notice. This behavior was confirmed by testing, which is why the
    page sends a patch rather than the full document.
    """
    base = json.loads(TARGET.read_text(encoding="utf-8"))
    if not isinstance(base, dict) or not isinstance(base.get("places"), list):
        raise ValueError("places.json on disk is malformed; refusing to patch it")

    ch = {c[0]: c for c in incoming.get("choices") or []
          if isinstance(c, list) and c and isinstance(c[0], str)}
    for p in base["places"]:
        c = ch.get(p.get("id"))
        if c is None:
            continue             # a place the AI just added that the page doesn't know about — leave it alone
        p["choice"] = c[1] if len(c) > 1 else None
        p["choice_reason"] = (c[2] if len(c) > 2 else "") or ""

    # Stubs the user added via map search (origin=user). The page sends the
    # full set on every save, and "skip if the id already exists on disk"
    # keeps it idempotent — the AI-completed version lives on disk and must
    # not be overwritten by the page's older, uncompleted stub. Fields go
    # through an allowlist: the patch comes from a browser and must not be
    # able to inject arbitrary keys into the dataset.
    stub_fields = {"id", "name", "name_local", "area", "coord",
                   "origin", "choice", "sources"}
    have = {p.get("id") for p in base["places"]}
    for a in incoming.get("added_places") or []:
        if not (isinstance(a, dict) and isinstance(a.get("id"), str) and a["id"]):
            continue
        if a["id"] in have:
            continue
        stub = {k: v for k, v in a.items() if k in stub_fields}
        stub["origin"] = "user"
        base["places"].append(stub)
        have.add(stub["id"])

    if "itinerary" in incoming:
        # The schedule may still reference places the AI has since deleted,
        # and writing those back would make the validator report P0.
        # alive is computed after the stubs are appended — a just-added point
        # must be allowed to appear in the schedule.
        alive = {p.get("id") for p in base["places"]}
        days = []
        for d in incoming.get("itinerary") or []:
            if not isinstance(d, dict):
                continue
            d = dict(d)
            d["places"] = [e for e in (d.get("places") or [])
                           if isinstance(e, dict) and e.get("id") in alive]
            days.append(d)
        base["itinerary"] = days
    return base


def write_atomic(text):
    """Write a temp file, then rename.

    Auto-save widens the "interrupted mid-write" exposure window by orders of
    magnitude, and a plain write_text would leave half a JSON file — at which
    point places.json is neither readable nor backed up.
    On Windows, antivirus scanning briefly locks files, hence the retries.
    """
    # places.json is checked into git. json.dumps ends without a newline, so
    # every rating made in the page produced a "\ No newline at end of file"
    # diff on a file whose content was otherwise unchanged.
    if not text.endswith("\n"):
        text += "\n"
    tmp = TARGET.with_name(TARGET.name + ".tmp")
    err = None
    for _ in range(4):
        try:
            tmp.write_text(text, encoding="utf-8")
            os.replace(tmp, TARGET)
            return
        except OSError as e:
            err = e
            time.sleep(0.15)
    try:
        tmp.unlink()
    except OSError:
        pass
    raise err


class H(SimpleHTTPRequestHandler):
    """Static file server plus one /__save__ write-back endpoint.

    Why the endpoint is needed: in most embedded browsers the File System
    Access API is "function present, write refused" (createWritable throws
    NotAllowedError), and the clipboard is often blocked too. POSTing back to
    a local server is the only transport that works reliably everywhere.
    """
    def __init__(self, *a, **k):
        super().__init__(*a, directory=str(ROOT), **k)

    def log_message(self, *a):
        pass

    def do_POST(self):
        path, _, query = self.path.partition("?")
        if path.rstrip("/") != "/__save__":
            self.send_error(404)
            return
        now = "now=1" in query          # manual save: rebuild at once, don't make the user wait 12s
        try:
            n = int(self.headers.get("Content-Length") or 0)
            if n <= 0 or n > 8 * 1024 * 1024:
                raise ValueError("unexpected request body size")
            doc = json.loads(self.rfile.read(n).decode("utf-8"))
            if not isinstance(doc, dict) or not doc.get("patch"):
                raise ValueError("not a valid patch structure")
            # Always writes this one filename under ROOT; arbitrary paths
            # from the page are never accepted
            with LOCK:
                out = merge(doc)
                write_atomic(json.dumps(out, ensure_ascii=False, indent=2))
            rebuilt = rebuild() if now else (rebuild_soon() or False)
            n_choice = sum(1 for p in out["places"] if p.get("choice"))
            body = json.dumps({"ok": True, "path": str(TARGET), "chosen": n_choice,
                               "rebuilt": bool(rebuilt)}, ensure_ascii=False).encode()
            self.send_response(200)
        except Exception as e:
            body = json.dumps({"ok": False, "error": str(e)}, ensure_ascii=False).encode()
            self.send_response(400)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

# Bind 127.0.0.1 only; never expose the write endpoint to the LAN
ThreadingHTTPServer(("127.0.0.1", int(sys.argv[1])), H).serve_forever()
'''


def _detach() -> dict:
    """Let the server outlive the parent process. start_new_session is
    POSIX-only and silently ignored on Windows (CPython even names the
    parameter unused_start_new_session); creationflags is what actually
    detaches from the console there."""
    if hasattr(os, "setsid"):
        return {"start_new_session": True}
    flags = (getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
             | getattr(subprocess, "DETACHED_PROCESS", 0))
    return {"creationflags": flags} if flags else {}


def serve(trip_dir: Path, page: Path, port: int, open_browser: bool = True) -> None:
    stop(trip_dir, quiet=True)
    proc = subprocess.Popen(
        [sys.executable, "-c", SERVER_SRC, str(port), str(trip_dir),
         str(Path(__file__).resolve())],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, **_detach())
    (trip_dir / PID_FILE).write_text(f"{proc.pid} {port}")
    time.sleep(0.8)
    if proc.poll() is not None:
        sys.exit(f"Server failed to start (port {port} may be in use); pick another with --port")

    url = f"http://localhost:{port}/{page.name}"
    print(f"✓ Local server running: {url}")
    # Print the current interpreter rather than a hardcoded python3 — on
    # Windows the python.org installer doesn't install python3.exe, and the
    # system's alias of that name opens the Microsoft Store.
    print(f"  Stop it: {Path(sys.executable).name} {Path(__file__).name} {trip_dir} --stop")
    print("  Page edits auto-save back to places.json (this server merges, writes, and rebuilds)")
    print("  (http also keeps the official OSM raster basemap compliant; the vector basemap works under file:// too)")
    # --no-open exists for callers that will show the page themselves — an
    # AI opening the URL in an embedded preview pane shouldn't also pop the
    # system browser, or the user gets the same page twice.
    if open_browser:
        try:
            webbrowser.open(url)
        except Exception:  # noqa: BLE001
            pass


def stop(trip_dir: Path, quiet: bool = False) -> None:
    f = trip_dir / PID_FILE
    if not f.exists():
        if not quiet:
            print("No server running")
        return
    try:
        pid, port = f.read_text().split()
        # os.killpg / os.getpgid simply don't exist on Windows. Calling them
        # directly raised an AttributeError that wasn't in the except list →
        # stack trace, while finally deleted the pid file anyway: the server
        # kept running, its record was gone, and it could never be stopped
        # again. serve() calls this function at startup, so a leftover pid
        # file would even crash starting up.
        if hasattr(os, "killpg"):
            os.killpg(os.getpgid(int(pid)), signal.SIGTERM)   # the whole process group
        else:
            os.kill(int(pid), signal.SIGTERM)                 # Windows: only the process itself
        if not quiet:
            print(f"✓ Stopped the server on port {port}")
    except (OSError, ValueError):
        if not quiet:
            print("Server is no longer running")
    finally:
        f.unlink(missing_ok=True)


# ------------------------------------------------------------------ cli

def main() -> int:
    ap = argparse.ArgumentParser(description="Build the trip page")
    ap.add_argument("trip_dir")
    ap.add_argument("--serve", action="store_true", help="start a background local server and open the browser")
    ap.add_argument("--no-open", action="store_true", help="with --serve: don't launch the system browser (caller opens the URL itself, e.g. in an embedded preview pane)")
    ap.add_argument("--stop", action="store_true", help="stop this directory's background server")
    ap.add_argument("--port", type=int, default=8787)
    ap.add_argument("--standalone", action="store_true", help="output only the standalone guide.html")
    args = ap.parse_args()

    trip_dir = Path(args.trip_dir).resolve()
    if not trip_dir.is_dir():
        sys.exit(f"Directory does not exist: {trip_dir}")

    if args.stop:
        stop(trip_dir)
        return 0

    page = build(trip_dir, standalone=args.standalone)
    if args.serve:
        serve(trip_dir, page, args.port, open_browser=not args.no_open)
    else:
        print(f"  Open directly: open {page}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
