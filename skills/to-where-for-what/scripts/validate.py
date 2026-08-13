#!/usr/bin/env python3
"""places.json validator — the main gate for anti-hallucination and data integrity.

Usage:
    python3 validate.py <places.json> [--check-links] [--json] [--quiet]

Levels:
    P0  reject  — the data is unusable; exit code 1
    P1  warn    — you can proceed, but something is very likely wrong
    P2  note    — quality suggestions

Contract: references/data-schema.md. Standard library only.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import unicodedata
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime, timedelta

SCHEMA_VERSION = 1

TIERS = {"S", "A", "B", "C"}
SCALES = {"spot", "30min", "1-2h", "2-3h", "half-day", "full-day"}
STATUSES = {"open", "renovating", "seasonal_closed", "permanently_closed"}
BOOKINGS = {"required", "recommended", "none"}
CHOICES = {None, "yes", "maybe", "no"}
VERIFY_STATES = {"verified", "partial", "blocked"}
VERDICTS = {"loved", "ok", "disappointed"}
RETRO_STATES = {"done", "skipped"}

# Every field the contract allows. Extra fields mean the AI invented its own
# schema, and the template won't render them — silent loss is worse than an
# error, hence the notice.
KNOWN_PLACE_FIELDS = {
    "id", "name", "name_local", "name_en", "kind", "category", "tier", "scale",
    "parent_id", "area", "coord", "hours", "last_entry", "closed_days",
    "closed", "ticket", "booking", "booking_url", "status", "status_note",
    "duration_min", "indoor", "night", "pitch", "detail", "photo_index",
    "photo_note", "tags", "images", "sources",
    "verify", "choice", "choice_reason", "origin",
    "verdict", "verdict_note", "prep",
}
KINDS = {"attraction", "lodging"}
ORIGINS = {"user"}

# Lodging uses a reduced required set: it isn't an "attraction" and has no
# notion of tier / tickets / closure days / photo spots, so forcing the
# attraction contract onto it would only coerce fake data.
LODGING_REQUIRED_STR = {"id", "name", "area"}
LODGING_REQUIRED_ANY = {"coord"}

# Stubs the user added via map search (origin=user): name + coordinates + OSM
# source only, with the research fields (hours / tier / category …) left for
# the AI to complete later. Forcing the page to invent that data would only
# produce fake data, hence the minimal required set.
STUB_REQUIRED_STR = {"id", "name"}
STUB_REQUIRED_ANY = {"coord", "sources"}
KNOWN_TRIP_FIELDS = {
    "destination", "destination_local", "destination_en", "country", "bbox",
    "timezone", "output_language", "local_language", "dates", "days", "party",
    "pace", "bases", "generated_at", "verified_at", "note", "retro",
}

# Required, and must not be an empty string
REQUIRED_STR = ["id", "name", "category", "area", "hours", "closed",
                "ticket", "pitch", "detail"]
REQUIRED_ANY = ["tier", "scale", "status", "booking", "coord",
                "duration_min", "photo_index",
                "indoor", "night", "sources"]
# closed_days may be null, meaning "unfindable, or sources contradict".
# Measured: for an old kissaten's Sunday hours, Tabelog said closed while the
# building's official tenant page said open, with no independent site to
# arbitrate. Forcing a value in that situation is far more dangerous than
# leaving it empty — the user would plan around wrong information.
# The cost is that closure-conflict validation becomes impossible, so it's
# downgraded to a P1 asking the user to confirm.

# A browser-shaped UA: measured, Tsūtenkaku's official site refuses tool-shaped
# UAs outright, and using one would misreport plenty of healthy official sites
# as dead links.
UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/140.0 Safari/537.36 to-where-for-what-validate/1.0")
STALE_DAYS = 30
DUPE_METERS = 25
# Within this many days of departure, a scheduled booking-required visit that
# isn't ticked off in the pre-departure checklist becomes a warning.
BOOKING_NUDGE_DAYS = 14

# These status codes mean "the site is alive but refuses automated access",
# which is not a dead link. Measured: Kuromon Market's official site returns
# 403 to every UA (anti-bot) while the page itself is perfectly fine.
BOT_BLOCKED = {401, 403, 405, 429, 503}


class Report:
    def __init__(self) -> None:
        self.items: list[tuple[str, str, str]] = []  # (level, where, message)

    def add(self, level: str, where: str, msg: str) -> None:
        self.items.append((level, where, msg))

    def of(self, level: str) -> list[tuple[str, str, str]]:
        return [i for i in self.items if i[0] == level]

    @property
    def failed(self) -> bool:
        return bool(self.of("P0"))


# ---------------------------------------------------------------- helpers

def _is_url(v) -> bool:
    return isinstance(v, str) and re.match(r"^https?://", v) is not None


def _blank(v) -> bool:
    return v is None or (isinstance(v, str) and not v.strip())


# Character count can't compare a Chinese pitch with an English one: measured on
# the card, ~28 CJK characters fill a line where ~55 Latin ones do. Counting the
# wide ones as two puts both languages on the same ruler — the card's three-line
# clamp lands near 170 units either way.
def _display_width(s: str) -> int:
    return sum(2 if unicodedata.east_asian_width(c) in "WF" else 1 for c in s)


def _haversine_m(a: dict, b: dict) -> float:
    from math import asin, cos, radians, sin, sqrt
    lon1, lat1, lon2, lat2 = map(radians, (a["lon"], a["lat"], b["lon"], b["lat"]))
    h = sin((lat2 - lat1) / 2) ** 2 + cos(lat1) * cos(lat2) * sin((lon2 - lon1) / 2) ** 2
    return 2 * 6371000 * asin(sqrt(h))


def _parse_date(s):
    try:
        return datetime.strptime(s, "%Y-%m-%d").date()
    except (ValueError, TypeError):
        return None


def _trip_weekdays(trip) -> set[int] | None:
    """The set of ISO weekdays the trip covers. Returns None without dates."""
    dates = trip.get("dates") or {}
    start, end = _parse_date(dates.get("start")), _parse_date(dates.get("end"))
    if not start or not end or end < start:
        return None
    days, cur = set(), start
    while cur <= end:
        days.add(cur.isoweekday())
        cur += timedelta(days=1)
    return days


# ---------------------------------------------------------------- checks

def check_top_level(doc, rep: Report) -> None:
    if doc.get("schema_version") != SCHEMA_VERSION:
        rep.add("P0", "root", f"schema_version should be {SCHEMA_VERSION}, got {doc.get('schema_version')!r}")
    for key in ("trip", "categories", "places"):
        if key not in doc:
            rep.add("P0", "root", f"missing top-level field {key}")

    trip = doc.get("trip") or {}
    for f in ("destination", "country", "bbox", "timezone", "output_language",
              "local_language", "days", "party", "pace", "generated_at", "verified_at"):
        if _blank(trip.get(f)):
            rep.add("P0", "trip", f"missing required field {f}")

    bbox = trip.get("bbox")
    if not (isinstance(bbox, list) and len(bbox) == 4 and all(isinstance(x, (int, float)) for x in bbox)):
        rep.add("P0", "trip", "bbox must be four numbers [minLon,minLat,maxLon,maxLat]")
    elif not (bbox[0] < bbox[2] and bbox[1] < bbox[3]):
        rep.add("P0", "trip", f"bbox min/max order is reversed: {bbox}")

    unknown_trip = set(trip) - KNOWN_TRIP_FIELDS
    if unknown_trip:
        rep.add("P2", "trip", f"fields outside the contract: {sorted(unknown_trip)}")

    # UI string override table (optional). The template ships en/zh built in,
    # selected by output_language; for other languages the AI translates the
    # template's I18N.en keys one by one into this object. The template
    # silently ignores unknown keys and falls back to English for missing
    # ones, so only the types are guarded here — a wrong value type would
    # render undefined/[object Object] on the page.
    ui = doc.get("ui")
    if ui is not None:
        if not isinstance(ui, dict):
            rep.add("P0", "ui", "ui must be an object of {key: translated string}")
        else:
            for k, v in ui.items():
                if k == "quick":
                    if not (isinstance(v, list) and all(isinstance(x, str) for x in v)):
                        rep.add("P0", "ui", "ui.quick must be an array of strings")
                elif k == "wmo":
                    if not (isinstance(v, dict) and all(isinstance(x, str) for x in v.values())):
                        rep.add("P0", "ui", "ui.wmo must be an object mapping WMO codes to strings")
                elif not isinstance(v, str):
                    rep.add("P0", "ui", f"ui.{k} must be a string, got {type(v).__name__}")
            lang = str(trip.get("output_language") or "").lower()
            if lang.startswith(("en", "zh")):
                rep.add("P2", "ui",
                        "output_language is en/zh, which the template ships built-in — "
                        "the ui override is unnecessary and will shadow the built-in strings")

    retro = trip.get("retro")
    if retro is not None and retro not in RETRO_STATES:
        rep.add("P0", "trip", f"retro={retro!r} is invalid; must be one of {sorted(RETRO_STATES)}")

    verified = _parse_date(trip.get("verified_at"))
    if verified:
        age = (date.today() - verified).days
        if age > STALE_DAYS:
            rep.add("P1", "trip", f"verified_at is {age} days old; hours/tickets may have changed — re-verify")
    elif trip.get("verified_at"):
        rep.add("P0", "trip", f"verified_at should be YYYY-MM-DD, got {trip.get('verified_at')!r}")


def check_place(p, idx, doc, rep: Report) -> None:
    pid = p.get("id") or f"#{idx}"
    where = f"places[{idx}] {pid}"
    trip = doc.get("trip") or {}

    kind = p.get("kind") or "attraction"
    if kind not in KINDS:
        rep.add("P0", where, f"kind={p.get('kind')!r} is invalid; must be one of {sorted(KINDS)}")
        kind = "attraction"

    origin = p.get("origin")
    if origin is not None and origin not in ORIGINS:
        rep.add("P0", where, f"origin={origin!r} is invalid; must be one of {sorted(ORIGINS)}")
    # A stub is origin=user with no tier yet — once the AI completes it (fills
    # in tier and the rest), it must be validated against the full attraction
    # required set and can no longer hide behind the reduced one.
    is_stub = origin == "user" and p.get("tier") is None

    # When verification is blocked these fields may be empty — that's exactly
    # what "couldn't find out" means. Forcing them to be filled would make the
    # user treat a guess as verified information.
    vstate = (p.get("verify") or {}).get("state")
    excused = {"hours", "ticket", "status", "closed", "last_entry"} if vstate in ("blocked", "partial") else set()

    if kind == "lodging":
        req_str, req_any = LODGING_REQUIRED_STR, LODGING_REQUIRED_ANY
    elif is_stub:
        req_str, req_any = STUB_REQUIRED_STR, STUB_REQUIRED_ANY
        rep.add("P2", where, "user-added stub (origin=user, no tier) — awaiting AI research completion")
    else:
        req_str, req_any = REQUIRED_STR, REQUIRED_ANY

    for f in req_str:
        if f in excused:
            continue
        if _blank(p.get(f)):
            rep.add("P0", where, f"missing required field {f}")
    for f in req_any:
        if f in excused:
            continue
        if p.get(f) is None:
            rep.add("P0", where, f"missing required field {f}")
    if excused:
        got = [f for f in sorted(excused) if not _blank(p.get(f))]
        rep.add("P2", where,
                f"verify.state={vstate} exempts {sorted(excused)} from the required check"
                + (f"; of those, {got} actually have values" if got else "; all are empty"))

    # Enums
    for field, allowed in (("tier", TIERS), ("scale", SCALES),
                           ("status", STATUSES), ("booking", BOOKINGS)):
        v = p.get(field)
        if v is not None and v not in allowed:
            rep.add("P0", where, f"{field}={v!r} is invalid; must be one of {sorted(allowed)}")
    if "choice" in p and p["choice"] not in CHOICES:
        rep.add("P0", where, f"choice={p['choice']!r} is invalid")
    v = p.get("verdict")
    if v is not None and v not in VERDICTS:
        rep.add("P0", where, f"verdict={v!r} is invalid; must be one of {sorted(VERDICTS)}")

    # Pre-departure prep state (page-written; the AI must not pre-fill).
    # Only place-level prep lives here: checked = "the user confirmed the
    # verify.check items themselves". Booking state is per-visit — bookings
    # are date-bound — so it sits on itinerary entries as booked, not here.
    prep = p.get("prep")
    if prep is not None:
        if not isinstance(prep, dict):
            rep.add("P0", where, 'prep must be an object, e.g. {"checked": true}')
        else:
            if "checked" in prep and not isinstance(prep["checked"], bool):
                rep.add("P0", where, f"prep.checked must be a boolean, got {prep['checked']!r}")
            unknown_prep = set(prep) - {"checked"}
            if unknown_prep:
                rep.add("P2", where,
                        f"prep has fields outside the contract: {sorted(unknown_prep)} — "
                        f"the page only reads checked")

    # Lodging belongs to no attraction category and takes part in no quota, so
    # it needn't appear in categories
    cat_ids = {c.get("id") for c in doc.get("categories") or []}
    if kind != "lodging" and p.get("category") and p["category"] not in cat_ids:
        rep.add("P0", where, f"category={p['category']!r} is not defined in categories")

    # Coordinates
    c = p.get("coord")
    if not isinstance(c, dict) or not isinstance(c.get("lon"), (int, float)) \
            or not isinstance(c.get("lat"), (int, float)):
        rep.add("P0", where, 'coord must be {"lon": number, "lat": number} (arrays are forbidden — they invite lon/lat swaps)')
    else:
        lon, lat = c["lon"], c["lat"]
        if not (-180 <= lon <= 180 and -90 <= lat <= 90):
            rep.add("P0", where, f"coordinates out of range: lon={lon} lat={lat}")
        else:
            bbox = trip.get("bbox")
            if isinstance(bbox, list) and len(bbox) == 4:
                if not (bbox[0] <= lon <= bbox[2] and bbox[1] <= lat <= bbox[3]):
                    if origin == "user":
                        # Spontaneous additions often sit just outside the
                        # bbox (adding Nara to an Osaka trip), and their
                        # coordinates come from OSM rather than the AI, so the
                        # prior for a swap or mis-search is far lower
                        rep.add("P1", where,
                                f"user-added point ({lon}, {lat}) is outside the destination bbox; "
                                f"confirm it isn't a same-named place elsewhere")
                    else:
                        rep.add("P0", where,
                                f"coordinates ({lon}, {lat}) fall outside the destination bbox — "
                                f"very likely swapped lon/lat or a same-named place elsewhere")

    # Sources (the main anti-hallucination gate)
    srcs = p.get("sources")
    if not isinstance(srcs, list) or not srcs:
        rep.add("P0", where, "sources is empty — entries not verified online must not enter the dataset")
    else:
        for i, s in enumerate(srcs):
            if not isinstance(s, dict) or not _is_url(s.get("url")):
                rep.add("P0", where, f"sources[{i}] lacks a valid http(s) url")

    # Status
    if p.get("status") and p["status"] != "open" and _blank(p.get("status_note")):
        rep.add("P0", where, f"status={p['status']} but status_note is missing (state the dates)")

    # Verification state. Orthogonal to status: status says whether the venue
    # is open, verify says how far we got confirming it.
    v = p.get("verify")
    if v is not None:
        if not isinstance(v, dict):
            rep.add("P0", where, "verify must be an object {state, note, check}")
        else:
            st = v.get("state")
            if st not in VERIFY_STATES:
                rep.add("P0", where, f"verify.state={st!r} is invalid; must be one of {sorted(VERIFY_STATES)}")
            elif st != "verified":
                if _blank(v.get("note")):
                    rep.add("P0", where,
                            f"verify.state={st} but note is missing — it must say what was tried and why it failed, "
                            f"or the user can't judge whether to check it themselves")
                if not v.get("check"):
                    rep.add("P1", where, f"verify.state={st}: consider listing the items the user should confirm in check")
                rep.add("P1", where,
                        f"verification blocked or incomplete ({st}): {str(v.get('note'))[:60]}…"
                        f" — the page will flag it for the user to confirm")

    # closed_days. Lodging has no notion of a "closure day" and is exempt.
    cd = p.get("closed_days")
    if cd is None:
        if kind != "lodging" and not is_stub:
            rep.add("P1", where,
                    "closed_days is null (unfindable or sources conflict) — closure/trip conflicts can't be validated; "
                    "remind the user in detail to confirm before departure")
    else:
        if not isinstance(cd, list) or any(not isinstance(d, int) or not 1 <= d <= 7 for d in cd):
            rep.add("P0", where, "closed_days must be an array of integers 1–7 (1=Monday); use [] for no closures")
        else:
            trip_days = _trip_weekdays(trip)
            if trip_days and trip_days.issubset(set(cd)):
                names = ", ".join(WEEK_NAMES[d] for d in sorted(trip_days))
                rep.add("P0", where,
                        f"closure days cover the whole trip (trip spans {names}; the place is shut on all of them) — "
                        f"the user should never see it as selectable")

    # Spot parentage. parent_id is optional — in practice some micro-spots
    # (ferry piers, small roadside shrines) have no major place in their area
    # at all, and forcing a parent would fabricate a false hierarchy.
    # A parentless spot renders as its own small card in the list, which is
    # acceptable.
    if p.get("scale") == "spot":
        parent = p.get("parent_id")
        if _blank(parent):
            rep.add("P2", where, 'scale="spot" without parent_id renders as a standalone card. '
                                 'If the area has a major place, attaching it keeps the list compact')
        else:
            all_ids = {q.get("id") for q in doc.get("places") or []}
            if parent not in all_ids:
                rep.add("P0", where, f"parent_id={parent!r} points at a nonexistent place")

    # Numeric fields
    for f in ("duration_min", "photo_index"):
        v = p.get(f)
        if v is not None and not isinstance(v, int):
            rep.add("P0", where, f"{f} must be an integer, got {v!r}")
    if isinstance(p.get("photo_index"), int) and not 1 <= p["photo_index"] <= 5:
        rep.add("P0", where, f"photo_index should be 1–5, got {p['photo_index']}")
    for f in ("indoor", "night"):
        if p.get(f) is not None and not isinstance(p[f], bool):
            rep.add("P0", where, f"{f} must be a boolean, got {p[f]!r}")

    # ---- P1
    # Stubs are exempt: name_local is a research product, and the page can
    # only supply it when OSM's namedetails happens to carry one
    if (not is_stub and trip.get("local_language") and trip.get("output_language")
            and trip["local_language"] != trip["output_language"]
            and _blank(p.get("name_local"))):
        rep.add("P1", where, "local language differs from the output language; name_local should be provided (and be findable on the map)")

    unknown = set(p) - KNOWN_PLACE_FIELDS
    if unknown:
        rep.add("P2", where,
                f"fields outside the contract: {sorted(unknown)} — the template won't render them and the content is silently lost. "
                f"If a new field is truly needed, change data-schema.md and validate.py first")

    # ---- P2
    # Lodging and stubs are exempt from these: photo spots, images and a long
    # write-up are post-research quality requirements. Telling a hotel or a
    # just-pinned stub that it "lacks shooting advice" only creates noise and
    # drowns the notices that matter.
    if kind != "lodging" and not is_stub:
        if _blank(p.get("photo_note")):
            rep.add("P2", where, "missing photo_note (shot description and shooting advice)")
        if not p.get("images"):
            rep.add("P2", where, "no images")
        if isinstance(p.get("detail"), str) and 0 < len(p["detail"].strip()) < 60:
            rep.add("P2", where, f"detail is only {len(p['detail'].strip())} characters — thin")
        # The card clamps the pitch to three lines. Overflow is no longer lost —
        # the dialog carries the full pitch as a lede — but a hook that never
        # fits its own card has stopped being a hook and is drifting into detail.
        if isinstance(p.get("pitch"), str) and _display_width(p["pitch"].strip()) > 180:
            rep.add("P2", where,
                    "pitch overflows the card's three-line clamp — move the background into detail "
                    "and keep the hook to the one judgment that decides want/skip")
    if p.get("booking") in ("required", "recommended") and _blank(p.get("booking_url")):
        rep.add("P2", where, f"booking={p['booking']} but booking_url is missing")


def check_cross(doc, rep: Report) -> None:
    places = doc.get("places") or []

    seen: dict[str, int] = {}
    for i, p in enumerate(places):
        pid = p.get("id")
        if not pid:
            continue
        if pid in seen:
            rep.add("P0", f"places[{i}]", f"id {pid!r} duplicates places[{seen[pid]}]")
        else:
            seen[pid] = i

    # Category quotas
    counts: dict[str, int] = {}
    for p in places:
        counts[p.get("category")] = counts.get(p.get("category"), 0) + 1
    for c in doc.get("categories") or []:
        n = counts.get(c.get("id"), 0)
        lo, hi = c.get("min"), c.get("max")
        label = c.get("label", c.get("id"))
        if isinstance(lo, int) and n < lo:
            rep.add("P1", "categories",
                    f"\"{label}\" has only {n}, below the minimum {lo} — "
                    f"if the destination truly has no more, say so honestly in the text; never pad")
        if isinstance(hi, int) and n > hi:
            rep.add("P1", "categories", f"\"{label}\" has {n}, above the maximum {hi}")

    # Nearly identical coordinates
    pts = [(i, p) for i, p in enumerate(places) if isinstance(p.get("coord"), dict)
           and isinstance(p["coord"].get("lon"), (int, float))
           and isinstance(p["coord"].get("lat"), (int, float))]
    for a in range(len(pts)):
        for b in range(a + 1, len(pts)):
            ia, pa = pts[a]
            ib, pb = pts[b]
            try:
                d = _haversine_m(pa["coord"], pb["coord"])
            except (KeyError, ValueError):
                continue
            if d < DUPE_METERS:
                rep.add("P1", f"places[{ia}] / places[{ib}]",
                        f"{pa.get('name')} and {pb.get('name')} are only {d:.0f} m apart — possible duplicate")

    total = len([p for p in places if (p.get("kind") or "attraction") != "lodging"])
    if total < 15:
        rep.add("P1", "places", f"only {total} places in total — the search may be too thin (target 35–50)")
    elif total > 60:
        rep.add("P1", "places", f"{total} places in total — above the suggested cap; too heavy to filter")


WEEK_NAMES = ["", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]


def check_itinerary(doc, rep: Report) -> None:
    """Validate the scheduling result, itinerary.

    The top-level key is itinerary rather than days to avoid colliding with
    trip.days (an integer count) — the same name at a different level with a
    different type confuses both the JSON author and the code reader.

    No itinerary means the whole section is skipped: scheduling is an optional
    stage and older files must keep working.
    """
    it = doc.get("itinerary")
    if it is None:
        return
    if not isinstance(it, list):
        rep.add("P0", "itinerary", "itinerary must be an array")
        return

    places = doc.get("places") or []
    by_id = {p.get("id"): p for p in places if p.get("id")}

    seen_n: dict[int, int] = {}
    assigned: dict[str, list[int]] = {}      # place id -> which days it appears on

    for di, day in enumerate(it):
        dwhere = f"itinerary[{di}]"
        if not isinstance(day, dict):
            rep.add("P0", dwhere, "each day must be an object")
            continue

        n = day.get("n")
        label = day.get("label") or (f"Day {n}" if isinstance(n, int) else dwhere)
        if not isinstance(n, int):
            rep.add("P0", dwhere, f"n must be an integer (0 = arrival evening), got {n!r}")
        elif n in seen_n:
            rep.add("P0", dwhere, f"n={n} duplicates itinerary[{seen_n[n]}]")
        else:
            seen_n[n] = di

        # The date drives closure-conflict checks; Day 0 may have no date of its own
        d = _parse_date(day.get("date")) if day.get("date") else None
        if day.get("date") and not d:
            rep.add("P0", dwhere, f"date should be YYYY-MM-DD, got {day.get('date')!r}")

        entries = day.get("places")
        if not isinstance(entries, list):
            rep.add("P0", dwhere, "places must be an array (order = visit order)")
            continue
        if not entries:
            rep.add("P1", dwhere, f"{label} has no places at all")

        for ei, ent in enumerate(entries):
            ewhere = f"{dwhere}.places[{ei}]"
            if not isinstance(ent, dict) or not ent.get("id"):
                rep.add("P0", ewhere, 'each entry must be an object of the form {"id": "..."}')
                continue
            pid = ent["id"]
            # booked is written back by the page when the user ticks a visit
            # off in the pre-departure checklist. It lives on the entry, not
            # the place: two scheduled visits are two bookings.
            if "booked" in ent and not isinstance(ent["booked"], bool):
                rep.add("P0", ewhere, f"booked must be a boolean, got {ent['booked']!r}")
            p = by_id.get(pid)
            if p is None:
                rep.add("P0", ewhere, f"id {pid!r} does not exist in places")
                continue

            assigned.setdefault(pid, []).append(n if isinstance(n, int) else di)

            # ---- Closure conflict: not a judgment call; you can't go that day ----
            if d is not None:
                wd = d.isoweekday()
                cds = p.get("closed_days")
                if isinstance(cds, list) and wd in cds:
                    rep.add("P0", ewhere,
                            f"{p.get('name')} is scheduled on {day.get('date')} ({WEEK_NAMES[wd]}), "
                            f"but it's closed that day (closed_days={cds})")
            if p.get("status") == "permanently_closed":
                rep.add("P0", ewhere, f"{p.get('name')} is permanently closed and cannot be scheduled")

    # ---- Cross-day checks ----
    for pid, days_in in assigned.items():
        p = by_id.get(pid) or {}
        # Lodging appearing every day is normal, not a suspicious duplicate —
        # in the test sample the hotel appeared twice a day (leaving in the
        # morning, returning at night), four times over two days, and was
        # falsely flagged as "confirm this isn't a mistake".
        if (p.get("kind") or "attraction") == "lodging":
            continue
        distinct = sorted(set(days_in))
        if len(distinct) > 1:
            # Visiting the same place twice is usually deliberate (daytime and
            # night views, two consecutive Expo days), but it can also be a
            # drag mistake. A note means deliberate.
            has_note = any(
                (ent.get("note") or "").strip()
                for day in it if isinstance(day, dict)
                for ent in (day.get("places") or [])
                if isinstance(ent, dict) and ent.get("id") == pid)
            if not has_note:
                rep.add("P2", f"itinerary/{pid}",
                        f"{p.get('name')} is scheduled on days {distinct} without a note — "
                        f"confirm it's a deliberate repeat visit, not a drag mistake")

    for p in places:
        if (p.get("kind") or "attraction") == "lodging" and p.get("id") not in assigned:
            rep.add("P1", "itinerary",
                    f"lodging \"{p.get('name')}\" appears on no day — "
                    f"put lodging into each day so start and end points are clear")

    # ---- Booking nudge ----
    # Within the departure window, any scheduled visit to a booking-required
    # place that isn't ticked off yet gets one aggregated warning — past that
    # point, "book it later" quietly becomes "arrived without a ticket".
    start = _parse_date(((doc.get("trip") or {}).get("dates") or {}).get("start"))
    if start:
        days_left = (start - date.today()).days
        if 0 <= days_left <= BOOKING_NUDGE_DAYS:
            unbooked = [
                f"{(by_id.get(ent.get('id')) or {}).get('name')} (day {day.get('n')})"
                for day in it if isinstance(day, dict)
                for ent in (day.get("places") or []) if isinstance(ent, dict)
                if (by_id.get(ent.get("id")) or {}).get("booking") == "required"
                and not ent.get("booked")
            ]
            if unbooked:
                rep.add("P1", "itinerary",
                        f"trip starts in {days_left} day(s), and these booking-required visits "
                        f"aren't marked booked in the pre-departure checklist yet: {', '.join(unbooked)}")


# ---------------------------------------------------------------- links

def _fetch(url: str) -> tuple[str, int | str]:
    """HEAD first, falling back to a first-byte GET when refused. Returns the
    status code or the exception name."""
    def _try(method: str) -> int:
        headers = {"User-Agent": UA}
        if method == "GET":
            headers["Range"] = "bytes=0-64"
        req = urllib.request.Request(url, method=method, headers=headers)
        with urllib.request.urlopen(req, timeout=15) as r:
            return r.status

    try:
        return url, _try("HEAD")
    except urllib.error.HTTPError as e:
        if e.code in (403, 405, 501):  # plenty of sites forbid HEAD
            try:
                return url, _try("GET")
            except urllib.error.HTTPError as e2:
                return url, e2.code
            except Exception as e2:  # noqa: BLE001
                return url, type(e2).__name__
        return url, e.code
    except Exception as e:  # noqa: BLE001
        return url, type(e).__name__


def check_links(doc, rep: Report) -> None:
    targets: dict[str, list[str]] = {}
    for i, p in enumerate(doc.get("places") or []):
        where = f"places[{i}] {p.get('id')}"
        for s in p.get("sources") or []:
            if _is_url(s.get("url")):
                targets.setdefault(s["url"], []).append(f"{where} sources")
        for im in p.get("images") or []:
            if _is_url(im.get("url")):
                targets.setdefault(im["url"], []).append(f"{where} images")
        if _is_url(p.get("booking_url")):
            targets.setdefault(p["booking_url"], []).append(f"{where} booking_url")

    if not targets:
        return
    print(f"  checking {len(targets)} links…", file=sys.stderr)
    with ThreadPoolExecutor(max_workers=12) as ex:
        for url, status in ex.map(_fetch, targets):
            if isinstance(status, int) and status < 400:
                continue
            if status in BOT_BLOCKED:
                # The site is alive, just refusing automated access — not a
                # dead link, but worth a manual click to confirm
                for where in targets[url]:
                    rep.add("P2", where, f"can't verify automatically (likely bot-blocked, HTTP {status}); check manually: {url}")
            else:
                for where in targets[url]:
                    rep.add("P1", where, f"link unreachable [{status}] {url}")


# ---------------------------------------------------------------- output

LEVEL_STYLE = {"P0": ("\033[91m", "reject"), "P1": ("\033[93m", "warn"), "P2": ("\033[96m", "note")}


def render(rep: Report, quiet: bool) -> None:
    if not rep.items:
        print("\033[92m✓ Validation passed, no findings\033[0m")
        return
    for level in ("P0", "P1", "P2"):
        items = rep.of(level)
        if not items or (quiet and level == "P2"):
            continue
        color, label = LEVEL_STYLE[level]
        print(f"\n{color}{level} · {label} ({len(items)})\033[0m")
        for _, where, msg in items:
            print(f"  {color}•\033[0m {where}\n      {msg}")
    n0, n1, n2 = len(rep.of("P0")), len(rep.of("P1")), len(rep.of("P2"))
    print(f"\nTotal  P0 {n0} · P1 {n1} · P2 {n2}")
    if n0:
        print("\033[91m→ P0 findings present: the data is unusable; fix and re-validate\033[0m")


def main() -> int:
    ap = argparse.ArgumentParser(description="Validate places.json")
    ap.add_argument("path")
    ap.add_argument("--check-links", action="store_true", help="check all URLs for reachability concurrently (slower)")
    ap.add_argument("--json", action="store_true", help="output results as JSON")
    ap.add_argument("--quiet", action="store_true", help="hide P2 notes")
    args = ap.parse_args()

    try:
        with open(args.path, encoding="utf-8") as f:
            doc = json.load(f)
    except FileNotFoundError:
        print(f"File not found: {args.path}", file=sys.stderr)
        return 2
    except json.JSONDecodeError as e:
        print(f"Failed to parse JSON: {e}", file=sys.stderr)
        return 2

    rep = Report()
    check_top_level(doc, rep)
    if isinstance(doc.get("places"), list):
        for i, p in enumerate(doc["places"]):
            if isinstance(p, dict):
                check_place(p, i, doc, rep)
            else:
                rep.add("P0", f"places[{i}]", "element is not an object")
        check_cross(doc, rep)
        check_itinerary(doc, rep)
    if args.check_links:
        check_links(doc, rep)

    if args.json:
        print(json.dumps(
            {"ok": not rep.failed,
             "findings": [{"level": l, "where": w, "message": m} for l, w, m in rep.items]},
            ensure_ascii=False, indent=2))
    else:
        render(rep, args.quiet)

    return 1 if rep.failed else 0


if __name__ == "__main__":
    sys.exit(main())
