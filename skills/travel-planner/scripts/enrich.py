#!/usr/bin/env python3
"""给 places.json 补齐坐标与配图。

用法:
    python3 enrich.py <places.json> --coords          # 补坐标（Nominatim）
    python3 enrich.py <places.json> --images          # 补配图（Wikimedia Commons）
    python3 enrich.py <places.json> --coords --images
    python3 enrich.py <places.json> --coords --dry-run

为什么这两件事不交给模型做：
    它们是确定性的 API 调用。模型来做只会引入不确定性，而且这不是 token 大头。
    坐标写错的代价极高——经纬度取错会让景点静默落到另一个半球，页面看起来还很正常。

已编码的实测教训：
    · Nominatim 政策要求最多 1 req/s，且必须带能识别应用的 User-Agent
    · 拿到坐标后必须用 trip.bbox 校验，这是发现「搜到了同名的另一个城市」的唯一方法
    · Wikimedia 已不再按任意宽度即时生成缩略图（220/320/480/640/800/1024 全部 400，
      仅 960/1280 可用）。必须用 API 的 iiurlwidth 让它返回真实存在的档位
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

UA = "travel-planner-enrich/1.0 (https://github.com/; trip planning skill)"
NOMINATIM_QPS = 1.1          # 政策要求 ≤1 req/s，留一点余量
COMMONS_API = "https://commons.wikimedia.org/w/api.php"


def get_json(url: str, timeout: int = 25) -> dict:
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.load(r)


# ------------------------------------------------------------------ 坐标

def geocode(query: str, lang: str | None = None) -> dict | None:
    params = {"q": query, "format": "json", "limit": 3, "addressdetails": 1}
    if lang:
        params["accept-language"] = lang
    try:
        res = get_json("https://nominatim.openstreetmap.org/search?" + urllib.parse.urlencode(params))
    except Exception as e:  # noqa: BLE001
        print(f"      查询失败: {type(e).__name__}", file=sys.stderr)
        return None
    return res or None


def in_bbox(lon: float, lat: float, bbox) -> bool:
    return bool(bbox) and bbox[0] <= lon <= bbox[2] and bbox[1] <= lat <= bbox[3]


# 常见通名后缀。去掉后再比对，好让「大阪城天守閣」能匹配上「大阪城」。
_SUFFIX = (r"(天守閣|展望台|記念館|美術館|博物館|資料館|図書館|会館|神社|大社|"
           r"寺院|寺|城|公園|商店街|市場|渡船場|ビルヂング|ビル|タワー|横丁|"
           r"駅|通|筋|跡|場|館|店)+$")
_PUNCT = r"[\s·・（）()【】\[\]、,，。'\"’”—\-–~〜]"


def name_matches(names: list[str], display_name: str) -> bool:
    """景点的任一名称变体与返回结果对得上，就算匹配。

    bbox 只能拦「搜错了城市」，拦不住「搜错了同城的另一个地点」——
    实测 Nominatim 把「適塾」返回成大阪市立美術館的坐标，经纬度完全在
    大阪 bbox 内、静默通过，marker 会插到错误的地方。

    但校验太严也会误杀，实测踩过三种：
      · 「大阪城天守閣」← 返回「大阪城」        通名后缀不同
      · 「萩ノ茶屋駅」  ← 返回「萩ノ茶屋」      同上
      · 「Dotonbori (Glico Sign)」← 返回「道頓堀グリコサイン」  跨语言
    所以：拿全部名称变体逐个比、双向包含都算、并剥掉通名后缀。
    """
    # 必须先按逗号切出「地点主名」，再去标点——反过来会把逗号一起删掉，
    # 于是整串地址被当成地点名，双向包含判断彻底失效。
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
            # 核心词只能比对「地点主名」，不能比对整个地址——
            # 地址里必然含片区名，否则「中之島公園」会匹配上「大阪市立東洋陶磁美術館,
            # 中之島一丁目」这种同片区的完全无关地点。
            if len(core) >= 2 and core in head:
                return True
            if len(hcore) >= 3 and (hcore in q or hcore in core):
                return True
            # 异体字容差：靱/靭、旧字体/新字体这类在日文地名里很常见。
            # 只在长度 ≥3 且恰好差 1 个字时放行，避免误配。
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
        print("坐标：全部已就绪")
        return 0

    print(f"坐标：{len(todo)} 个待补（Nominatim，{NOMINATIM_QPS}s 间隔）")
    ok = 0
    for p in todo:
        # 当地语言名命中率最高，其次英文名，最后用户语言名
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
                        print(f"      ↷ 跳过：搜「{nm}」返回的是「{disp.split(',')[0]}」，名称对不上")
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
            print(f"  ✓ {p.get('name'):<22} {lon:.5f},{lat:.5f}  ←「{q}」 {disp}")
        else:
            print(f"  ✗ {p.get('name'):<22} 未找到 bbox 内的匹配，需人工填写")
    return ok


# ------------------------------------------------------------------ 配图

def commons_thumb(title: str, width: int = 960) -> dict | None:
    """按 File: 标题取缩略图。用 API 的 iiurlwidth，它会吸附到真实存在的档位。"""
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
    """取维基条目的主图文件名。条目主图通常是最有代表性的一张，不易张冠李戴。"""
    q = {"action": "query", "titles": title, "prop": "pageimages",
         "piprop": "name", "format": "json", "formatversion": "2"}
    try:
        d = get_json(f"https://{lang}.wikipedia.org/w/api.php?" + urllib.parse.urlencode(q))
        return d["query"]["pages"][0].get("pageimage")
    except Exception:  # noqa: BLE001
        return None


def fill_images(doc: dict, dry: bool) -> int:
    trip = doc.get("trip", {})
    langs = [l for l in (trip.get("local_language"), "en") if l]
    todo = [p for p in doc["places"] if not p.get("images")]
    if not todo:
        print("配图：全部已就绪")
        return 0

    print(f"配图：{len(todo)} 个待补（维基条目主图 → Commons API）")
    ok = 0
    for p in todo:
        found = None
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
                    break
        if found:
            if not dry:
                p["images"] = [found]
            ok += 1
            print(f"  ✓ {p.get('name'):<22} {found['url'].rsplit('/', 1)[-1][:46]}")
        else:
            print(f"  – {p.get('name'):<22} 维基无主图，留空（配图非必填）")
    return ok


# ------------------------------------------------------------------ 轨道交通

OVERPASS = "https://overpass-api.de/api/interpreter"

# 只要城市轨道，不要公交。公交线路密到会把画面糊死，而且旅行者极少按公交线规划。
# monorail / light_rail 收进来是因为大阪的南港ポートタウン線、大阪モノレール
# 这类线路在出行体验上跟地铁没区别。
RAIL_ROUTES = ("subway", "light_rail", "monorail", "tram")

# 简化容差，约 13m。城市尺度下肉眼看不出差别，但点数能降到 1/4。
RDP_EPS = 0.00012


def _rdp(pts: list[tuple[float, float]], eps: float) -> list[tuple[float, float]]:
    """Douglas-Peucker 抽稀。"""
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


# Overpass 是公共免费服务，限流和过载是常态而非异常 —— 实测连着跑两次
# 第二次就吃到 504。退避重试，不要让用户自己去猜「要不要再跑一遍」。
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
        except Exception as e:  # noqa: BLE001  超时、连接重置都值得重试
            last = e
        if i < tries - 1:
            wait = 5 * 2 ** i          # 5s, 10s, 20s
            print(f"    ({type(last).__name__}) {wait}s 后换镜像重试…", file=sys.stderr)
            time.sleep(wait)
    raise last


# OSM 里线路的 colour 缺失时的兜底色板。刻意选高区分度、且与点位配色
# （绿/琥珀/灰）不撞的颜色。用到它时会在图例里注明「非官方配色」。
FALLBACK_COLORS = ["#E5171F", "#0078BE", "#019A66", "#522886", "#EE7B1A",
                   "#E44D93", "#814721", "#00A0DE", "#7A8B1F", "#B02A8F"]


def fetch_transit(doc: dict) -> dict:
    """抓目的地范围内的轨道交通线路与车站，产出一份 GeoJSON。"""
    bbox = doc.get("trip", {}).get("bbox")
    if not bbox or len(bbox) != 4:
        sys.exit("trip.bbox 缺失或格式不对，无法确定抓取范围")
    s, w, n, e = bbox[1], bbox[0], bbox[3], bbox[2]      # Overpass 用 (南,西,北,东)
    area = f"({s},{w},{n},{e})"

    # 线路和车站合成一个请求。分两次发实测会被限流打中第二次：
    # Overpass 按 IP 分配执行槽，连发两条几乎必然吃 429/504。
    print(f"→ Overpass 查询轨道交通线路与车站 {area}")
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
        print(f"  ✗ 查询失败：{type(exc).__name__}: {exc}", file=sys.stderr)
        print("    Overpass 是公共免费服务，限流时稍后重试即可。地铁层会被跳过，"
              "其余功能不受影响。", file=sys.stderr)
        return {}

    # 同一条线的往返两个方向几何几乎一样，按 ref+colour 归并只留一份
    lines: dict[tuple, dict] = {}
    for el in data.get("elements", []):
        if el.get("type") != "relation":      # 同一个响应里还有车站节点
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

    # 兜底色必须避开已被官方色占用的那些，否则会出现两条线同色。
    # 实测大阪：阪堺電気軌道没有 colour 标签，色板第一个 #E5171F 正好
    # 撞上御堂筋線的官方红，图上完全分不出来。
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

    # 车站来自同一个响应里的 node 元素。
    #
    # 不要按站名去重。同名的多个节点**不是重复录入**，而是各条线自己的站台，
    # 物理上确实分开：实测本町有 3 个节点、最远相隔 354m（御堂筋・中央・四つ橋
    # 三条线的本町站本来就不在同一处），天王寺 2 个相隔 404m。
    # 早先按名字只留第一个，等于随机保留其中一条线的站台，另外两条线上就没点了 ——
    # 用户一眼就看出「本町连着三条线，却只有红线上有点」。
    # 152 个原始节点里有 23 个属于这种情况，占 15%。
    stations = []
    for el in data.get("elements", []):
        if el.get("type") != "node":
            continue
        t = el.get("tags", {})
        lon, lat = el.get("lon"), el.get("lat")
        name = t.get("name") or t.get("name:en") or ""
        if lon is None or lat is None or not name:
            continue
        # 空值直接不写这个键。写成 "" 的话，页面里 MapLibre 的 coalesce
        # 会把空字符串当成有效值 —— 实测 129 个站名里有 120 个的 name:zh 是空串，
        # 结果站名标签全渲染成空白，图上什么都看不见。
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

    print(f"  线路 {len(feats)} 条、车站 {len(stations)} 个；坐标点简化后 {kept_pts}")
    if no_colour:
        print(f"  ⚠ 其中 {no_colour} 条线 OSM 里没有 colour 标签，已用兜底色板，"
              f"图例会注明「非官方配色」")
    for f in sorted(feats, key=lambda f: f["properties"]["ref"]):
        p = f["properties"]
        print(f"    {p['ref']:8s} {p['colour']:9s}{'（推测）' if p['guessed'] else '        '} {p['name'][:32]}")

    return {"lines": {"type": "FeatureCollection", "features": feats},
            "stations": {"type": "FeatureCollection", "features": stations}}


# ------------------------------------------------------------------ cli

def main() -> int:
    ap = argparse.ArgumentParser(description="补齐 places.json 的坐标与配图，并抓取轨道交通线路")
    ap.add_argument("path")
    ap.add_argument("--coords", action="store_true")
    ap.add_argument("--images", action="store_true")
    ap.add_argument("--transit", action="store_true",
                    help="抓取轨道交通线路与车站，写到同目录的 transit.geojson")
    ap.add_argument("--dry-run", action="store_true", help="只报告，不写文件")
    args = ap.parse_args()

    if not (args.coords or args.images or args.transit):
        ap.error("至少指定 --coords / --images / --transit 之一")

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
            # Overpass 会分别限流两条查询。若这次只拿到线路、车站空了，
            # 而磁盘上已有一份带车站的，就保留旧的 —— 部分失败绝不能让
            # 已有数据变差。（实测踩过：重试耗尽后写了个 0 车站的文件，
            # 把上一次好不容易抓到的 152 个站覆盖没了。）
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
                        print(f"  ↷ 本次没抓到{'线路' if key == 'lines' else '车站'}，"
                              f"保留已有的 {old_n} 条")
            out.write_text(json.dumps(tr, ensure_ascii=False, separators=(",", ":")),
                           encoding="utf-8")
            print(f"✓ 轨道交通已写入 {out}（{out.stat().st_size / 1024:.0f} KB，"
                  f"线路 {len(tr['lines']['features'])} 条 / "
                  f"车站 {len(tr['stations']['features'])} 个）")

    if args.dry_run:
        print(f"\n[dry-run] 本可补齐 {n} 项，未写入文件")
    elif n:
        with open(args.path, "w", encoding="utf-8") as f:
            json.dump(doc, f, ensure_ascii=False, indent=2)
        print(f"\n✓ 已补齐 {n} 项并写回 {args.path}")
        print("  下一步：python3 validate.py <places.json> --check-links")
    elif not args.transit:
        print("\n没有需要补齐的内容")
    return 0


if __name__ == "__main__":
    sys.exit(main())
