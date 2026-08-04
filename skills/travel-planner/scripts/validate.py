#!/usr/bin/env python3
"""places.json 校验器 —— 防幻觉与数据完整性的主闸门。

用法:
    python3 validate.py <places.json> [--check-links] [--json] [--quiet]

分级:
    P0  拒绝  —— 数据不可用，退出码 1
    P1  警告  —— 可以继续，但很可能有问题
    P2  提示  —— 质量建议

契约见 references/data-schema.md。只依赖标准库。
"""

from __future__ import annotations

import argparse
import json
import re
import sys
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

# 契约允许的全部字段。多出来的字段说明 AI 自己发明了 schema，
# 而模板不会渲染它们——静默丢失比报错更糟，所以要提示。
KNOWN_PLACE_FIELDS = {
    "id", "name", "name_local", "name_en", "kind", "category", "tier", "scale",
    "parent_id", "area", "coord", "hours", "last_entry", "closed_days",
    "closed", "ticket", "booking", "booking_url", "status", "status_note",
    "duration_min", "indoor", "night", "pitch", "detail", "photo_index",
    "photo_note", "tags", "media", "museum", "images", "sources",
    "verify", "choice", "choice_reason", "origin",
}
KINDS = {"attraction", "lodging"}
ORIGINS = {"user"}

# 住宿走一套精简的必填集：它不是"景点"，没有 tier / 门票 / 闭馆日 / 摄影机位这些概念，
# 硬套景点的契约只会逼着人往里填假数据。
LODGING_REQUIRED_STR = {"id", "name", "area"}
LODGING_REQUIRED_ANY = {"coord"}

# 用户在地图上搜索添加的粗胚（origin=user）：只有名称+坐标+OSM 来源，
# 研究型字段（hours / tier / category …）等 AI 事后补全。逼着页面端造这些
# 数据只会得到假数据，所以走最小必填集。
STUB_REQUIRED_STR = {"id", "name"}
STUB_REQUIRED_ANY = {"coord", "sources"}
KNOWN_TRIP_FIELDS = {
    "destination", "destination_local", "destination_en", "country", "bbox",
    "timezone", "output_language", "local_language", "dates", "days", "party",
    "pace", "bases", "generated_at", "verified_at", "note",
}

# 必填且不可为空字符串
REQUIRED_STR = ["id", "name", "category", "area", "hours", "closed",
                "ticket", "pitch", "detail"]
REQUIRED_ANY = ["tier", "scale", "status", "booking", "coord",
                "duration_min", "photo_index",
                "indoor", "night", "sources"]
# closed_days 允许为 null，表示「查不到或来源互相矛盾」。
# 实测：某老喫茶店的周日营业情况，食べログ说休、大楼官方商户页说不休，且无独立官网可仲裁。
# 这种情况下逼着填一个值，比留空危险得多——用户会按错误的信息安排行程。
# 代价是无法做闭馆日冲突校验，因此降级为 P1 提醒用户自行确认。

# 用浏览器形状的 UA：实测通天阁官网对纯工具 UA 直接拒连，
# 用工具 UA 会把大量正常官网误判成死链。
UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/140.0 Safari/537.36 travel-planner-validate/1.0")
STALE_DAYS = 30
DUPE_METERS = 25

# 这些状态码说明「站点活着但拒绝自动访问」，不等于死链。
# 实测：黑门市场官网对任何 UA 都回 403（反爬），但网页本身完全正常。
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
    """行程覆盖的 ISO 周几集合。无日期时返回 None。"""
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
    # 粗胚的判定是 origin=user 且还没有 tier——AI 一旦补全（填上 tier 等），
    # 它就要按普通景点的完整必填集来验，不能一直躲在精简集后面。
    is_stub = origin == "user" and p.get("tier") is None

    # 核实被拦截时，这几个字段允许为空——那正是「查不到」的含义。
    # 逼着填反而会让用户把猜测当成已核实的信息。
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

    # 枚举
    for field, allowed in (("tier", TIERS), ("scale", SCALES),
                           ("status", STATUSES), ("booking", BOOKINGS)):
        v = p.get(field)
        if v is not None and v not in allowed:
            rep.add("P0", where, f"{field}={v!r} is invalid; must be one of {sorted(allowed)}")
    if "choice" in p and p["choice"] not in CHOICES:
        rep.add("P0", where, f"choice={p['choice']!r} is invalid")

    # 住宿不属于任何景点分类，不参与配额，也就不必落在 categories 里
    cat_ids = {c.get("id") for c in doc.get("categories") or []}
    if kind != "lodging" and p.get("category") and p["category"] not in cat_ids:
        rep.add("P0", where, f"category={p['category']!r} is not defined in categories")

    # 坐标
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
                        # 临时起意的点常在 bbox 边缘外（大阪行程加奈良），
                        # 坐标又来自 OSM 而非 AI 之手，写反/搜错的先验低得多
                        rep.add("P1", where,
                                f"user-added point ({lon}, {lat}) is outside the destination bbox; "
                                f"confirm it isn't a same-named place elsewhere")
                    else:
                        rep.add("P0", where,
                                f"coordinates ({lon}, {lat}) fall outside the destination bbox — "
                                f"very likely swapped lon/lat or a same-named place elsewhere")

    # 来源（防幻觉主闸门）
    srcs = p.get("sources")
    if not isinstance(srcs, list) or not srcs:
        rep.add("P0", where, "sources is empty — entries not verified online must not enter the dataset")
    else:
        for i, s in enumerate(srcs):
            if not isinstance(s, dict) or not _is_url(s.get("url")):
                rep.add("P0", where, f"sources[{i}] lacks a valid http(s) url")

    # 状态
    if p.get("status") and p["status"] != "open" and _blank(p.get("status_note")):
        rep.add("P0", where, f"status={p['status']} but status_note is missing (state the dates)")

    # 核实状态。与 status 正交：status 说场馆开不开，verify 说我们查没查清。
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

    # closed_days。住宿没有「闭馆日」这个概念，不参与。
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

    # spot 归属。parent_id 是可选的——实测发现有些微景点（渡船口、街边小神社）
    # 在它所在片区里本来就没有主景点，强行指定 parent 会造出假的从属关系。
    # 没有 parent 的 spot 在清单里作为独立小卡片渲染，这是可接受的。
    if p.get("scale") == "spot":
        parent = p.get("parent_id")
        if _blank(parent):
            rep.add("P2", where, 'scale="spot" without parent_id renders as a standalone card. '
                                 'If the area has a major place, attaching it keeps the list compact')
        else:
            all_ids = {q.get("id") for q in doc.get("places") or []}
            if parent not in all_ids:
                rep.add("P0", where, f"parent_id={parent!r} points at a nonexistent place")

    # 数值
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
    # 粗胚豁免：name_local 是研究产物，页面端只有 OSM namedetails 里碰巧有才填得上
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
    # 住宿和粗胚不参与这几条：摄影机位、配图、长篇介绍都是研究后的质量要求。
    # 对着酒店或刚钉下的粗胚提"缺少拍摄建议"只会制造噪声，把真正该看的提示淹掉。
    if kind != "lodging" and not is_stub:
        if _blank(p.get("photo_note")):
            rep.add("P2", where, "missing photo_note (shot description and shooting advice)")
        if not p.get("images"):
            rep.add("P2", where, "no images")
        if isinstance(p.get("detail"), str) and 0 < len(p["detail"].strip()) < 60:
            rep.add("P2", where, f"detail is only {len(p['detail'].strip())} characters — thin")
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

    # 分类配额
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

    # 坐标重合
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
    """校验排程结果 itinerary。

    顶层叫 itinerary 而不是 days，是为了避开 trip.days（天数，整数）——
    同名不同层不同类型，写 JSON 的人和读代码的人都会搞混。

    没有 itinerary 就整段跳过：排程是可选阶段，老文件必须继续能用。
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
    assigned: dict[str, list[int]] = {}      # place id -> 出现在哪几天

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

        # 日期用来做闭馆冲突判断；第 0 天可以没有独立日期
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
            p = by_id.get(pid)
            if p is None:
                rep.add("P0", ewhere, f"id {pid!r} does not exist in places")
                continue

            assigned.setdefault(pid, []).append(n if isinstance(n, int) else di)

            # ---- 闭馆冲突：这不是判断题，是那天去不了 ----
            if d is not None:
                wd = d.isoweekday()
                cds = p.get("closed_days")
                if isinstance(cds, list) and wd in cds:
                    rep.add("P0", ewhere,
                            f"{p.get('name')} is scheduled on {day.get('date')} ({WEEK_NAMES[wd]}), "
                            f"but it's closed that day (closed_days={cds})")
            if p.get("status") == "permanently_closed":
                rep.add("P0", ewhere, f"{p.get('name')} is permanently closed and cannot be scheduled")

    # ---- 跨天的检查 ----
    for pid, days_in in assigned.items():
        p = by_id.get(pid) or {}
        # 住宿每天都出现是常态，不是可疑的重复 —— 实测样本里酒店一天出现两次
        # （早上出发、晚上回来）、两天共四次，被误报成「确认不是误操作」。
        if (p.get("kind") or "attraction") == "lodging":
            continue
        distinct = sorted(set(days_in))
        if len(distinct) > 1:
            # 同一地点去两次通常是有意的（白天夜景各一次、世博会连着两天），
            # 但也可能是拖拽误操作。写了 note 就当是有意的。
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


# ---------------------------------------------------------------- links

def _fetch(url: str) -> tuple[str, int | str]:
    """先 HEAD，被拒则退回 GET 首字节。返回状态码或异常名。"""
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
        if e.code in (403, 405, 501):  # 不少站点禁 HEAD
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
                # 站点活着，只是拒绝自动访问——不能算死链，但值得人工点一下确认
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
