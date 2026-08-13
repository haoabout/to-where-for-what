#!/usr/bin/env python3
"""Regression tests for validate.py: deliberately corrupt the data and
assert the validator catches it.

    python3 dev/test_validate.py
"""
from __future__ import annotations

import copy
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "skills/to-where-for-what/scripts"))
import validate  # noqa: E402


def base_doc() -> dict:
    """A minimal document that should pass cleanly."""
    return {
        "schema_version": 1,
        "trip": {
            "destination": "大阪", "destination_local": "大阪", "country": "JP",
            "bbox": [135.35, 34.55, 135.65, 34.80],
            "timezone": "Asia/Tokyo",
            "output_language": "zh-CN", "local_language": "ja",
            "dates": {"start": "2026-09-12", "end": "2026-09-13"},  # Saturday, Sunday
            "days": 2, "party": "情侣 2 人", "pace": "中等",
            "generated_at": str(validate.date.today()),
            "verified_at": str(validate.date.today()),
            # In the fixture on purpose: theme_hue once drifted out of
            # KNOWN_TRIP_FIELDS and every legal trip got flagged. The baseline
            # check ("zero unexpected findings") now guards against a repeat.
            "theme_hue": 334,
        },
        "categories": [
            {"id": "museum", "label": "博物馆", "min": 1, "max": 8},
            {"id": "landmark", "label": "地标", "min": 1, "max": 6},
        ],
        "places": [
            {
                "id": "os-001", "name": "大阪城", "name_local": "大阪城",
                "category": "landmark", "tier": "S", "scale": "2-3h", "area": "大阪城",
                "coord": {"lon": 135.5259, "lat": 34.6873},
                "hours": "09:00-17:00", "last_entry": "16:30",
                "closed_days": [], "closed": "12/28-1/1",
                "ticket": "¥600", "booking": "none", "status": "open",
                "duration_min": 150, "indoor": False, "night": False,
                "pitch": "天守阁与护城河。", "detail": "x" * 80,
                "photo_index": 4, "photo_note": "西之丸庭园角度最好。",
                "images": [{"url": "https://example.org/a.jpg", "credit": "© x"}],
                "sources": [{"title": "官网", "url": "https://www.osakacastle.net/"}],
                "choice": None, "choice_reason": "",
            },
            {
                "id": "os-002", "name": "中之岛美术馆", "name_local": "大阪中之島美術館",
                "category": "museum", "tier": "A", "scale": "2-3h", "area": "中之岛",
                "coord": {"lon": 135.4914, "lat": 34.6914},
                "hours": "10:00-18:00", "last_entry": "17:30",
                "closed_days": [1], "closed": "周一",
                "ticket": "¥1200", "booking": "recommended",
                "booking_url": "https://nakka-art.jp/", "status": "open",
                "duration_min": 120, "indoor": True, "night": False,
                "pitch": "黑立方体外观。", "detail": "y" * 80,
                "photo_index": 4, "photo_note": "红色扶梯。",
                "images": [{"url": "https://example.org/b.jpg", "credit": "© y"}],
                "sources": [{"title": "官网", "url": "https://nakka-art.jp/"}],
                "choice": None, "choice_reason": "",
            },
        ],
    }


def run(doc) -> validate.Report:
    rep = validate.Report()
    validate.check_document(doc, rep)
    return rep


def with_itinerary(doc: dict, **kw) -> None:
    """Attach a two-day schedule to the baseline document. The trip dates are
    09-12 (Sat) and 09-13 (Sun)."""
    doc["itinerary"] = [
        {"n": 1, "date": "2026-09-12", "label": "第 1 天",
         "places": [{"id": "os-001"}]},
        {"n": 2, "date": "2026-09-13", "label": "第 2 天",
         "places": [{"id": "os-002"}]},
    ]
    for k, v in kw.items():
        doc["itinerary"][0][k] = v


def hotel(doc: dict, **kw) -> dict:
    """Append a lodging entry to places and return it."""
    h = {"id": "os-h1", "name": "梅田某酒店", "name_local": "梅田のホテル",
         "kind": "lodging",
         "area": "梅田", "coord": {"lon": 135.4980, "lat": 34.7025},
         # Lodging passes the anti-hallucination gate too: the AI must
         # actually look it up to confirm it exists and get its address
         "sources": [{"title": "官网", "url": "https://example.org/hotel"}]}
    h.update(kw)
    doc["places"].append(h)
    return h


def messages(rep: validate.Report, level: str) -> str:
    return " || ".join(m for lv, _, m in rep.items if lv == level)


PASS, FAIL = "\033[92m✓\033[0m", "\033[91m✗\033[0m"
results: list[bool] = []


def case(name: str, mutate, level: str, needle: str) -> None:
    """The needle decides how the assertion works:

        "text"    the level must contain this text
        ""        the level must have no findings at all
        "!text"   the level must **not** contain this text (other findings ok)

    An empty string can't go through `needle in got` — `"" in s` is always
    true, so such a case would always pass and amount to no test at all. And
    when verifying that "a particular false positive is gone", requiring the
    whole level to be empty usually won't work — the baseline document itself
    carries expected findings like "sample too small"."""
    doc = base_doc()
    mutate(doc)
    rep = run(doc)
    got = messages(rep, level)
    if needle == "":
        ok, expect = (not got), "no findings at all"
    elif needle.startswith("!"):
        ok, expect = (needle[1:] not in got), f"must not contain {needle[1:]!r}"
    else:
        ok, expect = (needle in got), repr(needle)
    results.append(ok)
    print(f"  {PASS if ok else FAIL} {name}")
    if not ok:
        print(f"      expected {level} {expect}")
        print(f"      actual   {level}: {got or '(none)'}")


def main() -> int:
    print("\nBaseline document: zero P0, and the only P1 is the expected \"sample too small\" notice")
    rep = run(base_doc())
    p1s = [m for _, _, m in rep.of("P1")]
    expected_p1 = [m for m in p1s if "only 2 places in total" in m]
    clean = (not rep.of("P0")) and len(p1s) == 1 and len(expected_p1) == 1
    results.append(clean)
    print(f"  {PASS if clean else FAIL} baseline is clean (only the expected sample-size notice remains)")
    if not clean:
        for lv, w, m in rep.items:
            if lv in ("P0", "P1"):
                print(f"      [{lv}] {w}: {m}")

    print("\nP0 · must be blocked")
    case("missing sources (the main anti-hallucination gate)",
         lambda d: d["places"][1].pop("sources"), "P0", "sources is empty")
    case("a non-http fake link in sources",
         lambda d: d["places"][1].update(sources=[{"title": "x", "url": "内部资料"}]),
         "P0", "valid http(s) url")
    case("coord written as an array (invites lon/lat swaps)",
         lambda d: d["places"][1].update(coord=[135.49, 34.69]), "P0", "arrays are forbidden")
    case("lon/lat swapped → falls outside the bbox",
         lambda d: d["places"][1].update(coord={"lon": 34.6914, "lat": 135.4914}),
         "P0", "out of range")
    case("wrong same-named place (a Tokyo point in an Osaka trip)",
         lambda d: d["places"][1].update(coord={"lon": 139.767, "lat": 35.681}),
         "P0", "outside the destination bbox")
    case("closure days cover the whole trip (weekend trip, closed weekends)",
         lambda d: d["places"][1].update(closed_days=[6, 7]), "P0", "closure days cover the whole trip")
    case("status is not open but unexplained",
         lambda d: d["places"][1].update(status="renovating"), "P0", "status_note is missing")
    case("duplicate id",
         lambda d: d["places"][1].update(id="os-001"), "P0", "duplicates")
    case("illegal tier enum",
         lambda d: d["places"][1].update(tier="SS"), "P0", "tier='SS' is invalid")
    case("parent_id points at a nonexistent place",
         lambda d: d["places"][1].update(scale="spot", parent_id="os-999"),
         "P0", "points at a nonexistent place")
    case("undefined category",
         lambda d: d["places"][1].update(category="ufo"), "P0", "not defined in categories")
    case("photo_index out of range",
         lambda d: d["places"][1].update(photo_index=9), "P0", "should be 1–5")
    case("bbox min/max reversed",
         lambda d: d["trip"].update(bbox=[135.65, 34.80, 135.35, 34.55]), "P0", "order is reversed")

    print("\nP1 · should warn")
    case("local language differs but name_local is missing",
         lambda d: d["places"][1].pop("name_local"), "P1", "name_local")
    case("category count below minimum",
         lambda d: d["categories"].append({"id": "food", "label": "餐饮", "min": 2, "max": 5}),
         "P1", "below the minimum")
    case("two places with nearly identical coordinates",
         lambda d: d["places"][1].update(coord={"lon": 135.52591, "lat": 34.68731}),
         "P1", "possible duplicate")
    case("verified_at is stale",
         lambda d: d["trip"].update(verified_at=str(validate.date.today() - validate.timedelta(days=45))),
         "P1", "is 45 days old")

    print("\ntheme_hue · a legal trip field, validated 0–359")
    case("legal theme_hue is not flagged as outside the contract",
         lambda d: d["trip"].update(theme_hue=128), "P2", "!fields outside the contract")
    case("theme_hue out of range",
         lambda d: d["trip"].update(theme_hue=400), "P1", "theme_hue must be an integer 0–359")
    case("theme_hue as a string",
         lambda d: d["trip"].update(theme_hue="pink"), "P1", "theme_hue must be an integer 0–359")
    case("theme_hue as a boolean (bool is an int subtype — still wrong)",
         lambda d: d["trip"].update(theme_hue=True), "P1", "theme_hue must be an integer 0–359")
    case("absent theme_hue stays legal (the page keeps its default palette)",
         lambda d: d["trip"].pop("theme_hue"), "P1", "!theme_hue")

    print("\nP2 · should note")
    case("missing photo_note",
         lambda d: d["places"][1].pop("photo_note"), "P2", "photo_note")
    case("booking required but no booking_url",
         lambda d: d["places"][1].pop("booking_url"), "P2", "booking_url")
    case("detail too short",
         lambda d: d["places"][1].update(detail="很好看"), "P2", "thin")
    # Rule changed after end-to-end testing: micro-spots with no major place
    # in their area are normal (ferry piers, small roadside shrines), and
    # forcing parent_id would fabricate a false hierarchy — downgraded to a note.
    case("spot without parent_id (should note, not reject)",
         lambda d: d["places"][1].update(scale="spot"), "P2", "renders as a standalone card")

    print("\nverify · handling blocked verification")
    def blocked(d, **kw):
        p = d["places"][1]
        p["verify"] = {"state": "blocked", "note": "官网 404，专用域名连不上",
                       "check": ["营业时间", "票价"]}
        p.update(**kw)
    case("blocked allows hours/ticket/status to be empty",
         lambda d: blocked(d, hours=None, ticket=None, status=None), "P1", "verification blocked")
    case("blocked without a note — must be rejected",
         lambda d: d["places"][1].update(verify={"state": "blocked"}), "P0", "note is missing")
    case("illegal verify.state value",
         lambda d: d["places"][1].update(verify={"state": "maybe", "note": "x"}), "P0", "is invalid")
    case("verified grants no exemption from required fields",
         lambda d: d["places"][1].update(verify={"state": "verified"}, hours=None),
         "P0", "missing required field hours")

    print("\nitinerary · scheduling result")
    case("a clean schedule should produce no P0",
         lambda d: with_itinerary(d), "P0", "")     # needle 为空串 → 只要不崩就算过
    case("scheduled a nonexistent id",
         lambda d: (with_itinerary(d),
                    d["itinerary"][0]["places"].append({"id": "os-999"})),
         "P0", "does not exist in places")
    case("scheduled on a closure day (Nakanoshima museum closes Mondays, scheduled on Monday)",
         lambda d: (with_itinerary(d),
                    d["itinerary"][0].update(date="2026-09-14"),   # 周一
                    d["itinerary"][0]["places"].append({"id": "os-002"})),
         "P0", "closed that day")
    case("duplicate n",
         lambda d: (with_itinerary(d), d["itinerary"][1].update(n=1)),
         "P0", "duplicates itinerary[0]")
    case("a day left empty",
         lambda d: (with_itinerary(d), d["itinerary"][1].update(places=[])),
         "P1", "has no places at all")
    case("entry is not an object (written as a bare id)",
         lambda d: (with_itinerary(d), d["itinerary"][0].update(places=["os-001"])),
         "P0", "of the form")
    case("illegal date format",
         lambda d: (with_itinerary(d), d["itinerary"][0].update(date="2026/09/12")),
         "P0", "date should be YYYY-MM-DD")
    case("a permanently closed place was scheduled",
         lambda d: (with_itinerary(d),
                    d["places"][0].update(status="permanently_closed",
                                          status_note="2025 年拆除")),
         "P0", "permanently closed")
    case("same place on two days without a note",
         lambda d: (with_itinerary(d),
                    d["itinerary"][1]["places"].append({"id": "os-001"})),
         "P2", "without a note")
    case("a note silences the notice",
         lambda d: (with_itinerary(d),
                    d["itinerary"][1]["places"].append({"id": "os-001", "note": "夜景"})),
         "P2", "")
    # A hotel appearing twice a day (leaving in the morning, returning at
    # night), four times over two days, is normal and not a mistake
    case("daily lodging must not be treated as a duplicate mistake",
         lambda d: (hotel(d), with_itinerary(d),
                    d["itinerary"][0]["places"].insert(0, {"id": "os-h1"}),
                    d["itinerary"][0]["places"].append({"id": "os-h1"}),
                    d["itinerary"][1]["places"].insert(0, {"id": "os-h1"}),
                    d["itinerary"][1]["places"].append({"id": "os-h1"})),
         "P2", "")
    case("lodging scheduled on no day",
         lambda d: (hotel(d), with_itinerary(d)),
         "P1", "appears on no day")
    case("itinerary is not an array",
         lambda d: d.update(itinerary={"n": 1}), "P0", "must be an array")

    print("\nprep / booked · pre-departure checklist state")
    case("valid prep.checked on a place produces no P0",
         lambda d: d["places"][1].update(prep={"checked": True}), "P0", "")
    case("prep is not an object",
         lambda d: d["places"][1].update(prep="checked"), "P0", "prep must be an object")
    case("prep.checked is not a boolean",
         lambda d: d["places"][1].update(prep={"checked": "yes"}),
         "P0", "prep.checked must be a boolean")
    case("unknown key inside prep is noted, not rejected",
         lambda d: d["places"][1].update(prep={"booked": True}),
         "P2", "prep has fields outside the contract")
    case("valid booked on an itinerary entry produces no P0",
         lambda d: (with_itinerary(d),
                    d["itinerary"][0]["places"][0].update(booked=True)), "P0", "")
    case("booked is not a boolean",
         lambda d: (with_itinerary(d),
                    d["itinerary"][0]["places"][0].update(booked="yes")),
         "P0", "booked must be a boolean")

    # The nudge window compares against the real today, so these cases build
    # their dates relative to it; os-001 has no closure days, keeping the
    # weekday of "today + n" from mattering.
    def nudge(d, days_out, booked=None):
        start = validate.date.today() + validate.timedelta(days=days_out)
        d["trip"]["dates"] = {"start": str(start),
                              "end": str(start + validate.timedelta(days=1))}
        d["places"][0].update(booking="required",
                              booking_url="https://example.org/book")
        ent = {"id": "os-001"}
        if booked is not None:
            ent["booked"] = booked
        d["itinerary"] = [{"n": 1, "date": str(start), "places": [ent]}]
    case("booking-required visit unbooked within 14 days of departure",
         lambda d: nudge(d, 7), "P1", "aren't marked booked")
    case("marking it booked silences the nudge",
         lambda d: nudge(d, 7, booked=True), "P1", "!aren't marked booked")
    case("no nudge while departure is still far away",
         lambda d: nudge(d, 60), "P1", "!aren't marked booked")

    print("\nkind · lodging uses the reduced required set")
    case("lodging missing tier/tickets/closure days must not error",
         lambda d: (hotel(d), with_itinerary(d),
                    d["itinerary"][0]["places"].insert(0, {"id": "os-h1"})),
         "P0", "")
    case("lodging must not be asked why closed_days is null",
         lambda d: (hotel(d), with_itinerary(d),
                    d["itinerary"][0]["places"].insert(0, {"id": "os-h1"})),
         "P1", "!closed_days is null")
    case("lodging still needs coordinates",
         lambda d: (hotel(d, coord=None), with_itinerary(d),
                    d["itinerary"][0]["places"].insert(0, {"id": "os-h1"})),
         "P0", "missing required field coord")
    case("illegal kind value",
         lambda d: d["places"][1].update(kind="hostel"), "P0", "kind='hostel' is invalid")

    print("\nmalformed shapes · report P0, never traceback")
    # The validator is the delivery gate for AI-produced data; a wrong
    # container shape is exactly the input it must survive.
    rep = validate.Report()
    validate.check_document([{"id": "x"}], rep)
    shape_ok = "top-level value must be an object" in messages(rep, "P0")
    results.append(shape_ok)
    print(f"  {PASS if shape_ok else FAIL} top-level array reports P0 instead of crashing")

    case("trip is an array",
         lambda d: d.update(trip=[1, 2]), "P0", "trip must be an object")
    case("trip is a string",
         lambda d: d.update(trip="大阪"), "P0", "trip must be an object")
    case("a bad trip container doesn't stop the other checks",
         lambda d: (d.update(trip=[1]), d["places"][1].pop("sources")),
         "P0", "sources is empty")
    case("categories is an object instead of an array",
         lambda d: d.update(categories={"id": "museum"}),
         "P0", "categories must be an array")
    case("categories is a list of bare strings",
         lambda d: d.update(categories=["museum", "landmark"]),
         "P0", "element is not an object")
    case("verify is a string",
         lambda d: d["places"][1].update(verify="ok"), "P0", "verify must be an object")
    case("verify is an array",
         lambda d: d["places"][1].update(verify=["hours"]), "P0", "verify must be an object")
    case("choice is an array",
         lambda d: d["places"][1].update(choice=["yes"]), "P0", "is invalid")
    case("kind is an object",
         lambda d: d["places"][1].update(kind={"a": 1}), "P0", "is invalid")
    case("tier is an array (unhashable enum value)",
         lambda d: d["places"][1].update(tier=["S"]), "P0", "is invalid")
    case("retro is an array",
         lambda d: d["trip"].update(retro=["done"]), "P0", "retro=")
    case("category is an array",
         lambda d: d["places"][1].update(category=["museum"]),
         "P0", "category must be a string")
    case("parent_id is an array",
         lambda d: d["places"][1].update(scale="spot", parent_id=["os-001"]),
         "P0", "points at a nonexistent place")
    case("itinerary entry id is an array",
         lambda d: (with_itinerary(d),
                    d["itinerary"][0]["places"].append({"id": ["os-001"]})),
         "P0", "of the form")
    case("trip.dates is an array (weekday and nudge checks degrade quietly)",
         lambda d: (d["trip"].update(dates=["2026-09-12"]), with_itinerary(d)),
         "P0", "")

    ok, total = sum(results), len(results)
    print(f"\n{'\033[92m' if ok == total else '\033[91m'}{ok}/{total} passed\033[0m")
    return 0 if ok == total else 1


if __name__ == "__main__":
    sys.exit(main())
