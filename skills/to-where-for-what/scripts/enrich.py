#!/usr/bin/env python3
"""Fill in coordinates and images for places.json.

Usage:
    python3 enrich.py <places.json> --coords          # fill coordinates (Nominatim)
    python3 enrich.py <places.json> --images          # fill images (Wikipedia → Wikidata → Openverse)
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
import json
import math
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
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

def commons_thumb(title: str, width: int = 960) -> dict | None:
    """Fetch a thumbnail by File: title. Uses the API's iiurlwidth, which
    snaps to a width that actually exists."""
    q = {"action": "query", "titles": f"File:{title}", "prop": "imageinfo",
         "iiprop": "url|extmetadata", "iiurlwidth": str(width),
         "format": "json", "formatversion": "2"}
    try:
        d = get_json(COMMONS_API + "?" + urllib.parse.urlencode(q))
        ii = (d["query"]["pages"][0].get("imageinfo") or [{}])[0]
    except Exception:  # noqa: BLE001
        return None
    if not ii.get("thumburl"):
        return None
    em = ii.get("extmetadata", {})
    artist = re.sub(r"<[^>]+>", "", (em.get("Artist", {}) or {}).get("value", "")).strip()
    lic = (em.get("LicenseShortName", {}) or {}).get("value", "").strip()
    return {"url": ii["thumburl"],
            "credit": " / ".join(x for x in (artist[:60], "Wikimedia Commons", lic) if x),
            "source_url": ii.get("descriptionurl", "")}


def wiki_lead_image(title: str, lang: str) -> str | None:
    """Get the filename of a Wikipedia article's lead image. The lead image is
    usually the most representative one and rarely mislabeled."""
    q = {"action": "query", "titles": title, "prop": "pageimages",
         "piprop": "name", "format": "json", "formatversion": "2"}
    try:
        d = get_json(f"https://{lang}.wikipedia.org/w/api.php?" + urllib.parse.urlencode(q))
        return d["query"]["pages"][0].get("pageimage")
    except Exception:  # noqa: BLE001
        return None


def wikidata_image(name: str, lang: str, bbox) -> str | None:
    """Search Wikidata by name and return the entity's P18 image filename.
    Catches places notable enough for a Wikidata item but with no Wikipedia
    article in our languages (small galleries, markets, brand flagships).
    Same-name entities elsewhere in the world are common, so a candidate is
    accepted only when its P625 coordinate falls inside the trip bbox — an
    entity without P625 is rejected rather than trusted."""
    api = "https://www.wikidata.org/w/api.php?"
    q = {"action": "wbsearchentities", "search": name, "language": lang,
         "type": "item", "limit": "5", "format": "json"}
    try:
        ids = [h["id"] for h in get_json(api + urllib.parse.urlencode(q)).get("search", [])]
    except Exception:  # noqa: BLE001
        return None
    if not ids:
        return None
    time.sleep(0.35)
    try:
        q2 = {"action": "wbgetentities", "ids": "|".join(ids),
              "props": "claims", "format": "json"}
        ents = get_json(api + urllib.parse.urlencode(q2)).get("entities", {})
    except Exception:  # noqa: BLE001
        return None
    for eid in ids:                      # search order = relevance order
        claims = (ents.get(eid) or {}).get("claims", {})
        try:
            pos = claims["P625"][0]["mainsnak"]["datavalue"]["value"]
            if bbox and not in_bbox(pos["longitude"], pos["latitude"], bbox):
                continue
            return claims["P18"][0]["mainsnak"]["datavalue"]["value"]
        except (KeyError, IndexError, TypeError):
            continue
    return None


def openverse_image(query: str) -> dict | None:
    """Openverse (api.openverse.org) aggregates openly licensed photos from
    Flickr and friends; anonymous access, no key. Last resort in the chain:
    keyword search mislabels far more often than a Wikipedia lead image, so
    anything from here needs the same eyeballing as a category fetch."""
    q = {"q": query, "page_size": "3"}
    try:
        d = get_json("https://api.openverse.org/v1/images/?" + urllib.parse.urlencode(q))
    except Exception:  # noqa: BLE001
        return None
    for r in d.get("results") or []:
        # thumbnail is Openverse's own proxy (~600px, stable); the original
        # url can be a 20MB TIFF on someone's homepage
        url = r.get("thumbnail") or r.get("url")
        if not url:
            continue
        credit = " / ".join(x for x in ((r.get("creator") or "")[:60],
                                        r.get("source") or "Openverse",
                                        (r.get("license") or "").upper()) if x)
        return {"url": url, "credit": credit,
                "source_url": r.get("foreign_landing_url", "")}
    return None


def fill_images(doc: dict, dry: bool) -> int:
    trip = doc.get("trip", {})
    bbox = trip.get("bbox")
    langs = [l for l in (trip.get("local_language"), "en") if l]
    todo = [p for p in doc["places"] if not p.get("images")]
    if not todo:
        print("Images: all present")
        return 0

    print(f"Images: {len(todo)} to fill (Wikipedia lead → Wikidata P18 → Openverse)")
    ok = 0
    for p in todo:
        found, how = None, ""
        # 1) Wikipedia lead image — most representative, rarely mislabeled
        for lang in langs:
            name = p.get("name_local") if lang != "en" else (p.get("name_en") or p.get("name_local"))
            if not name:
                continue
            fn = wiki_lead_image(name, lang)
            time.sleep(0.35)
            if fn:
                found = commons_thumb(fn)
                time.sleep(0.35)
                if found:
                    how = "wikipedia"
                    break
        # 2) Wikidata P18 — items without an article; bbox-checked via P625
        if not found:
            for lang in langs:
                name = p.get("name_local") if lang != "en" else (p.get("name_en") or p.get("name_local"))
                if not name:
                    continue
                fn = wikidata_image(name, lang, bbox)
                time.sleep(0.35)
                if fn:
                    found = commons_thumb(fn)
                    time.sleep(0.35)
                    if found:
                        how = "wikidata"
                        break
        # 3) Openverse keyword search — highest mislabel risk, hence last
        if not found:
            name = p.get("name_en") or p.get("name_local") or p.get("name")
            city = trip.get("destination_en") or trip.get("destination_local") or ""
            if name:
                found = openverse_image(f"{name} {city}".strip())
                time.sleep(0.35)
                if found:
                    how = "openverse"
        if found:
            if not dry:
                p["images"] = [found]
            ok += 1
            print(f"  ✓ {p.get('name'):<22} [{how}] {found['url'].rsplit('/', 1)[-1][:40]}")
        else:
            print(f"  – {p.get('name'):<22} nothing in any source; use a direct image link "
                  f"from an official page, or leave empty (images are optional)")
    return ok


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
    ap.add_argument("--dry-run", action="store_true", help="report only, write nothing")
    args = ap.parse_args()

    if not (args.coords or args.images or args.transit):
        ap.error("specify at least one of --coords / --images / --transit")

    with open(args.path, encoding="utf-8") as f:
        doc = json.load(f)

    n = 0
    if args.coords:
        n += fill_coords(doc, args.dry_run)
    if args.images:
        n += fill_images(doc, args.dry_run)

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
        print("  Next: python3 validate.py <places.json> --check-links")
    elif not args.transit:
        print("\nNothing to fill")
    return 0


if __name__ == "__main__":
    sys.exit(main())
