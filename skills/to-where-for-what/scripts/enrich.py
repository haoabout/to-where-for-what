#!/usr/bin/env python3
"""Fill in coordinates and images for places.json.

Usage:
    python3 enrich.py <places.json> --coords          # fill coordinates (Nominatim)
    python3 enrich.py <places.json> --images          # image candidate pipeline → image-audit.json
    python3 enrich.py <places.json> --images --recheck    # re-collect even for places with live images
    python3 enrich.py <places.json> --apply-image-review <images-patch.json>
    python3 enrich.py <places.json> --coords --images
    python3 enrich.py <places.json> --coords --dry-run

Why these two jobs aren't left to the model:
    They're deterministic API calls. Having the model do them only injects
    uncertainty, and they aren't where the tokens go anyway. A wrong
    coordinate is very expensive — swapped lat/lon silently drops a place on
    another hemisphere while the page still looks perfectly fine.

Lessons already encoded here:
    · Nominatim's policy allows at most 1 req/s and requires a User-Agent
      that identifies the application
    · Coordinates must be validated against trip.bbox — the only way to catch
      "found a same-named place in another city"
    · Wikimedia no longer generates thumbnails at arbitrary widths on demand
      (220/320/480/640/800/1024 all return 400; only 960/1280 work). The
      API's iiurlwidth must be used so it returns a width that exists
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import re
import shutil
import sys
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

UA = "to-where-for-what-enrich/1.0 (https://github.com/; trip planning skill)"
NOMINATIM_QPS = 1.1          # policy demands ≤1 req/s; leave a little headroom
COMMONS_API = "https://commons.wikimedia.org/w/api.php"


def get_json(url: str, timeout: int = 25) -> dict:
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.load(r)


# ------------------------------------------------------------------ coordinates

def geocode(query: str, lang: str | None = None) -> dict | None:
    params = {"q": query, "format": "json", "limit": 3, "addressdetails": 1}
    if lang:
        params["accept-language"] = lang
    try:
        res = get_json("https://nominatim.openstreetmap.org/search?" + urllib.parse.urlencode(params))
    except Exception as e:  # noqa: BLE001
        print(f"      lookup failed: {type(e).__name__}", file=sys.stderr)
        return None
    return res or None


def in_bbox(lon: float, lat: float, bbox) -> bool:
    return bool(bbox) and bbox[0] <= lon <= bbox[2] and bbox[1] <= lat <= bbox[3]


# Common generic suffixes. Stripped before comparing, so that e.g.
# 大阪城天守閣 (Osaka Castle Keep) can match 大阪城 (Osaka Castle).
_SUFFIX = (r"(天守閣|展望台|記念館|美術館|博物館|資料館|図書館|会館|神社|大社|"
           r"寺院|寺|城|公園|商店街|市場|渡船場|ビルヂング|ビル|タワー|横丁|"
           r"駅|通|筋|跡|場|館|店)+$")
_PUNCT = r"[\s·・（）()【】\[\]、,，。'\"’”—\-–~〜]"


def name_matches(names: list[str], display_name: str) -> bool:
    """A match if any of the place's name variants lines up with the result.

    bbox only catches "wrong city"; it cannot catch "wrong place in the right
    city" — measured, Nominatim returned the coordinates of the Osaka
    Municipal Museum of Art for 適塾 (Tekijuku), squarely inside the Osaka
    bbox, passing silently and planting the marker in the wrong spot.

    But over-strict validation produces false negatives; three were hit in
    testing:
      · 大阪城天守閣 ← returned 大阪城                    different generic suffix
      · 萩ノ茶屋駅   ← returned 萩ノ茶屋                  same
      · "Dotonbori (Glico Sign)" ← returned 道頓堀グリコサイン   cross-language
    Hence: compare every name variant, accept containment in either
    direction, and strip generic suffixes.
    """
    # The place's main name must be split off at the comma *before* stripping
    # punctuation — the reverse order deletes the commas too, so the whole
    # address is treated as the place name and the two-way containment test
    # collapses entirely.
    head = re.sub(_PUNCT, "", display_name.split(",")[0])
    d = re.sub(_PUNCT, "", display_name)
    dl, headl = d.lower(), head.lower()
    for nm in names:
        if not nm:
            continue
        q = re.sub(_PUNCT, "", nm)
        if not q:
            continue
        if re.search(r"[぀-ヿ一-鿿]", q):
            if q in d:
                return True
            core = re.sub(_SUFFIX, "", q)
            hcore = re.sub(_SUFFIX, "", head)
            # The core word may only be compared against the place's main
            # name, never the full address — an address always contains the
            # district name, so 中之島公園 (Nakanoshima Park) would otherwise
            # match "大阪市立東洋陶磁美術館, 中之島一丁目", a completely
            # unrelated place in the same district.
            if len(core) >= 2 and core in head:
                return True
            if len(hcore) >= 3 and (hcore in q or hcore in core):
                return True
            # Variant-character tolerance: pairs like 靱/靭 and old/new kanji
            # forms are common in Japanese place names. Allowed only at
            # length ≥3 and exactly one differing character, to avoid
            # mismatches.
            if len(q) >= 3 and len(q) == len(head) and sum(a != b for a, b in zip(q, head)) == 1:
                return True
        else:
            ql = q.lower()
            if ql in dl:
                return True
            words = [w for w in re.split(r"[^a-z0-9]+", ql) if len(w) > 3]
            if words and sum(w in dl for w in words) >= max(1, len(words) // 2):
                return True
    return False


def fill_coords(doc: dict, dry: bool) -> int:
    trip = doc.get("trip", {})
    bbox = trip.get("bbox")
    lang = trip.get("local_language")
    todo = [p for p in doc["places"] if not (isinstance(p.get("coord"), dict)
            and isinstance(p["coord"].get("lon"), (int, float)))]
    if not todo:
        print("Coordinates: all present")
        return 0

    print(f"Coordinates: {len(todo)} to fill (Nominatim, {NOMINATIM_QPS}s interval)")
    ok = 0
    for p in todo:
        # The local-language name has the best hit rate, then the English
        # name, and the user-language name last
        names = [n for n in (p.get("name_local"), p.get("name_en"), p.get("name")) if n]
        hit = None
        for nm in names:
            city = trip.get("destination_local") or trip.get("destination_en") or ""
            for q in (f"{nm} {city}".strip(), nm):
                res = geocode(q, lang)
                time.sleep(NOMINATIM_QPS)
                if not res:
                    continue
                for cand in res:
                    lon, lat = float(cand["lon"]), float(cand["lat"])
                    disp = cand.get("display_name", "")
                    if not in_bbox(lon, lat, bbox):
                        continue
                    if not name_matches(names, disp):
                        print(f"      ↷ skipped: searching \"{nm}\" returned \"{disp.split(',')[0]}\" — names don't match")
                        continue
                    hit = (lon, lat, disp[:64], q)
                    break
                if hit:
                    break
            if hit:
                break

        if hit:
            lon, lat, disp, q = hit
            if not dry:
                p["coord"] = {"lon": round(lon, 6), "lat": round(lat, 6)}
            ok += 1
            print(f"  ✓ {p.get('name'):<22} {lon:.5f},{lat:.5f}  ← \"{q}\" {disp}")
        else:
            print(f"  ✗ {p.get('name'):<22} no match inside the bbox; fill in manually")
    return ok


# ------------------------------------------------------------------ images
#
# The image flow is a candidate pipeline, not a first-hit chain: each place
# collects verified, deduplicated candidates across the source families
# below, each graded by identity confidence:
#
#   high   — exact-identity: Wikipedia exact-title/redirect lead image, or a
#            Wikidata P18 whose entity matches both name and bbox
#   medium — Wikipedia search hits, official-site og/meta/body images,
#            Commons category members
#   low    — pure geo hits, Openverse, anything with weak name evidence
#
# What a place gets is decided by the evidence rather than spent evenly. The
# two identity families run first; a place that leaves them holding a live,
# corroborated `high` was *easy to find* and stops right there with that one
# candidate — the five remaining families, which are also the slow ones,
# never run for it. Everything else is *hard to find* and gets the full scan
# up to MAX_CANDIDATES. The audit records which tier a place landed in as
# `review: "glance" | "full"`, and the visual pass spends its eyes
# accordingly (references/image-agent-briefing.md).
#
# The split is measured, not guessed (Osaka, 47 places, cross-tabbed against
# the visual pass's verdicts): `medium` candidates were rejected 79% of the
# time, so hard places must keep every pair of eyes they have. `high`
# candidates were still wrong about 10% of the time — a lead image that shot
# the neighbor, a museum's holdings rather than its building, an interior —
# which is too often to skip review altogether, and rare and coarse enough
# that a contact-sheet glance catches it. Hence glance, never exempt.
#
# Only `high` may be provisionally written to places.json, and only for
# places that had no image at all. Everything else — including every image
# that already sits in places.json ("existing" candidates) — waits for the
# visual review pass (image-agent-briefing.md), whose verdicts come back via
# --apply-image-review. Every candidate and every failure is recorded in
# image-audit.json next to places.json — metadata and URLs — while the bytes
# of the kept candidates land in image-review/ for the review pass to read
# (see _save_candidate_files), and are deleted once its verdicts are merged.

MAX_CANDIDATES = 2
AUDIT_NAME = "image-audit.json"

# The bytes themselves are saved for the review pass, into `image-review/`
# next to places.json. Measured on the Osaka run: the review agent spent 12.3
# of its 31.4 minutes re-downloading, one serial curl at a time, exactly the
# candidates this pipeline had just fetched. Collection GETs them anyway to
# verify them, so a second full GET of only the *kept* ones is the whole cost
# — 155s of checking vs 410s of downloading everything, and only the ~60
# survivors pay it. 2MB is the ceiling per file: a truncated image is worse
# than no image (the agent would judge half a photo), so anything that hits
# the cap is left unsaved and the agent falls back to the URL for that one.
FULL_IMAGE_CAP = 2_097_152
REVIEW_DIR = "image-review"

# --- network layer: one choke point for the whole image pipeline.
# Per-domain throttling replaces the scattered time.sleep(0.35) calls; a
# one-run cache means a URL is fetched once no matter how many source
# families surface it; 429/5xx get 3 retries honoring Retry-After (else
# 1/2/4s). Other HTTP errors return a result instead of raising, so the
# caller can record *why* a candidate failed instead of silently eating it.
#
# Several places are collected at once (see fill_images), so everything here
# runs on multiple threads. Politeness is per host, not global: each host
# gets its own lock, held across its whole request cycle, so two requests to
# commons.wikimedia.org stay strictly serial and DOMAIN_INTERVAL apart while
# a slow official site in another thread costs them nothing. Both the
# throttle timestamp and the breaker counter live behind that lock, which is
# the only mutable state a request touches — no second lock needed, and no
# lock is ever held while waiting for another.
#
# Only the image pipeline goes through here. Nominatim (--coords, get_json)
# and Overpass (--transit) each open their own connections on the main
# thread and keep their own, far stricter pacing; concurrency does not reach
# them.

_HTTP_CACHE: dict[str, dict] = {}
_INFLIGHT: dict[str, threading.Event] = {}
_CACHE_LOCK = threading.Lock()
_DOMAINS: dict[str, dict] = {}
_DOMAINS_LOCK = threading.Lock()
DOMAIN_INTERVAL = 0.35
RETRY_HTTP = {429, 500, 502, 503, 504}

# A dead host is dead for every URL under it, but the per-URL stop-loss can
# only ever learn that one URL at a time. Measured on the Osaka run: an
# official domain that no longer resolves costs 2 network attempts × 12s for
# each of the five candidate URLs the page extractor found on it — the same
# 24 seconds paid five times over for information the first URL already
# gave. Two consecutive network failures therefore condemn the host for the
# rest of the process and later requests to it return without touching the
# wire. Consecutive is the operative word: any answer from the host, a 404
# and a 503 included, clears the streak, so a single flaky moment cannot
# blacklist a live site.
HOST_FAIL_LIMIT = 2


def _domain(url: str) -> dict:
    """This host's lock, throttling timestamp and circuit-breaker state."""
    host = urllib.parse.urlparse(url).netloc
    with _DOMAINS_LOCK:
        st = _DOMAINS.get(host)
        if st is None:
            st = {"lock": threading.Lock(), "last": 0.0,
                  "fails": 0, "first_err": None, "dead": None}
            _DOMAINS[host] = st
        return st


def _claim(url: str, cap: int) -> tuple[dict | None, bool]:
    """(cached result, do I own the fetch). The cache only helps when a URL
    is asked for twice in sequence; with several places in flight the same
    Commons thumbnail is routinely asked for twice at once, so the second
    caller waits on the first's result instead of putting an identical
    request on the wire. A fetch that ends without publishing anything (an
    exception escaping http_get) hands ownership to whoever waits.

    The cache is cap-aware, and has to be: the pipeline now asks for the same
    URL twice on purpose — 64KB to verify it is an image, then in full to save
    it — and a plain URL-keyed cache would hand the second caller the 64KB
    stump. A hit is valid only when the cached body cannot be a truncation
    (it ended before its own cap) or was fetched under a cap at least as
    large as this one. Otherwise it is a miss: the caller refetches and
    _publish overwrites. Errors and non-2xx carry an empty body, so they are
    complete at every cap and stay cached — a dead URL is never re-tried."""
    while True:
        with _CACHE_LOCK:
            hit = _HTTP_CACHE.get(url)
            if hit is not None and (len(hit["body"]) < hit["cap"]
                                    or hit["cap"] >= cap):
                return hit, False
            ev = _INFLIGHT.get(url)
            if ev is None:
                _INFLIGHT[url] = threading.Event()
                return None, True
        ev.wait()


def _publish(url: str, res: dict | None, cap: int) -> None:
    with _CACHE_LOCK:
        if res is not None:
            res["cap"] = cap
            _HTTP_CACHE[url] = res
        ev = _INFLIGHT.pop(url, None)
    if ev is not None:
        ev.set()


def _ascii_url(url: str) -> str:
    """urllib refuses to send a URL whose path holds raw non-ASCII: Request
    dies with UnicodeEncodeError before a single packet leaves. Measured on
    the Osaka run, 5 of 9 failing candidates were exactly this — official-site
    photos with Japanese filenames (glico.com's og:image among them) that
    would otherwise have been usable. Percent-encode the path and query,
    keeping '%' in the safe set so already-encoded %XX sequences pass through
    untouched instead of being double-encoded. A non-ASCII hostname still
    fails as before; none has been seen in the wild here."""
    try:
        url.encode("ascii")
        return url
    except UnicodeEncodeError:
        p = urllib.parse.urlsplit(url)
        safe = "/%:@&=+$,~"
        return urllib.parse.urlunsplit(
            (p.scheme, p.netloc,
             urllib.parse.quote(p.path, safe=safe),
             urllib.parse.quote(p.query, safe=safe),
             urllib.parse.quote(p.fragment, safe=safe)))


def http_get(url: str, accept: str = "*/*", cap: int = 800_000,
             timeout: int = 12) -> dict:
    """Streaming GET, first `cap` bytes only. Never HEAD — several official
    sites (measured) 404 on HEAD while the GET serves the image fine.
    Returns {"status", "body", "ctype", "error", "cap"}; "error" is set on
    network failure after retries, "status" on any HTTP response including
    4xx, and "cap" records what the body was read under (see _claim). A
    request to a host the breaker has condemned comes back immediately as
    error "host-dead:<the error that first broke it>"."""
    # Encoding happens before _claim so the cache / in-flight key is the
    # same string that goes on the wire.
    url = _ascii_url(url)
    cached, mine = _claim(url, cap)
    if not mine:
        return cached
    res = None
    try:
        res = _fetch(url, accept, cap, timeout)
        return res
    finally:
        _publish(url, res, cap)


def _fetch(url: str, accept: str, cap: int, timeout: int) -> dict:
    """The request itself, once per URL per run.

    Retry policy is asymmetric on purpose: 429/5xx are cheap, fast responses
    worth 3 retries (honoring Retry-After, else 1/2/4s) — but a connection
    timeout already cost `timeout` seconds, so network errors get exactly
    one retry. Measured on the Bangkok run: 3 retries × 20s timeouts on a
    handful of dead official domains stretched one --images pass past 20
    minutes. The backoff sleeps outside the host lock; only the request
    itself holds it."""
    st = _domain(url)
    last_err = None
    net_fails = 0
    for attempt in range(4):                     # 1 try + up to 3 retries
        retry_after = None
        with st["lock"]:
            if st["dead"]:
                return {"status": None, "body": b"", "ctype": "",
                        "error": f"host-dead:{st['dead']}"}
            dt = time.monotonic() - st["last"]
            if dt < DOMAIN_INTERVAL:
                time.sleep(DOMAIN_INTERVAL - dt)
            req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": accept})
            try:
                with urllib.request.urlopen(req, timeout=timeout) as r:
                    st["fails"], st["first_err"] = 0, None
                    return {"status": r.status, "body": r.read(cap),
                            "ctype": (r.headers.get("Content-Type") or "").lower(),
                            "error": None}
            except urllib.error.HTTPError as e:
                # Any status at all means the host answered, so it counts as
                # proof of life even when the retry loop keeps going.
                st["fails"], st["first_err"] = 0, None
                if e.code not in RETRY_HTTP:
                    return {"status": e.code, "body": b"", "ctype": "", "error": None}
                last_err = f"http:{e.code}"
                retry_after = (e.headers or {}).get("Retry-After")
            except Exception as e:  # noqa: BLE001  timeouts, DNS, resets
                last_err = type(e).__name__
                net_fails += 1
                # Only true transport failures may feed the breaker. This
                # branch also catches client-side errors that say nothing
                # about the host — measured on the Osaka run, glico.com
                # serves image URLs with Japanese filenames that raise
                # UnicodeEncodeError before a single packet leaves, and
                # counting those condemned a perfectly healthy domain.
                # Everything at the socket layer, timeouts and resets
                # included, is an OSError; those are the real evidence.
                if isinstance(e, OSError):
                    st["fails"] += 1
                    if st["first_err"] is None:
                        st["first_err"] = last_err
                    if st["fails"] >= HOST_FAIL_LIMIT:
                        st["dead"] = st["first_err"]
            finally:
                st["last"] = time.monotonic()
        if st["dead"] or net_fails >= 2:
            break
        if attempt < 3:
            try:
                wait = max(0.0, float(retry_after))
            except (TypeError, ValueError):
                wait = float(2 ** attempt)       # 1s, 2s, 4s
            time.sleep(wait)
    return {"status": None, "body": b"", "ctype": "", "error": last_err}


def _json(url: str) -> dict | None:
    r = http_get(url, accept="application/json")
    if r["error"] or not r["status"] or not 200 <= r["status"] < 300:
        return None
    try:
        return json.loads(r["body"].decode("utf-8", "replace"))
    except ValueError:
        return None


def sniff_image(head: bytes) -> str | None:
    if head.startswith(b"\xff\xd8\xff"):
        return "jpeg"
    if head.startswith(b"\x89PNG\r\n\x1a\n"):
        return "png"
    if head.startswith((b"GIF87a", b"GIF89a")):
        return "gif"
    if head[:4] == b"RIFF" and head[8:12] == b"WEBP":
        return "webp"
    # ISO-BMFF (ftyp box): AVIF/HEIC. Measured on the Bangkok run — a
    # WordPress site served its hero photos as image/avif and the checker
    # rejected all four as "not-image", a pure false negative.
    if head[4:8] == b"ftyp" and head[8:12] in (b"avif", b"avis", b"heic",
                                               b"heix", b"mif1"):
        return "avif"
    return None


def check_image_url(url: str) -> dict:
    """Verify a candidate actually is a live image: real GET (first 64KB),
    2xx, an image MIME, and JPEG/PNG/WebP/GIF magic bytes. og:image URLs
    routinely 404 (theCOMMONS served a dead share.webp) and some CDNs return
    an HTML error page with 200 — the magic-byte check catches both."""
    r = http_get(url, accept="image/*", cap=65_536)
    if r["error"]:
        return {"ok": False, "reason": f"fetch-failed:{r['error']}"}
    if not 200 <= (r["status"] or 0) < 300:
        return {"ok": False, "reason": f"http:{r['status']}"}
    fmt = sniff_image(r["body"])
    if not fmt:
        kind = "html" if r["body"].lstrip()[:1] in (b"<",) else "not-image"
        return {"ok": False, "reason": f"{kind}:{r['ctype'][:40]}"}
    if r["ctype"] and not (r["ctype"].startswith("image/")
                           or "octet-stream" in r["ctype"]):
        return {"ok": False, "reason": f"mime:{r['ctype'][:40]}"}
    return {"ok": True, "reason": "", "format": fmt}


# Filename features that mark a URL as site furniture rather than a photo of
# the place. Checked on the URL path only — never a reason to stop scanning a
# page, just to skip that one URL.
#
# The second row was added from measurement, not imagination: cross-tabbing
# the Osaka run's 90 candidates against their last path segment, the original
# row caught nothing at all while 13 URLs were plainly furniture —
# btn_nav_{ec,menu,shop}.svg and btn_access.png (551horai), header_facebook /
# header_instagram.svg (sumiyoshitaisha), clearspacer.gif (city.osaka.lg.jp),
# ico-{minus,plus,search}.svg and ico_{rbi,red,spe}.svg. Short tokens are
# anchored to the start of the segment and must be followed by a separator,
# because unanchored `ico` would eat any photo of a place whose name contains
# it; `spacer` is distinctive enough to stand on its own (the measured
# instance is *clear*spacer.gif).
NEG_IMG_RE = re.compile(
    r"(logo|icon|share|ogp|sprite|avatar|favicon|placeholder"
    r"|spacer|^btn[-_]|^ico[-_]|^header_(facebook|instagram))", re.I)


def looks_negative(url: str) -> bool:
    return bool(NEG_IMG_RE.search(urllib.parse.urlparse(url).path.rsplit("/", 1)[-1]))


def commons_thumb(title: str, width: int = 960) -> dict | None:
    """Fetch a thumbnail by File: title. Uses the API's iiurlwidth, which
    snaps to a width that actually exists."""
    q = {"action": "query", "titles": f"File:{title}", "prop": "imageinfo",
         "iiprop": "url|extmetadata", "iiurlwidth": str(width),
         "format": "json", "formatversion": "2"}
    d = _json(COMMONS_API + "?" + urllib.parse.urlencode(q))
    try:
        ii = (d["query"]["pages"][0].get("imageinfo") or [{}])[0]
    except (TypeError, KeyError, IndexError):
        return None
    if not ii.get("thumburl"):
        return None
    em = ii.get("extmetadata", {})
    artist = re.sub(r"<[^>]+>", "", (em.get("Artist", {}) or {}).get("value", "")).strip()
    lic = (em.get("LicenseShortName", {}) or {}).get("value", "").strip()
    return {"url": ii["thumburl"],
            "credit": " / ".join(x for x in (artist[:60], "Wikimedia Commons", lic) if x),
            "source_url": ii.get("descriptionurl", "")}


def wiki_lead_image(title: str, lang: str) -> tuple[str, str, tuple | None] | None:
    """Lead-image filename + canonical title + article coordinate (lon, lat)
    for an exact title. The lead image is usually the most representative
    one and rarely mislabeled. redirects=1 matters: 「大邮政大楼」-style
    display names reach their article only via a redirect, which the plain
    query misses. The coordinate rides along because the caller needs it to
    tell a real place article from a generic-noun one (see wikipedia_exact)."""
    q = {"action": "query", "titles": title, "prop": "pageimages|coordinates",
         "piprop": "name", "redirects": "1", "colimit": "1",
         "format": "json", "formatversion": "2"}
    d = _json(f"https://{lang}.wikipedia.org/w/api.php?" + urllib.parse.urlencode(q))
    try:
        pg = d["query"]["pages"][0]
    except (TypeError, KeyError, IndexError):
        return None
    fn = pg.get("pageimage")
    if not fn:
        return None
    coord = None
    co = (pg.get("coordinates") or [{}])[0]
    if isinstance(co.get("lon"), (int, float)) and isinstance(co.get("lat"), (int, float)):
        coord = (co["lon"], co["lat"])
    return fn, pg.get("title") or title, coord


def wiki_search_images(name: str, lang: str, limit: int = 3) -> list[tuple[str, str]]:
    """Full-text search hits and their lead images — (filename, title) pairs.
    A search hit is *not* an exact-identity match (searching a gallery name
    can surface the district's article), so these grade medium, never high."""
    q = {"action": "query", "list": "search", "srsearch": name,
         "srlimit": str(limit), "format": "json", "formatversion": "2"}
    d = _json(f"https://{lang}.wikipedia.org/w/api.php?" + urllib.parse.urlencode(q))
    out = []
    for h in ((d or {}).get("query", {}).get("search") or []):
        title = h.get("title") or ""
        hit = wiki_lead_image(title, lang)
        if hit:
            out.append((hit[0], hit[1]))
    return out


def wikidata_entities(name: str, lang: str, bbox) -> list[dict]:
    """Search Wikidata by name; return entities with their P18/P373 claims,
    label, and whether their P625 coordinate falls inside the trip bbox.
    Same-name entities elsewhere in the world are common, so a candidate
    without P625, or with P625 outside the bbox, is rejected rather than
    trusted — that rule predates this pipeline and stays."""
    api = "https://www.wikidata.org/w/api.php?"
    q = {"action": "wbsearchentities", "search": name, "language": lang,
         "type": "item", "limit": "5", "format": "json"}
    d = _json(api + urllib.parse.urlencode(q))
    ids = [h["id"] for h in ((d or {}).get("search") or [])]
    if not ids:
        return []
    q2 = {"action": "wbgetentities", "ids": "|".join(ids),
          "props": "claims|labels", "format": "json"}
    ents = (_json(api + urllib.parse.urlencode(q2)) or {}).get("entities", {})
    out = []
    for eid in ids:                      # search order = relevance order
        ent = ents.get(eid) or {}
        claims = ent.get("claims", {})
        try:
            pos = claims["P625"][0]["mainsnak"]["datavalue"]["value"]
            if bbox and not in_bbox(pos["longitude"], pos["latitude"], bbox):
                continue
        except (KeyError, IndexError, TypeError):
            continue                     # no coordinate → cannot vouch for identity
        rec = {"id": eid, "label": "", "p18": None, "p373": None}
        labels = ent.get("labels") or {}
        for lg in (lang, "en"):
            if labels.get(lg):
                rec["label"] = labels[lg].get("value", "")
                break
        try:
            rec["p18"] = claims["P18"][0]["mainsnak"]["datavalue"]["value"]
        except (KeyError, IndexError, TypeError):
            pass
        try:
            rec["p373"] = claims["P373"][0]["mainsnak"]["datavalue"]["value"]
        except (KeyError, IndexError, TypeError):
            pass
        if rec["p18"] or rec["p373"]:
            out.append(rec)
    return out


def name_variants(name: str | None) -> list[str]:
    """Query variants for a display name that is often not an article title.
    「梅田蓝天大厦 · 空中庭园展望台」 and 「道顿堀（固力果招牌）」 both have
    perfectly good Wikipedia articles — under 梅田スカイビル and 道頓堀.
    Measured on the Osaka trip, composite names were the single biggest
    class of misses; Bangkok added the 与/&/and family (「大邮政大楼与 TCDC
    曼谷」→ General Post Office). Order: the name itself, parentheticals
    stripped, then each segment of the compound."""
    if not name:
        return []
    out = [name.strip()]
    bare = re.sub(r"[（(][^（）()]*[）)]", "", name).strip(" ·・-—")
    if bare:
        out.append(bare)
    # Compound connectors: ·・/& always split; and/และ/与/和 only as spaced
    # words or between CJK runs — 和 is too common inside proper names
    # (昭和, 平和) to split on unconditionally, and the length-≥2 filter
    # below drops the fragments such a split would produce.
    parts = re.split(r"\s*[·・/&]\s*|\s+(?:and|และ)\s+|\s*[与和]\s+|\s+[与和]\s*", bare or name)
    for seg in parts:
        seg = seg.strip()
        if seg:
            out.append(seg)
    seen: set[str] = set()
    res = []
    for n in out:
        if len(n) >= 2 and n not in seen:
            seen.add(n)
            res.append(n)
    return res[:4]


def wiki_geo_hits(lat: float, lon: float, lang: str, radius: int = 150,
                  limit: int = 5) -> list[dict]:
    """Wikipedia articles near the coordinate — (title, dist) pairs, distance
    sorted. The nearest article can be a neighbor rather than the place
    itself (measured in Bangkok: the Old Customs House won on distance for a
    place 180m off), so distance alone never decides anything — the caller
    grades each hit by whether its title matches the place's names."""
    q = {"action": "query", "list": "geosearch", "gscoord": f"{lat}|{lon}",
         "gsradius": str(radius), "gslimit": str(limit), "format": "json"}
    d = _json(f"https://{lang}.wikipedia.org/w/api.php?" + urllib.parse.urlencode(q))
    return [{"title": h.get("title", ""), "dist": h.get("dist")}
            for h in ((d or {}).get("query", {}).get("geosearch") or [])]


def commons_geo_images(lat: float, lon: float, radius: int = 120,
                       limit: int = 3) -> list[dict]:
    """Geotagged Commons photos taken near the point — the fallback for
    streetscapes (shopping arcades, alleys, slopes, ferry piers) that no
    article covers but plenty of photographers have shot. Keyword-free, so
    the failure mode shifts from "wrong name" to "wrong angle"; every hit is
    a low-confidence candidate for the visual pass, never an auto-write."""
    q = {"action": "query", "generator": "geosearch",
         "ggscoord": f"{lat}|{lon}", "ggsradius": str(radius),
         "ggslimit": "12", "ggsnamespace": "6",
         "prop": "imageinfo", "iiprop": "url|mime|extmetadata",
         "iiurlwidth": "960", "format": "json"}
    d = _json(COMMONS_API + "?" + urllib.parse.urlencode(q))
    pages = (d or {}).get("query", {}).get("pages", {})
    out = []
    for _, pg in sorted(pages.items(), key=lambda kv: kv[1].get("index", 999)):
        ii = (pg.get("imageinfo") or [{}])[0]
        if ii.get("mime") not in ("image/jpeg", "image/png") or not ii.get("thumburl"):
            continue
        em = ii.get("extmetadata", {})
        artist = re.sub(r"<[^>]+>", "", (em.get("Artist", {}) or {}).get("value", "")).strip()
        lic = (em.get("LicenseShortName", {}) or {}).get("value", "").strip()
        out.append({"url": ii["thumburl"],
                    "credit": " / ".join(x for x in (artist[:60], "Wikimedia Commons", lic) if x),
                    "source_url": ii.get("descriptionurl", ""),
                    "title": pg.get("title", "")})
        if len(out) >= limit:
            break
    return out


def get_html(url: str, cap: int = 800_000) -> str | None:
    """Capped at 800KB (was 400KB): body-image extraction needs to see past
    the header scripts that dominate heavy official sites."""
    r = http_get(url, accept="text/html", cap=cap)
    if r["error"] or not r["status"] or not 200 <= r["status"] < 300:
        return None
    return r["body"].decode("utf-8", "replace")


_META_RE = [
    re.compile(r'<meta[^>]+property=["\']og:image(?::secure_url)?["\'][^>]+content=["\']([^"\']+)', re.I),
    re.compile(r'<meta[^>]+content=["\']([^"\']+)["\'][^>]+property=["\']og:image(?::secure_url)?["\']', re.I),
    re.compile(r'<meta[^>]+name=["\']twitter:image(?::src)?["\'][^>]+content=["\']([^"\']+)', re.I),
    re.compile(r'itemprop=["\']image["\'][^>]+(?:content|src)=["\']([^"\']+)', re.I),
]
_JSONLD_RE = re.compile(
    r'<script[^>]+application/ld\+json[^>]*>(.*?)</script>', re.I | re.S)
_IMG_SRC_RE = re.compile(r'<img[^>]+src=["\']([^"\']+)["\']', re.I)
_SRCSET_RE = re.compile(r'<(?:img|source)[^>]+srcset=["\']([^"\']+)["\']', re.I)


def _jsonld_images(html: str) -> list[str]:
    out = []
    for m in _JSONLD_RE.finditer(html):
        try:
            data = json.loads(m.group(1).strip())
        except ValueError:
            continue
        stack = [data]
        while stack:
            node = stack.pop()
            if isinstance(node, dict):
                img = node.get("image")
                if isinstance(img, str):
                    out.append(img)
                elif isinstance(img, dict) and isinstance(img.get("url"), str):
                    out.append(img["url"])
                elif isinstance(img, list):
                    out.extend(x for x in img if isinstance(x, str))
                stack.extend(node.values())
            elif isinstance(node, list):
                stack.extend(node)
    return out


def _srcset_best(srcset: str) -> str | None:
    """Largest URL out of a srcset attribute (by the numeric descriptor)."""
    best, best_w = None, -1.0
    for part in srcset.split(","):
        bits = part.strip().split()
        if not bits:
            continue
        w = 0.0
        if len(bits) > 1:
            m = re.match(r"([\d.]+)", bits[1])
            if m:
                w = float(m.group(1))
        if w > best_w:
            best, best_w = bits[0], w
    return best


def official_page_images(p: dict) -> tuple[list[dict], list[dict]]:
    """Two lists from the place's own official pages (sources[]):
    (meta_images, body_images). Meta = og:image / twitter:image / JSON-LD /
    itemprop; body = <img src> and the largest srcset entry. For pop-up
    events and small shops the official page is routinely the only source
    that shows the right thing — but an og:image can just as well be a logo,
    a campaign banner, or a news photo of an event at the venue (measured:
    Siam Paragon), so nothing from here is exact-identity: it all grades
    medium and waits for the visual pass. Filename furniture (logo/share/…)
    is skipped per URL, never a reason to stop scanning the page."""
    meta, body = [], []
    seen: set[str] = set()

    def add(bucket: list, raw: str, page: str) -> None:
        img = urllib.parse.urljoin(page, raw.strip())
        if not img.startswith("http") or img in seen or looks_negative(img):
            return
        seen.add(img)
        bucket.append({"url": img,
                       "credit": urllib.parse.urlparse(page).netloc,
                       "source_url": page})

    for s in (p.get("sources") or [])[:3]:
        u = (s or {}).get("url") or ""
        if not u.startswith("http"):
            continue
        html = get_html(u)
        if not html:
            continue
        for rx in _META_RE:
            for m in rx.finditer(html):
                add(meta, m.group(1), u)
        for raw in _jsonld_images(html):
            add(meta, raw, u)
        for m in _SRCSET_RE.finditer(html):
            best = _srcset_best(m.group(1))
            if best:
                add(body, best, u)
        for m in _IMG_SRC_RE.finditer(html):
            add(body, m.group(1), u)
    return meta, body


def commons_category_files(cat: str, limit: int = 4, descend: bool = True) -> list[dict]:
    """Image files in a Commons category (from Wikidata P373); when the
    category holds only subcategories, descend exactly one level. The first
    file in a category can be anything (the Category:Osaka Castle lesson),
    so members grade medium at best and face the visual pass."""
    q = {"action": "query", "list": "categorymembers",
         "cmtitle": f"Category:{cat}", "cmtype": "file|subcat",
         "cmlimit": "20", "format": "json", "formatversion": "2"}
    d = _json(COMMONS_API + "?" + urllib.parse.urlencode(q))
    members = ((d or {}).get("query", {}).get("categorymembers") or [])
    files, subcats = [], []
    for m in members:
        title = m.get("title", "")
        if title.startswith("File:"):
            files.append(title[5:])
        elif title.startswith("Category:"):
            subcats.append(title[9:])
    out = []
    for fn in files:
        if not re.search(r"\.(jpe?g|png|webp)$", fn, re.I):
            continue
        thumb = commons_thumb(fn)
        if thumb:
            thumb["title"] = fn
            out.append(thumb)
        if len(out) >= limit:
            return out
    if not out and descend:
        for sub in subcats[:2]:
            out = commons_category_files(sub, limit=limit, descend=False)
            if out:
                break
    return out


def openverse_images(query: str, limit: int = 2) -> list[dict]:
    """Openverse (api.openverse.org) aggregates openly licensed photos from
    Flickr and friends; anonymous access, no key. Last resort in the chain:
    keyword search mislabels far more often than a Wikipedia lead image, so
    everything from here is a low-confidence candidate — it can fill a gap
    for the visual pass but never outranks an official or Wikipedia hit."""
    q = {"q": query, "page_size": "3"}
    d = _json("https://api.openverse.org/v1/images/?" + urllib.parse.urlencode(q))
    out = []
    for r in ((d or {}).get("results") or []):
        # thumbnail is Openverse's own proxy (~600px, stable); the original
        # url can be a 20MB TIFF on someone's homepage
        url = r.get("thumbnail") or r.get("url")
        if not url:
            continue
        credit = " / ".join(x for x in ((r.get("creator") or "")[:60],
                                        r.get("source") or "Openverse",
                                        (r.get("license") or "").upper()) if x)
        out.append({"url": url, "credit": credit,
                    "source_url": r.get("foreign_landing_url", ""),
                    "title": r.get("title", "")})
        if len(out) >= limit:
            break
    return out


def _cand(url: str, source: str, confidence: str, *, credit: str = "",
          source_url: str = "", title: str = "", dist=None) -> dict:
    return {"url": url, "source": source, "confidence": confidence,
            "credit": credit, "source_url": source_url,
            "matched_title": title, "distance_m": dist,
            "check": None, "verdict": None}


def _name_pool(p: dict) -> list[str]:
    return [n for n in (p.get("name"), p.get("name_local"), p.get("name_en")) if n]


def _query_names(p: dict, lang: str) -> list[str]:
    """Name variants to query in a given language — every name field
    contributes, deduplicated, local-language-appropriate one first."""
    if lang == "en":
        bases = [p.get("name_en"), p.get("name_local"), p.get("name")]
    else:
        bases = [p.get("name_local"), p.get("name"), p.get("name_en")]
    out, seen = [], set()
    for b in bases:
        for v in name_variants(b):
            if v not in seen:
                seen.add(v)
                out.append(v)
    return out[:6]


def candidate_families(p: dict, trip: dict, bbox, langs: list[str],
                       ambiguous: set) -> tuple[list, list]:
    """Build this place's source families in trust-then-cost order, split
    into the two identity families that always run and the rest that only a
    hard-to-find place pays for. Each entry is a zero-argument generator.

    `ambiguous` is filled in by the Wikidata family: one name resolving to
    several in-bbox entities means the corroboration is not corroboration at
    all — two neighboring temples, a station and the district it is named
    after — so such a place is pushed into the full tier no matter what its
    `high` looks like.

    Events put the official page first: the venue photo every other source
    would find is not the event, and the key visual on the organizer's page
    is — an exhibition must never be represented by the building's facade."""
    names = _name_pool(p)
    coord = p.get("coord") if isinstance(p.get("coord"), dict) else {}
    lat, lon = coord.get("lat"), coord.get("lon")
    has_geo = isinstance(lat, (int, float)) and isinstance(lon, (int, float))
    event = p.get("category") == "event"

    def official():
        meta, body = official_page_images(p)
        for c in meta[:3]:
            yield _cand(c["url"], "official-meta", "medium",
                        credit=c["credit"], source_url=c["source_url"])
        for c in body[:4]:
            yield _cand(c["url"], "official-body", "medium",
                        credit=c["credit"], source_url=c["source_url"])

    def wikipedia_exact():
        # Exact title (following redirects). A hit alone is NOT identity:
        # redirects also suck brand-like names into generic-noun articles —
        # measured in Bangkok, "Speakerbox" (an indie live house) redirected
        # to "Loudspeaker enclosure" and auto-wrote a photo of hi-fi
        # speakers. high therefore needs corroboration: the canonical title
        # matches a name, or the article carries a coordinate inside the
        # trip bbox (real place articles have one; generic nouns don't).
        for lang in langs:
            for nm in _query_names(p, lang):
                hit = wiki_lead_image(nm, lang)
                if hit:
                    fn, title, acoord = hit
                    thumb = commons_thumb(fn)
                    if thumb:
                        ident = (name_matches(names, title)
                                 or (acoord and bbox
                                     and in_bbox(acoord[0], acoord[1], bbox)))
                        yield _cand(thumb["url"], "wikipedia",
                                    "high" if ident else "low",
                                    credit=thumb["credit"],
                                    source_url=thumb["source_url"], title=title)

    def wikidata():
        # P18 with the entity's coordinate inside the bbox; high only when
        # the entity's label also matches a name — coordinate alone can be a
        # neighbor.
        for lang in langs:
            for nm in _query_names(p, lang)[:3]:
                ents = wikidata_entities(nm, lang, bbox)
                # One name, several in-bbox entities that each carry an
                # image: the "corroboration" no longer says *which* of them
                # this place is, so the place loses the cheap tier. Measured
                # on Osaka this fires on 4 of 47, and on exactly the traps it
                # should — 住吉大社 against its station and its three
                # sub-shrines, 藤田美術館 against the sutras it holds, 大阪城
                # against the hall and the park. Filtering these by
                # name_matches was tried and changed none of them: that
                # predicate is deliberately loose (it strips generic
                # suffixes, so 大阪城 → 大阪 matches 大阪商業大学), which
                # makes it useless as a tiebreak between rivals.
                if len({e["id"] for e in ents}) > 1:
                    ambiguous.add(nm)
                for ent in ents:
                    if not ent["p18"]:
                        continue
                    thumb = commons_thumb(ent["p18"])
                    if thumb:
                        conf = "high" if name_matches(names, ent["label"] or nm) else "low"
                        yield _cand(thumb["url"], "wikidata", conf,
                                    credit=thumb["credit"],
                                    source_url=thumb["source_url"],
                                    title=ent["label"])

    def wiki_search():
        for lang in langs:
            for nm in _query_names(p, lang)[:2]:
                for fn, title in wiki_search_images(nm, lang, limit=2):
                    thumb = commons_thumb(fn)
                    if thumb:
                        conf = "medium" if name_matches(names, title) else "low"
                        yield _cand(thumb["url"], "wiki-search", conf,
                                    credit=thumb["credit"],
                                    source_url=thumb["source_url"], title=title)

    def commons_cat():
        for lang in langs:
            for nm in _query_names(p, lang)[:2]:
                for ent in wikidata_entities(nm, lang, bbox):
                    if not ent["p373"]:
                        continue
                    for c in commons_category_files(ent["p373"]):
                        yield _cand(c["url"], "commons-category", "medium",
                                    credit=c["credit"],
                                    source_url=c["source_url"],
                                    title=c.get("title", ""))
                    return

    def geo():
        # Distance never decides identity: a geosearch hit whose title
        # doesn't match the place's names stays low no matter how close.
        if not has_geo:
            return
        for lang in langs:
            for h in wiki_geo_hits(lat, lon, lang):
                hit = wiki_lead_image(h["title"], lang)
                if not hit:
                    continue
                fn, title, _ = hit
                thumb = commons_thumb(fn)
                if thumb:
                    conf = "medium" if name_matches(names, title) else "low"
                    yield _cand(thumb["url"], "wiki-geo", conf,
                                credit=thumb["credit"],
                                source_url=thumb["source_url"],
                                title=title, dist=h.get("dist"))
        for c in commons_geo_images(lat, lon):
            yield _cand(c["url"], "commons-geo", "low", credit=c["credit"],
                        source_url=c["source_url"], title=c.get("title", ""))

    def openverse():
        tries = []
        if p.get("name_local"):
            tries.append(f"{p['name_local']} {trip.get('destination_local') or ''}".strip())
        if p.get("name_en"):
            tries.append(f"{p['name_en']} {trip.get('destination_en') or ''}".strip())
        for q in tries:
            for c in openverse_images(q):
                yield _cand(c["url"], "openverse", "low", credit=c["credit"],
                            source_url=c["source_url"], title=c.get("title", ""))

    # Official pages come before Wikipedia search: search hits are the
    # junkiest medium/low family (measured on theCOMMONS — a logo and a
    # subway platform), and they must not crowd out the venue's own photos.
    if event:
        # No identity stage: an event can never qualify for the cheap tier
        # (its `high` hits are the venue, and collect_candidates caps them at
        # medium anyway), so the whole chain runs in the events order.
        return [], [official, wikipedia_exact, wikidata, wiki_search,
                    commons_cat, geo, openverse]
    return ([wikipedia_exact, wikidata],
            [official, wiki_search, commons_cat, geo, openverse])


def collect_candidates(p: dict, trip: dict, bbox, langs: list[str],
                       existing: list[dict]) -> tuple[list[dict], str]:
    """Assemble verified candidates and report how hard the place was to
    find: returns (candidates, review) where review is "glance" or "full".

    Existing images enter first as `existing` candidates and count toward the
    cap; failed checks are kept in the list (for the audit) but don't count.

    Only high/medium (and live existing) candidates stop the scan early —
    low ones are fillers that must never crowd out a later, more
    trustworthy family (measured on theCOMMONS: three junk wiki-search hits
    filled the cap before the official page, which held the actual photos,
    was ever scanned). Overflow lows are trimmed at the end.

    The glance tier is only granted when the corroborated `high` is the image
    the reader will actually end up seeing. With nothing on the page yet that
    is automatic — the high is adopted below. With an image already there,
    only a high that *is* that image qualifies (the dedup branch catches it,
    which is how a --recheck re-earns the tier for places whose image this
    pipeline wrote in the first place); an existing image no source vouches
    for stays in the full tier, where the visual pass is free to replace it."""
    out: list[dict] = []
    seen: dict[str, dict] = {}
    strong = 0
    for img in existing:
        url = (img or {}).get("url") or ""
        if not url or url in seen:
            continue
        c = _cand(url, "existing", "existing",
                  credit=img.get("credit", ""), source_url=img.get("source_url", ""))
        c["check"] = check_image_url(url)
        out.append(c)
        seen[url] = c
        if c["check"]["ok"]:
            strong += 1

    live_existing = any(c["check"]["ok"] for c in out)
    event = p.get("category") == "event"
    ambiguous: set[str] = set()
    identity, rest = candidate_families(p, trip, bbox, langs, ambiguous)
    high_ev: dict | None = None

    def absorb(c: dict) -> bool:
        """Record one raw candidate; True once the cap is full."""
        nonlocal strong, high_ev
        if event and c["confidence"] == "high":
            # An event's identity is the event, not the venue. An exact
            # Wikipedia/Wikidata hit on a name segment is the building's
            # facade — never a reason to auto-write over the activity's
            # key visual, so events produce no auto-write candidates.
            c["confidence"] = "medium"
        dup = seen.get(c["url"])
        if dup is not None:
            # A `high` that only repeats what is already on the page is still
            # identity evidence: the tiering reads the source, not the record.
            if (c["confidence"] == "high" and high_ev is None
                    and dup["check"]["ok"]):
                high_ev = dup
            return False
        seen[c["url"]] = c
        # Filename furniture is skipped across every family — Commons
        # and Openverse serve *_Logo.svg.png files too, not just
        # official sites.
        if looks_negative(c["url"]):
            c["check"] = {"ok": False, "reason": "filename:negative"}
            out.append(c)
            return False
        c["check"] = check_image_url(c["url"])
        out.append(c)
        if not c["check"]["ok"]:
            return False
        if c["confidence"] == "high" and high_ev is None:
            high_ev = c
        if c["confidence"] != "low":
            strong += 1
            return strong >= MAX_CANDIDATES
        return False

    def scan(families) -> bool:
        """Run families in order; True if the cap filled and we stopped."""
        for fam in families:
            for c in fam():
                if absorb(c):
                    return True
        return False

    review = "full"
    if strong < MAX_CANDIDATES:
        capped = scan(identity)
        if (high_ev is not None and not ambiguous
                and (not live_existing or high_ev["source"] == "existing")):
            review = "glance"
        elif not capped:
            scan(rest)

    if review == "glance":
        # One candidate, and specifically the corroborated one: anything else
        # collected alongside it would only be an unreviewed distraction on
        # the contact sheet.
        keep = {id(high_ev)}
    else:
        # Trim overflow: live candidates never exceed the cap, and lows are
        # the ones trimmed — a strong found by a late family beats an early
        # filler.
        ok_strong = [c for c in out if c["check"]["ok"] and c["confidence"] != "low"]
        ok_low = [c for c in out if c["check"]["ok"] and c["confidence"] == "low"]
        keep = set(map(id, ok_strong[:MAX_CANDIDATES]
                       + ok_low[:max(0, MAX_CANDIDATES - len(ok_strong))]))
    return [c for c in out if not c["check"]["ok"] or id(c) in keep], review


# --------------------------------------------------------------- image audit

def _now_iso() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%S%z")


def _pid(p: dict) -> str:
    """The audit key for a place — id when it has one, else its name."""
    return p.get("id") or p.get("name") or "?"


def load_audit(trip_dir: Path) -> dict:
    path = trip_dir / AUDIT_NAME
    if path.exists():
        try:
            d = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(d, dict) and d.get("schema_version") == 1:
                return d
        except ValueError:
            pass
    return {"schema_version": 1, "generated": "", "places": {}}


def save_audit(trip_dir: Path, audit: dict) -> None:
    audit["generated"] = _now_iso()
    _atomic_write_json(trip_dir / AUDIT_NAME, audit)


def _atomic_write_json(path: Path, doc: dict) -> None:
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(json.dumps(doc, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(path)


# A place's collection is almost entirely time spent waiting on somebody
# else's server, so places are collected several at a time. Five workers,
# not more: the throttle keeps same-host requests serial no matter how many
# threads there are, and since Commons and Wikipedia are on the critical
# path for nearly every place, extra workers would only queue up behind
# those two hosts while making the run look busier than it is.
IMAGE_WORKERS = 5

# Workers print a whole place's block at once. Without this the lines of two
# places that finish together interleave into an unreadable mess.
_PRINT_LOCK = threading.Lock()


def _save_candidate_files(trip_dir: Path, pid: str, cands: list[dict]) -> None:
    """Save the kept candidates' full bytes under `image-review/`, and record
    the path on each candidate as `file` (relative to the trip directory).

    Only candidates that passed the check are fetched again — the 64KB
    verification already told us the rest are not images. The saved bytes are
    the URL's own content, undecoded and unscaled: a Commons thumburl is
    already 960px wide, and the review agent reads these files directly.

    `file` is present exactly when the bytes are on disk. It is absent for a
    failed check, a duplicate, an image at or over FULL_IMAGE_CAP, a second
    GET that failed, and for dry runs — the agent falls back to the URL for
    those. Duplicates are demoted rather than deleted: two families serving
    byte-identical images is one photo, and the audit says which copy won.

    The place's own stale files are removed first, so a --recheck replaces
    them instead of leaving last run's numbering to pile up alongside."""
    safe_pid = re.sub(r"[^A-Za-z0-9_-]", "_", pid or "place")
    out_dir = trip_dir / REVIEW_DIR
    for stale in out_dir.glob(f"{safe_pid}_*"):
        try:
            stale.unlink()
        except OSError:
            pass
    by_digest: dict[str, str] = {}
    n = 0
    for c in cands:
        if not (c.get("check") or {}).get("ok"):
            continue
        n += 1
        r = http_get(c["url"], accept="image/*", cap=FULL_IMAGE_CAP)
        if r.get("error") or not 200 <= (r.get("status") or 0) < 300:
            continue
        body = r.get("body") or b""
        fmt = sniff_image(body)
        # At the cap the body is almost certainly cut short — urllib returned
        # exactly as much as it was allowed to read, not as much as there was.
        if not fmt or len(body) >= FULL_IMAGE_CAP:
            continue
        digest = hashlib.sha256(body).hexdigest()
        twin = by_digest.get(digest)
        if twin is not None:
            c["check"] = {"ok": False, "reason": f"duplicate-bytes:{twin}"}
            continue
        name = f"{safe_pid}_{n}.{'jpg' if fmt == 'jpeg' else fmt}"
        try:
            out_dir.mkdir(parents=True, exist_ok=True)
            (out_dir / name).write_bytes(body)
        except OSError as e:  # noqa: BLE001  a full disk must not kill the run
            with _PRINT_LOCK:
                print(f"      (could not save {name}: {e})",
                      file=sys.stderr, flush=True)
            continue
        by_digest[digest] = c["url"]
        c["file"] = f"{REVIEW_DIR}/{name}"


def _images_for_place(p: dict, trip: dict, bbox, langs: list[str],
                      dry: bool, recheck: bool, trip_dir: Path,
                      pid: str) -> tuple[dict, str | None, bool]:
    """One place's whole image pass, run on a worker thread: verify what's
    on the page, collect if needed, and (when it had nothing) adopt a
    verified `high` candidate. Returns its audit record, the URL written if
    any, and whether the place's `image_gallery` flag changed — the caller
    needs both kinds of change to know places.json is worth rewriting.
    Touches only this place's own dict; the caller does the merging, so the
    audit keeps places.json order however the threads finish."""
    existing = [i for i in (p.get("images") or []) if isinstance(i, dict)]
    # Verify what's already on the page — a dead URL is an audit-worthy
    # failure, not a silent skip.
    existing_checked = []
    broken = False
    for img in existing:
        url = img.get("url") or ""
        c = _cand(url, "existing", "existing",
                  credit=img.get("credit", ""),
                  source_url=img.get("source_url", ""))
        c["check"] = check_image_url(url) if url else {"ok": False, "reason": "empty-url"}
        existing_checked.append(c)
        if not c["check"]["ok"]:
            broken = True

    needs_collect = recheck or not existing or broken
    if not needs_collect:
        # Nothing was re-collected, so there is no fresh evidence to re-tier
        # on. The flag already sitting on the place *is* the last run's
        # evidence, so it is what the record reports.
        return {"name": p.get("name", ""),
                "checked": _now_iso(),
                "review": "glance" if p.get("image_gallery") is True else "full",
                "written": None,
                "candidates": existing_checked}, None, False

    with _PRINT_LOCK:
        print(f"  → {p.get('name')} …", flush=True)
    cands, review = collect_candidates(p, trip, bbox, langs, existing)
    # Before anything reads the candidate list: saving may demote a
    # byte-duplicate to a failed check, and the counts printed below (and the
    # auto-write choice) must see the list as the audit will record it.
    if not dry:
        _save_candidate_files(trip_dir, pid, cands)
    written = None
    if not existing and not dry:
        best = next((c for c in cands
                     if c["confidence"] == "high" and c["check"]["ok"]), None)
        if best:
            p["images"] = [{"url": best["url"], "credit": best["credit"],
                            "source_url": best["source_url"]}]
            written = best["url"]
    # The tier, persisted on the place: the template opens a runtime "more
    # photos" gallery for places whose single image is source-corroborated.
    # Written and *cleared* here, so a --recheck that drops a place out of
    # the tier can never leave a stale flag promising a gallery the evidence
    # no longer supports.
    flagged = False
    if not dry:
        had = p.get("image_gallery")
        if review == "glance":
            p["image_gallery"] = True
        else:
            p.pop("image_gallery", None)
        flagged = p.get("image_gallery") != had

    ok_n = sum(1 for c in cands if (c["check"] or {}).get("ok"))
    bad_n = len(cands) - ok_n
    tag = ("✓ high→written" if written
           else ("existing broken" if broken and existing else "awaiting review"))
    lines = [f"  {p.get('name'):<24} {ok_n} candidate(s), {bad_n} failed  "
             f"[{review}; {tag}]"]
    for c in cands:
        chk = c["check"] or {}
        mark = "·" if chk.get("ok") else "✗"
        lines.append(f"      {mark} [{c['source']}/{c['confidence']}] "
                     f"{c['url'].rsplit('/', 1)[-1][:48]}"
                     f"{'' if chk.get('ok') else '  (' + chk.get('reason', '?') + ')'}")
    with _PRINT_LOCK:
        print("\n".join(lines), flush=True)

    return {"name": p.get("name", ""),
            "checked": _now_iso(),
            "review": review,
            "written": written,
            "candidates": cands}, written, flagged


def fill_images(doc: dict, path: str, dry: bool, recheck: bool = False) -> int:
    """Candidate pipeline. Writes places.json only for places that had no
    image and produced a verified `high` candidate, plus the `image_gallery`
    flag for whichever places earned the glance tier; every place touched
    gets an image-audit.json record for the visual review pass. Incremental by
    default: places whose existing image still verifies are left alone
    (recorded, not re-collected) unless --recheck."""
    trip = doc.get("trip", {})
    bbox = trip.get("bbox")
    langs = [l for l in (trip.get("local_language"), "en") if l]
    trip_dir = Path(path).resolve().parent
    audit = load_audit(trip_dir)

    n_missing = sum(1 for p in doc["places"] if not p.get("images"))
    print(f"Images: candidate pipeline (1/place when the identity families "
          f"vouch for it, else max {MAX_CANDIDATES}; "
          f"{n_missing} place(s) without images"
          f"{', full recheck' if recheck else ''}; {IMAGE_WORKERS} workers)")

    def run(p: dict):
        # One place blowing up must cost that place only. Its previous audit
        # record is left in place rather than overwritten with an empty one —
        # yesterday's candidates are worth more than a blank entry.
        try:
            return _images_for_place(p, trip, bbox, langs, dry, recheck,
                                     trip_dir, _pid(p))
        except Exception as exc:  # noqa: BLE001
            with _PRINT_LOCK:
                print(f"  ✗ {p.get('name')}: {type(exc).__name__}: {exc}"
                      f" — skipped, its audit entry is left as it was",
                      file=sys.stderr, flush=True)
            return None, None, False

    with ThreadPoolExecutor(max_workers=IMAGE_WORKERS,
                            thread_name_prefix="img") as ex:
        results = list(ex.map(run, doc["places"]))

    # Merged in places.json order, after every worker is done: the audit's
    # key order and its one-shot write are what the visual review agent and
    # --apply-image-review read.
    _prev_files = {(pid, c.get("url")): c["file"]
                   for pid, prec in audit.get("places", {}).items()
                   for c in (prec.get("candidates") or [])
                   if isinstance(c, dict) and c.get("file")}
    wrote = 0
    flagged = 0
    glance = 0
    for p, (rec, written, flag_change) in zip(doc["places"], results):
        if rec is None:
            continue
        pid = _pid(p)
        # A record is written whole, which would drop the `file` of a place
        # that was skipped as healthy this run — it never re-collected, so it
        # never re-saved. Carry the previous run's paths over by URL, but only
        # while the bytes are actually still there: a merged review deletes
        # the whole directory, and a path to a file that is gone would send
        # the agent looking for it.
        for c in rec.get("candidates", []):
            if c.get("file"):
                continue
            prev = _prev_files.get((pid, c.get("url")))
            if prev and (trip_dir / prev).exists():
                c["file"] = prev
        audit["places"][pid] = rec
        if rec.get("review") == "glance":
            glance += 1
        if written:
            wrote += 1
        if flag_change:
            flagged += 1

    # The tier split is what the visual pass budgets against, so it is
    # printed rather than left to be counted out of the audit by hand.
    done = sum(1 for rec, _, _ in results if rec is not None)
    print(f"  tiers: {glance} glance / {done - glance} full"
          f"{f'; {flagged} image_gallery flag change(s)' if flagged else ''}")
    if not dry:
        save_audit(trip_dir, audit)
        print(f"  audit → {trip_dir / AUDIT_NAME}")
    # Flag changes count as filled items: they are places.json edits, and the
    # caller only writes the file when something changed.
    return wrote + flagged


# ------------------------------------------------------- apply image review

def apply_image_review(path: str, patch_path: str) -> int:
    """Merge the review agent's images-patch.json (patches + reviews) into
    places.json and write verdicts back to image-audit.json. All-or-nothing:
    any validation error leaves every official file untouched."""
    with open(path, encoding="utf-8") as f:
        doc = json.load(f)
    try:
        with open(patch_path, encoding="utf-8") as f:
            patch = json.load(f)
    except (OSError, ValueError) as e:
        print(f"✗ cannot read patch: {e}", file=sys.stderr)
        return 1

    by_id = {p.get("id"): p for p in doc.get("places", []) if p.get("id")}
    errors: list[str] = []
    patches = patch.get("patches")
    reviews = patch.get("reviews") or []
    if not isinstance(patches, list):
        errors.append('top level must have "patches": [...]')
        patches = []
    if not isinstance(reviews, list):
        errors.append('"reviews" must be a list when present')
        reviews = []

    for i, entry in enumerate(patches):
        where = f"patches[{i}]"
        if not isinstance(entry, dict):
            errors.append(f"{where}: not an object")
            continue
        pid = entry.get("id")
        if pid not in by_id:
            errors.append(f"{where}: unknown place id {pid!r}")
        imgs = entry.get("images")
        if not isinstance(imgs, list):
            errors.append(f"{where}: \"images\" must be a list (empty = stays imageless)")
            continue
        for j, img in enumerate(imgs):
            w = f"{where}.images[{j}]"
            if not isinstance(img, dict):
                errors.append(f"{w}: not an object")
                continue
            url = img.get("url")
            if not (isinstance(url, str) and url.startswith("http")):
                errors.append(f"{w}: url missing or not http(s)")
            if not (isinstance(img.get("credit"), str) and img["credit"].strip()):
                errors.append(f"{w}: credit missing — every image needs an honest credit")
    for i, rv in enumerate(reviews):
        if not isinstance(rv, dict) or rv.get("id") not in by_id:
            errors.append(f"reviews[{i}]: missing or unknown place id")

    if errors:
        print(f"✗ review patch rejected, nothing written ({len(errors)} error(s)):",
              file=sys.stderr)
        for e in errors:
            print(f"    - {e}", file=sys.stderr)
        return 1

    for entry in patches:
        place = by_id[entry["id"]]
        place["images"] = [{"url": img["url"], "credit": img["credit"],
                            "source_url": img.get("source_url", "")}
                           for img in entry["images"]]

    trip_dir = Path(path).resolve().parent
    audit = load_audit(trip_dir)
    for rv in reviews:
        rec = audit["places"].setdefault(
            rv["id"], {"name": by_id[rv["id"]].get("name", ""),
                       "checked": _now_iso(), "review": "full",
                       "written": None, "candidates": []})
        cand_by_url = {c.get("url"): c for c in rec.get("candidates", [])}
        for url in (rv.get("accepted") or []):
            c = cand_by_url.get(url)
            if c:
                c["verdict"] = "accepted"
        for rej in (rv.get("rejected") or []):
            if not isinstance(rej, dict):
                continue
            c = cand_by_url.get(rej.get("url"))
            if c:
                c["verdict"] = "rejected"
                c["verdict_reason"] = rej.get("reason", "")
        # `review` is the tier the collector assigned; the verdicts the visual
        # pass came back with live under their own key so the two can't
        # overwrite each other.
        rec["review_result"] = {"at": _now_iso(),
                                "accepted": rv.get("accepted") or [],
                                "rejected": rv.get("rejected") or [],
                                "note": rv.get("note", ""),
                                "searched": rv.get("searched") or []}

    _atomic_write_json(Path(path), doc)
    save_audit(trip_dir, audit)
    # The verdicts are in; the saved candidate bytes have done their job and
    # would otherwise sit in the trip directory for good. Only on the success
    # path — a rejected patch leaves the material intact so the review agent
    # can be sent back in without a re-collection.
    shutil.rmtree(trip_dir / REVIEW_DIR, ignore_errors=True)
    print(f"✓ applied {len(patches)} patch(es), {len(reviews)} review record(s); "
          f"audit updated → {trip_dir / AUDIT_NAME}")
    return 0


# ------------------------------------------------------------------ rail transit

OVERPASS = "https://overpass-api.de/api/interpreter"

# Urban rail only, no buses. Bus networks are dense enough to smear the whole
# picture, and travelers almost never plan around bus routes.
# monorail / light_rail are included because lines like Osaka's Nankō Port
# Town Line and the Osaka Monorail are indistinguishable from the metro in
# terms of the travel experience.
RAIL_ROUTES = ("subway", "light_rail", "monorail", "tram")

# Simplification tolerance, about 13m. Invisible at city scale, but it cuts
# the point count to a quarter.
RDP_EPS = 0.00012


def _rdp(pts: list[tuple[float, float]], eps: float) -> list[tuple[float, float]]:
    """Douglas-Peucker simplification."""
    if len(pts) < 3:
        return pts

    def dist(p, a, b):
        (x, y), (x1, y1), (x2, y2) = p, a, b
        dx, dy = x2 - x1, y2 - y1
        if dx == 0 and dy == 0:
            return math.hypot(x - x1, y - y1)
        t = max(0.0, min(1.0, ((x - x1) * dx + (y - y1) * dy) / (dx * dx + dy * dy)))
        return math.hypot(x - (x1 + t * dx), y - (y1 + t * dy))

    i = max(range(1, len(pts) - 1), key=lambda k: dist(pts[k], pts[0], pts[-1]))
    if dist(pts[i], pts[0], pts[-1]) > eps:
        return _rdp(pts[:i + 1], eps)[:-1] + _rdp(pts[i:], eps)
    return [pts[0], pts[-1]]


# Overpass is a free public service where throttling and overload are the
# norm, not the exception — measured, running it twice back to back gets a
# 504 on the second call. Back off and retry rather than leaving the user to
# guess whether to run it again.
OVERPASS_MIRRORS = ("https://overpass-api.de/api/interpreter",
                    "https://overpass.kumi.systems/api/interpreter")
RETRY_STATUS = {429, 502, 503, 504}


def overpass(query: str, timeout: int = 180, tries: int = 4) -> dict:
    last = None
    for i in range(tries):
        url = OVERPASS_MIRRORS[i % len(OVERPASS_MIRRORS)]
        req = urllib.request.Request(url, data=query.encode("utf-8"),
                                     headers={"User-Agent": UA})
        try:
            with urllib.request.urlopen(req, timeout=timeout) as r:
                return json.load(r)
        except urllib.error.HTTPError as e:
            last = e
            if e.code not in RETRY_STATUS:
                raise
        except Exception as e:  # noqa: BLE001  timeouts and connection resets are worth retrying
            last = e
        if i < tries - 1:
            wait = 5 * 2 ** i          # 5s, 10s, 20s
            print(f"    ({type(last).__name__}) retrying on another mirror in {wait}s…", file=sys.stderr)
            time.sleep(wait)
    raise last


# Fallback palette for lines whose colour tag is missing in OSM. Deliberately
# high-contrast and chosen not to collide with the marker palette
# (green/amber/gray). When used, the legend says the colors are unofficial.
FALLBACK_COLORS = ["#E5171F", "#0078BE", "#019A66", "#522886", "#EE7B1A",
                   "#E44D93", "#814721", "#00A0DE", "#7A8B1F", "#B02A8F"]


def fetch_transit(doc: dict) -> dict:
    """Fetch rail lines and stations within the destination's bounds and
    produce a GeoJSON document."""
    bbox = doc.get("trip", {}).get("bbox")
    if not bbox or len(bbox) != 4:
        sys.exit("trip.bbox missing or malformed; cannot determine the fetch area")
    s, w, n, e = bbox[1], bbox[0], bbox[3], bbox[2]      # Overpass uses (south,west,north,east)
    area = f"({s},{w},{n},{e})"

    # Lines and stations go in one request. Sending two separate ones gets
    # the second throttled in practice: Overpass allocates execution slots per
    # IP, and back-to-back requests almost always draw a 429/504.
    print(f"→ Overpass query for rail lines and stations {area}")
    q = f'''[out:json][timeout:180];
relation["route"~"^({"|".join(RAIL_ROUTES)})$"]{area};
out geom;
(node["railway"="station"]["station"~"^(subway|light_rail|monorail)$"]{area};
 node["railway"="station"]["subway"="yes"]{area};
 node["railway"="station"]["light_rail"="yes"]{area};
 node["railway"="halt"]["subway"="yes"]{area};);
out tags center;'''
    try:
        data = overpass(q)
    except Exception as exc:  # noqa: BLE001
        print(f"  ✗ query failed: {type(exc).__name__}: {exc}", file=sys.stderr)
        print("    Overpass is a free public service; when throttled, just retry later. "
              "The transit layer is skipped; everything else is unaffected.", file=sys.stderr)
        return {}

    # A line's two directions have near-identical geometry, so merge by
    # ref+colour and keep one copy
    lines: dict[tuple, dict] = {}
    for el in data.get("elements", []):
        if el.get("type") != "relation":      # the same response also carries station nodes
            continue
        tags = el.get("tags", {})
        ref = tags.get("ref") or tags.get("name", "")
        if not ref:
            continue
        colour = (tags.get("colour") or "").strip()
        key = (ref, colour.upper())
        rec = lines.setdefault(key, {
            "ref": ref, "colour": colour,
            "name": (tags.get("name") or "").split(" (")[0],
            "route": tags.get("route"), "segs": [], "seen": set(),
        })
        for m in el.get("members", []):
            g = m.get("geometry")
            if m.get("type") != "way" or not g:
                continue
            pts = [(round(p["lon"], 5), round(p["lat"], 5)) for p in g]
            sig = (pts[0], pts[-1], len(pts))
            if sig in rec["seen"]:
                continue
            rec["seen"].add(sig)
            rec["segs"].append(_rdp(pts, RDP_EPS))

    # Fallback colors must avoid those already taken by official ones, or two
    # lines end up identical. Measured in Osaka: the Hankai Tramway has no
    # colour tag, and the palette's first entry #E5171F collided exactly with
    # the Midōsuji Line's official red — indistinguishable on the map.
    used = {(r["colour"] or "").upper() for r in lines.values() if r["colour"]}
    palette = iter([c for c in FALLBACK_COLORS if c.upper() not in used])

    feats, kept_pts, no_colour = [], 0, 0
    for rec in lines.values():
        if not rec["segs"]:
            continue
        colour = rec["colour"]
        if not colour:
            no_colour += 1
            colour = next(palette, "#888888")
        kept_pts += sum(len(x) for x in rec["segs"])
        feats.append({
            "type": "Feature",
            "properties": {"ref": rec["ref"], "name": rec["name"],
                           "colour": colour, "route": rec["route"],
                           "guessed": not rec["colour"]},
            "geometry": {"type": "MultiLineString", "coordinates": rec["segs"]},
        })

    # Stations come from the node elements in the same response.
    #
    # Do NOT deduplicate by station name. Multiple nodes sharing a name are
    # **not** duplicate entries — they are each line's own platforms, and they
    # really are physically separate: measured, Hommachi has 3 nodes up to
    # 354m apart (the Midōsuji, Chūō and Yotsubashi lines' Hommachi stations
    # were never in the same place), and Tennōji has 2 that are 404m apart.
    # Keeping only the first by name, as an earlier version did, effectively
    # picks one line's platform at random and leaves the other lines without
    # a dot — the user immediately notices "Hommachi serves three lines but
    # only the red one has a marker".
    # 23 of the 152 raw nodes fall into this category, 15% of them.
    stations = []
    for el in data.get("elements", []):
        if el.get("type") != "node":
            continue
        t = el.get("tags", {})
        lon, lat = el.get("lon"), el.get("lat")
        name = t.get("name") or t.get("name:en") or ""
        if lon is None or lat is None or not name:
            continue
        # Omit the key entirely when empty. Written as "", MapLibre's coalesce
        # in the page treats the empty string as a valid value — measured, 120
        # of 129 station names had an empty name:zh, so every station label
        # rendered blank and nothing was visible on the map.
        props = {"name": name}
        for key, tag in (("name_en", "name:en"), ("name_zh", "name:zh")):
            v = (t.get(tag) or "").strip()
            if v:
                props[key] = v
        stations.append({
            "type": "Feature",
            "properties": props,
            "geometry": {"type": "Point", "coordinates": [round(lon, 5), round(lat, 5)]},
        })

    print(f"  {len(feats)} lines, {len(stations)} stations; {kept_pts} points after simplification")
    if no_colour:
        print(f"  ⚠ {no_colour} line(s) have no colour tag in OSM; fallback palette used, "
              f"the legend will say \"unofficial colors\"")
    for f in sorted(feats, key=lambda f: f["properties"]["ref"]):
        p = f["properties"]
        print(f"    {p['ref']:8s} {p['colour']:9s}{'(guessed)' if p['guessed'] else '         '} {p['name'][:32]}")

    return {"lines": {"type": "FeatureCollection", "features": feats},
            "stations": {"type": "FeatureCollection", "features": stations}}


# ------------------------------------------------------------------ cli

def main() -> int:
    ap = argparse.ArgumentParser(description="Fill in coordinates and images for places.json, and fetch rail transit lines")
    ap.add_argument("path")
    ap.add_argument("--coords", action="store_true")
    ap.add_argument("--images", action="store_true")
    ap.add_argument("--transit", action="store_true",
                    help="fetch rail lines and stations into transit.geojson next to the input")
    ap.add_argument("--recheck", action="store_true",
                    help="with --images: re-collect candidates even for places whose images verify")
    ap.add_argument("--apply-image-review", metavar="PATCH",
                    help="merge a reviewed images-patch.json into places.json and the audit")
    ap.add_argument("--dry-run", action="store_true", help="report only, write nothing")
    args = ap.parse_args()

    # Line-buffer stdout even when redirected to a file — an --images run
    # takes minutes, and block buffering makes it look hung until the end.
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(line_buffering=True)

    if args.apply_image_review:
        if args.coords or args.images or args.transit:
            ap.error("--apply-image-review runs alone")
        return apply_image_review(args.path, args.apply_image_review)

    if not (args.coords or args.images or args.transit):
        ap.error("specify at least one of --coords / --images / --transit")

    with open(args.path, encoding="utf-8") as f:
        doc = json.load(f)

    n = 0
    if args.coords:
        n += fill_coords(doc, args.dry_run)
    if args.images:
        n += fill_images(doc, args.path, args.dry_run, args.recheck)

    if args.transit:
        out = Path(args.path).with_name("transit.geojson")
        tr = fetch_transit(doc)
        if tr and not args.dry_run:
            # Overpass throttles the two queries independently. If this run
            # returned lines but no stations while the disk already holds a
            # copy with stations, keep the old one — a partial failure must
            # never degrade existing data. (Hit in practice: after the retries
            # were exhausted, a file with 0 stations was written, wiping the
            # 152 stations painstakingly fetched the time before.)
            if out.exists():
                try:
                    old = json.loads(out.read_text(encoding="utf-8"))
                except Exception:  # noqa: BLE001
                    old = {}
                for key in ("lines", "stations"):
                    new_n = len(tr.get(key, {}).get("features") or [])
                    old_n = len(old.get(key, {}).get("features") or [])
                    if new_n == 0 and old_n > 0:
                        tr[key] = old[key]
                        print(f"  ↷ no {'lines' if key == 'lines' else 'stations'} fetched this run; "
                              f"keeping the existing {old_n}")
            out.write_text(json.dumps(tr, ensure_ascii=False, separators=(",", ":")),
                           encoding="utf-8")
            print(f"✓ Transit written to {out} ({out.stat().st_size / 1024:.0f} KB, "
                  f"{len(tr['lines']['features'])} lines / "
                  f"{len(tr['stations']['features'])} stations)")

    if args.dry_run:
        print(f"\n[dry-run] would have filled {n} item(s); nothing written")
    elif n:
        with open(args.path, "w", encoding="utf-8") as f:
            json.dump(doc, f, ensure_ascii=False, indent=2)
        print(f"\n✓ Filled {n} item(s) and wrote back to {args.path}")
        # Print the current interpreter rather than a hardcoded python3 — on
        # Windows the python.org installer doesn't install python3.exe, and
        # the system's alias of that name opens the Microsoft Store.
        print(f"  Next: {Path(sys.executable).name} validate.py <places.json> --check-links")
    elif not args.transit:
        print("\nNothing to fill")
    return 0


if __name__ == "__main__":
    sys.exit(main())
