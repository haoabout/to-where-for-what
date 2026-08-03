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
        rep.add("P0", "根", f"schema_version 应为 {SCHEMA_VERSION}，实际为 {doc.get('schema_version')!r}")
    for key in ("trip", "categories", "places"):
        if key not in doc:
            rep.add("P0", "根", f"缺少顶层字段 {key}")

    trip = doc.get("trip") or {}
    for f in ("destination", "country", "bbox", "timezone", "output_language",
              "local_language", "days", "party", "pace", "generated_at", "verified_at"):
        if _blank(trip.get(f)):
            rep.add("P0", "trip", f"缺少必填字段 {f}")

    bbox = trip.get("bbox")
    if not (isinstance(bbox, list) and len(bbox) == 4 and all(isinstance(x, (int, float)) for x in bbox)):
        rep.add("P0", "trip", "bbox 必须是 [minLon,minLat,maxLon,maxLat] 四个数字")
    elif not (bbox[0] < bbox[2] and bbox[1] < bbox[3]):
        rep.add("P0", "trip", f"bbox 的 min/max 顺序反了: {bbox}")

    unknown_trip = set(trip) - KNOWN_TRIP_FIELDS
    if unknown_trip:
        rep.add("P2", "trip", f"出现契约外的字段 {sorted(unknown_trip)}")

    verified = _parse_date(trip.get("verified_at"))
    if verified:
        age = (date.today() - verified).days
        if age > STALE_DAYS:
            rep.add("P1", "trip", f"verified_at 距今 {age} 天，开放时间/门票可能已变，建议重新核验")
    elif trip.get("verified_at"):
        rep.add("P0", "trip", f"verified_at 格式应为 YYYY-MM-DD，实际 {trip.get('verified_at')!r}")


def check_place(p, idx, doc, rep: Report) -> None:
    pid = p.get("id") or f"#{idx}"
    where = f"places[{idx}] {pid}"
    trip = doc.get("trip") or {}

    kind = p.get("kind") or "attraction"
    if kind not in KINDS:
        rep.add("P0", where, f"kind={p.get('kind')!r} 非法，应为 {sorted(KINDS)}")
        kind = "attraction"

    origin = p.get("origin")
    if origin is not None and origin not in ORIGINS:
        rep.add("P0", where, f"origin={origin!r} 非法，应为 {sorted(ORIGINS)}")
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
        rep.add("P2", where, "用户添加的粗胚（origin=user 且无 tier），待 AI 研究补全")
    else:
        req_str, req_any = REQUIRED_STR, REQUIRED_ANY

    for f in req_str:
        if f in excused:
            continue
        if _blank(p.get(f)):
            rep.add("P0", where, f"缺少必填字段 {f}")
    for f in req_any:
        if f in excused:
            continue
        if p.get(f) is None:
            rep.add("P0", where, f"缺少必填字段 {f}")
    if excused:
        got = [f for f in sorted(excused) if not _blank(p.get(f))]
        rep.add("P2", where,
                f"因 verify.state={vstate} 豁免了 {sorted(excused)} 的必填检查"
                + (f"，其中 {got} 实际有值" if got else "，均为空"))

    # 枚举
    for field, allowed in (("tier", TIERS), ("scale", SCALES),
                           ("status", STATUSES), ("booking", BOOKINGS)):
        v = p.get(field)
        if v is not None and v not in allowed:
            rep.add("P0", where, f"{field}={v!r} 非法，应为 {sorted(allowed)}")
    if "choice" in p and p["choice"] not in CHOICES:
        rep.add("P0", where, f"choice={p['choice']!r} 非法")

    # 住宿不属于任何景点分类，不参与配额，也就不必落在 categories 里
    cat_ids = {c.get("id") for c in doc.get("categories") or []}
    if kind != "lodging" and p.get("category") and p["category"] not in cat_ids:
        rep.add("P0", where, f"category={p['category']!r} 未在 categories 中定义")

    # 坐标
    c = p.get("coord")
    if not isinstance(c, dict) or not isinstance(c.get("lon"), (int, float)) \
            or not isinstance(c.get("lat"), (int, float)):
        rep.add("P0", where, 'coord 必须是 {"lon": 数字, "lat": 数字}（不许用数组，防经纬度写反）')
    else:
        lon, lat = c["lon"], c["lat"]
        if not (-180 <= lon <= 180 and -90 <= lat <= 90):
            rep.add("P0", where, f"坐标超出合法范围: lon={lon} lat={lat}")
        else:
            bbox = trip.get("bbox")
            if isinstance(bbox, list) and len(bbox) == 4:
                if not (bbox[0] <= lon <= bbox[2] and bbox[1] <= lat <= bbox[3]):
                    if origin == "user":
                        # 临时起意的点常在 bbox 边缘外（大阪行程加奈良），
                        # 坐标又来自 OSM 而非 AI 之手，写反/搜错的先验低得多
                        rep.add("P1", where,
                                f"用户添加的点坐标 ({lon}, {lat}) 在目的地 bbox 之外，"
                                f"请确认不是搜错了同名地点")
                    else:
                        rep.add("P0", where,
                                f"坐标 ({lon}, {lat}) 落在目的地 bbox 之外——"
                                f"极可能是经纬度写反或搜错了同名地点")

    # 来源（防幻觉主闸门）
    srcs = p.get("sources")
    if not isinstance(srcs, list) or not srcs:
        rep.add("P0", where, "sources 为空——未经联网核验的条目不许进入数据集")
    else:
        for i, s in enumerate(srcs):
            if not isinstance(s, dict) or not _is_url(s.get("url")):
                rep.add("P0", where, f"sources[{i}] 缺少合法的 http(s) url")

    # 状态
    if p.get("status") and p["status"] != "open" and _blank(p.get("status_note")):
        rep.add("P0", where, f"status={p['status']} 但缺少 status_note（需说明起止时间）")

    # 核实状态。与 status 正交：status 说场馆开不开，verify 说我们查没查清。
    v = p.get("verify")
    if v is not None:
        if not isinstance(v, dict):
            rep.add("P0", where, "verify 必须是对象 {state, note, check}")
        else:
            st = v.get("state")
            if st not in VERIFY_STATES:
                rep.add("P0", where, f"verify.state={st!r} 非法，应为 {sorted(VERIFY_STATES)}")
            elif st != "verified":
                if _blank(v.get("note")):
                    rep.add("P0", where,
                            f"verify.state={st} 但缺少 note——必须写清尝试过什么、为什么失败，"
                            f"否则用户无从判断该不该自己去查")
                if not v.get("check"):
                    rep.add("P1", where, f"verify.state={st} 建议用 check 列出需用户自行确认的项")
                rep.add("P1", where,
                        f"核实被拦截或不完整（{st}）：{str(v.get('note'))[:60]}…"
                        f" —— 页面会标注提醒用户自行确认")

    # closed_days。住宿没有「闭馆日」这个概念，不参与。
    cd = p.get("closed_days")
    if cd is None:
        if kind != "lodging" and not is_stub:
            rep.add("P1", where,
                    "closed_days 为 null（查不到或来源矛盾）——无法校验闭馆日与行程是否冲突，"
                    "请在 detail 里提醒用户出发前自行确认")
    else:
        if not isinstance(cd, list) or any(not isinstance(d, int) or not 1 <= d <= 7 for d in cd):
            rep.add("P0", where, "closed_days 必须是 1–7 的整数数组（1=周一），全年无休填 []")
        else:
            trip_days = _trip_weekdays(trip)
            if trip_days and trip_days.issubset(set(cd)):
                names = "".join("一二三四五六日"[d - 1] for d in sorted(trip_days))
                rep.add("P0", where,
                        f"闭馆日覆盖整个行程（行程含周{names}，该点这几天都不开）——"
                        f"不该让用户在清单里看到它可选")

    # spot 归属。parent_id 是可选的——实测发现有些微景点（渡船口、街边小神社）
    # 在它所在片区里本来就没有主景点，强行指定 parent 会造出假的从属关系。
    # 没有 parent 的 spot 在清单里作为独立小卡片渲染，这是可接受的。
    if p.get("scale") == "spot":
        parent = p.get("parent_id")
        if _blank(parent):
            rep.add("P2", where, 'scale="spot" 未指定 parent_id，将作为独立卡片显示。'
                                 '若同片区有主景点，挂上去可以让清单更紧凑')
        else:
            all_ids = {q.get("id") for q in doc.get("places") or []}
            if parent not in all_ids:
                rep.add("P0", where, f"parent_id={parent!r} 指向不存在的景点")

    # 数值
    for f in ("duration_min", "photo_index"):
        v = p.get(f)
        if v is not None and not isinstance(v, int):
            rep.add("P0", where, f"{f} 必须是整数，实际 {v!r}")
    if isinstance(p.get("photo_index"), int) and not 1 <= p["photo_index"] <= 5:
        rep.add("P0", where, f"photo_index 应在 1–5，实际 {p['photo_index']}")
    for f in ("indoor", "night"):
        if p.get(f) is not None and not isinstance(p[f], bool):
            rep.add("P0", where, f"{f} 必须是布尔值，实际 {p[f]!r}")

    # ---- P1
    # 粗胚豁免：name_local 是研究产物，页面端只有 OSM namedetails 里碰巧有才填得上
    if (not is_stub and trip.get("local_language") and trip.get("output_language")
            and trip["local_language"] != trip["output_language"]
            and _blank(p.get("name_local"))):
        rep.add("P1", where, "当地语言与输出语言不同，应提供 name_local（且需能在地图搜到）")

    unknown = set(p) - KNOWN_PLACE_FIELDS
    if unknown:
        rep.add("P2", where,
                f"出现契约外的字段 {sorted(unknown)}——模板不会渲染它们，内容会静默丢失。"
                f"确需新字段请先改 data-schema.md 与 validate.py")

    # ---- P2
    # 住宿和粗胚不参与这几条：摄影机位、配图、长篇介绍都是研究后的质量要求。
    # 对着酒店或刚钉下的粗胚提"缺少拍摄建议"只会制造噪声，把真正该看的提示淹掉。
    if kind != "lodging" and not is_stub:
        if _blank(p.get("photo_note")):
            rep.add("P2", where, "缺少 photo_note（画面描述与拍摄建议）")
        if not p.get("images"):
            rep.add("P2", where, "没有配图")
        if isinstance(p.get("detail"), str) and 0 < len(p["detail"].strip()) < 60:
            rep.add("P2", where, f"detail 仅 {len(p['detail'].strip())} 字，偏薄")
    if p.get("booking") in ("required", "recommended") and _blank(p.get("booking_url")):
        rep.add("P2", where, f"booking={p['booking']} 但缺少 booking_url")


def check_cross(doc, rep: Report) -> None:
    places = doc.get("places") or []

    seen: dict[str, int] = {}
    for i, p in enumerate(places):
        pid = p.get("id")
        if not pid:
            continue
        if pid in seen:
            rep.add("P0", f"places[{i}]", f"id {pid!r} 与 places[{seen[pid]}] 重复")
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
                    f"「{label}」只有 {n} 个，低于保底 {lo}——"
                    f"若目的地确实没有更多，请在正文如实说明，不要凑数硬编")
        if isinstance(hi, int) and n > hi:
            rep.add("P1", "categories", f"「{label}」有 {n} 个，超过上限 {hi}")

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
                        f"{pa.get('name')} 与 {pb.get('name')} 坐标相距仅 {d:.0f} 米，疑似重复录入")

    total = len([p for p in places if (p.get("kind") or "attraction") != "lodging"])
    if total < 15:
        rep.add("P1", "places", f"总共只有 {total} 个景点，可能搜得不够充分（目标 35–50）")
    elif total > 60:
        rep.add("P1", "places", f"总共 {total} 个景点，超出建议上限，用户筛选负担过重")


WEEK_CN = ["", "周一", "周二", "周三", "周四", "周五", "周六", "周日"]


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
        rep.add("P0", "itinerary", "itinerary 必须是数组")
        return

    places = doc.get("places") or []
    by_id = {p.get("id"): p for p in places if p.get("id")}

    seen_n: dict[int, int] = {}
    assigned: dict[str, list[int]] = {}      # place id -> 出现在哪几天

    for di, day in enumerate(it):
        dwhere = f"itinerary[{di}]"
        if not isinstance(day, dict):
            rep.add("P0", dwhere, "每一天必须是对象")
            continue

        n = day.get("n")
        label = day.get("label") or (f"第 {n} 天" if isinstance(n, int) else dwhere)
        if not isinstance(n, int):
            rep.add("P0", dwhere, f"n 必须是整数（0 表示抵达当晚），实际 {n!r}")
        elif n in seen_n:
            rep.add("P0", dwhere, f"n={n} 与 itinerary[{seen_n[n]}] 重复")
        else:
            seen_n[n] = di

        # 日期用来做闭馆冲突判断；第 0 天可以没有独立日期
        d = _parse_date(day.get("date")) if day.get("date") else None
        if day.get("date") and not d:
            rep.add("P0", dwhere, f"date 格式应为 YYYY-MM-DD，实际 {day.get('date')!r}")

        entries = day.get("places")
        if not isinstance(entries, list):
            rep.add("P0", dwhere, "places 必须是数组（顺序即游览顺序）")
            continue
        if not entries:
            rep.add("P1", dwhere, f"{label} 一个地点都没有")

        for ei, ent in enumerate(entries):
            ewhere = f"{dwhere}.places[{ei}]"
            if not isinstance(ent, dict) or not ent.get("id"):
                rep.add("P0", ewhere, '每一项必须是 {"id": "..."} 形式的对象')
                continue
            pid = ent["id"]
            p = by_id.get(pid)
            if p is None:
                rep.add("P0", ewhere, f"id {pid!r} 在 places 里不存在")
                continue

            assigned.setdefault(pid, []).append(n if isinstance(n, int) else di)

            # ---- 闭馆冲突：这不是判断题，是那天去不了 ----
            if d is not None:
                wd = d.isoweekday()
                cds = p.get("closed_days")
                if isinstance(cds, list) and wd in cds:
                    rep.add("P0", ewhere,
                            f"{p.get('name')} 排在 {day.get('date')}（{WEEK_CN[wd]}），"
                            f"但它当天闭馆（closed_days={cds}）")
            if p.get("status") == "permanently_closed":
                rep.add("P0", ewhere, f"{p.get('name')} 已永久关闭，不能排进行程")

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
                        f"{p.get('name')} 被排进第 {distinct} 天却没写 note，"
                        f"确认是有意重复访问而非误操作")

    for p in places:
        if (p.get("kind") or "attraction") == "lodging" and p.get("id") not in assigned:
            rep.add("P1", "itinerary",
                    f"住宿「{p.get('name')}」没有出现在任何一天——"
                    f"住宿要放进当天的行程里，起点终点才说得清")


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
    print(f"  检查 {len(targets)} 个链接…", file=sys.stderr)
    with ThreadPoolExecutor(max_workers=12) as ex:
        for url, status in ex.map(_fetch, targets):
            if isinstance(status, int) and status < 400:
                continue
            if status in BOT_BLOCKED:
                # 站点活着，只是拒绝自动访问——不能算死链，但值得人工点一下确认
                for where in targets[url]:
                    rep.add("P2", where, f"无法自动验证（疑似反爬，HTTP {status}），请人工确认：{url}")
            else:
                for where in targets[url]:
                    rep.add("P1", where, f"链接不可达 [{status}] {url}")


# ---------------------------------------------------------------- output

LEVEL_STYLE = {"P0": ("\033[91m", "拒绝"), "P1": ("\033[93m", "警告"), "P2": ("\033[96m", "提示")}


def render(rep: Report, quiet: bool) -> None:
    if not rep.items:
        print("\033[92m✓ 校验通过，无任何问题\033[0m")
        return
    for level in ("P0", "P1", "P2"):
        items = rep.of(level)
        if not items or (quiet and level == "P2"):
            continue
        color, label = LEVEL_STYLE[level]
        print(f"\n{color}{level} · {label}（{len(items)} 条）\033[0m")
        for _, where, msg in items:
            print(f"  {color}•\033[0m {where}\n      {msg}")
    n0, n1, n2 = len(rep.of("P0")), len(rep.of("P1")), len(rep.of("P2"))
    print(f"\n合计  P0 {n0} · P1 {n1} · P2 {n2}")
    if n0:
        print("\033[91m→ 存在 P0，数据不可用，必须修正后重新校验\033[0m")


def main() -> int:
    ap = argparse.ArgumentParser(description="校验 places.json")
    ap.add_argument("path")
    ap.add_argument("--check-links", action="store_true", help="并发检查所有 URL 是否可达（较慢）")
    ap.add_argument("--json", action="store_true", help="以 JSON 输出结果")
    ap.add_argument("--quiet", action="store_true", help="不显示 P2 提示")
    args = ap.parse_args()

    try:
        with open(args.path, encoding="utf-8") as f:
            doc = json.load(f)
    except FileNotFoundError:
        print(f"找不到文件: {args.path}", file=sys.stderr)
        return 2
    except json.JSONDecodeError as e:
        print(f"JSON 解析失败: {e}", file=sys.stderr)
        return 2

    rep = Report()
    check_top_level(doc, rep)
    if isinstance(doc.get("places"), list):
        for i, p in enumerate(doc["places"]):
            if isinstance(p, dict):
                check_place(p, i, doc, rep)
            else:
                rep.add("P0", f"places[{i}]", "元素不是对象")
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
