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

# 必填且不可为空字符串
REQUIRED_STR = ["id", "name", "category", "area", "hours", "closed",
                "ticket", "pitch", "detail"]
REQUIRED_ANY = ["tier", "scale", "status", "booking", "coord",
                "closed_days", "duration_min", "photo_index",
                "indoor", "night", "sources"]

UA = "travel-planner-validate/1.0 (+https://github.com/; skill data validator)"
STALE_DAYS = 30
DUPE_METERS = 25


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

    for f in REQUIRED_STR:
        if _blank(p.get(f)):
            rep.add("P0", where, f"缺少必填字段 {f}")
    for f in REQUIRED_ANY:
        if p.get(f) is None:
            rep.add("P0", where, f"缺少必填字段 {f}")

    # 枚举
    for field, allowed in (("tier", TIERS), ("scale", SCALES),
                           ("status", STATUSES), ("booking", BOOKINGS)):
        v = p.get(field)
        if v is not None and v not in allowed:
            rep.add("P0", where, f"{field}={v!r} 非法，应为 {sorted(allowed)}")
    if "choice" in p and p["choice"] not in CHOICES:
        rep.add("P0", where, f"choice={p['choice']!r} 非法")

    cat_ids = {c.get("id") for c in doc.get("categories") or []}
    if p.get("category") and p["category"] not in cat_ids:
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
                    rep.add("P0", where,
                            f"坐标 ({lon}, {lat}) 落在目的地 bbox 之外——"
                            f"极可能是经纬度写反或搜错了同名地点")

    # 来源（防幻觉主闸门）
    srcs = p.get("sources")
    if not isinstance(srcs, list) or not srcs:
        rep.add("P0", where, "sources 为空——未经联网核验的景点不许进入数据集")
    else:
        for i, s in enumerate(srcs):
            if not isinstance(s, dict) or not _is_url(s.get("url")):
                rep.add("P0", where, f"sources[{i}] 缺少合法的 http(s) url")

    # 状态
    if p.get("status") and p["status"] != "open" and _blank(p.get("status_note")):
        rep.add("P0", where, f"status={p['status']} 但缺少 status_note（需说明起止时间）")

    # closed_days
    cd = p.get("closed_days")
    if cd is not None:
        if not isinstance(cd, list) or any(not isinstance(d, int) or not 1 <= d <= 7 for d in cd):
            rep.add("P0", where, "closed_days 必须是 1–7 的整数数组（1=周一），全年无休填 []")
        else:
            trip_days = _trip_weekdays(trip)
            if trip_days and trip_days.issubset(set(cd)):
                names = "".join("一二三四五六日"[d - 1] for d in sorted(trip_days))
                rep.add("P0", where,
                        f"闭馆日覆盖整个行程（行程含周{names}，该点这几天都不开）——"
                        f"不该让用户在清单里看到它可选")

    # spot 归属
    if p.get("scale") == "spot":
        parent = p.get("parent_id")
        if _blank(parent):
            rep.add("P0", where, 'scale="spot" 必须有 parent_id 指向同区域主景点')
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
    if (trip.get("local_language") and trip.get("output_language")
            and trip["local_language"] != trip["output_language"]
            and _blank(p.get("name_local"))):
        rep.add("P1", where, "当地语言与输出语言不同，应提供 name_local（且需能在地图搜到）")

    # ---- P2
    if _blank(p.get("photo_note")):
        rep.add("P2", where, "缺少 photo_note（画面描述与拍摄建议）")
    if p.get("booking") in ("required", "recommended") and _blank(p.get("booking_url")):
        rep.add("P2", where, f"booking={p['booking']} 但缺少 booking_url")
    if not p.get("images"):
        rep.add("P2", where, "没有配图")
    if isinstance(p.get("detail"), str) and 0 < len(p["detail"].strip()) < 60:
        rep.add("P2", where, f"detail 仅 {len(p['detail'].strip())} 字，偏薄")


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

    total = len(places)
    if total < 15:
        rep.add("P1", "places", f"总共只有 {total} 个景点，可能搜得不够充分（目标 35–50）")
    elif total > 60:
        rep.add("P1", "places", f"总共 {total} 个景点，超出建议上限，用户筛选负担过重")


# ---------------------------------------------------------------- links

def _head(url: str) -> tuple[str, int | str]:
    req = urllib.request.Request(url, method="HEAD", headers={"User-Agent": UA})
    try:
        with urllib.request.urlopen(req, timeout=12) as r:
            return url, r.status
    except urllib.error.HTTPError as e:
        if e.code in (403, 405, 501):  # 不少站点禁 HEAD，退回 GET 首字节
            try:
                req2 = urllib.request.Request(url, headers={"User-Agent": UA, "Range": "bytes=0-64"})
                with urllib.request.urlopen(req2, timeout=12) as r2:
                    return url, r2.status
            except Exception as e2:  # noqa: BLE001
                return url, f"{type(e2).__name__}"
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
        for url, status in ex.map(_head, targets):
            ok = isinstance(status, int) and status < 400
            if not ok:
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
