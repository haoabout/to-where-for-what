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
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

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
                    if in_bbox(lon, lat, bbox):
                        hit = (lon, lat, cand.get("display_name", "")[:64], q)
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


# ------------------------------------------------------------------ cli

def main() -> int:
    ap = argparse.ArgumentParser(description="补齐 places.json 的坐标与配图")
    ap.add_argument("path")
    ap.add_argument("--coords", action="store_true")
    ap.add_argument("--images", action="store_true")
    ap.add_argument("--dry-run", action="store_true", help="只报告，不写文件")
    args = ap.parse_args()

    if not (args.coords or args.images):
        ap.error("至少指定 --coords 或 --images")

    with open(args.path, encoding="utf-8") as f:
        doc = json.load(f)

    n = 0
    if args.coords:
        n += fill_coords(doc, args.dry_run)
    if args.images:
        n += fill_images(doc, args.dry_run)

    if args.dry_run:
        print(f"\n[dry-run] 本可补齐 {n} 项，未写入文件")
    elif n:
        with open(args.path, "w", encoding="utf-8") as f:
            json.dump(doc, f, ensure_ascii=False, indent=2)
        print(f"\n✓ 已补齐 {n} 项并写回 {args.path}")
        print("  下一步：python3 validate.py <places.json> --check-links")
    else:
        print("\n没有需要补齐的内容")
    return 0


if __name__ == "__main__":
    sys.exit(main())
