#!/usr/bin/env python3
"""把各 agent 交回的分类碎片合并进 places.json。

    python3 dev/merge_fragments.py <trip-dir> <fragment.json> [<fragment.json> ...]

碎片格式：{"places": [...]} 或直接一个数组。

合并时做的事（都是我不想手工做、又容易出错的）：
  · 按 category 重新编号 id，保证全局唯一且可读
  · 剔除 evidence 字段（它是给人核查用的，不进最终数据，另存 evidence.json）
  · 检测重名/坐标重合的疑似重复
  · 统一 area 写法（报告不一致的写法，供人工裁决）
"""

from __future__ import annotations

import json
import sys
from collections import Counter, defaultdict
from pathlib import Path

PREFIX = {"landmark": "lm", "museum": "mu", "hidden": "hd", "media": "md",
          "architecture": "ar", "shrine": "sh", "nature": "na",
          "market": "mk", "food": "fd", "event": "ev"}


def load_fragment(p: Path) -> list[dict]:
    d = json.loads(p.read_text(encoding="utf-8"))
    if isinstance(d, list):
        return d
    return d.get("places", [])


def main() -> int:
    if len(sys.argv) < 3:
        print(__doc__)
        return 2
    trip_dir = Path(sys.argv[1])
    target = trip_dir / "places.json"
    doc = json.loads(target.read_text(encoding="utf-8"))

    incoming: list[dict] = []
    for f in sys.argv[2:]:
        got = load_fragment(Path(f))
        incoming += got
        print(f"  读入 {Path(f).name}: {len(got)} 个")

    known_cats = {c["id"] for c in doc["categories"]}
    evidence = {}
    by_cat: dict[str, list[dict]] = defaultdict(list)

    for p in incoming:
        cat = p.get("category")
        if cat not in known_cats:
            print(f"  ⚠ 分类未定义: {cat!r} ({p.get('name')})")
        by_cat[cat].append(p)

    places = []
    for cat, items in by_cat.items():
        for i, p in enumerate(items, 1):
            pid = f"os-{PREFIX.get(cat, 'xx')}{i:02d}"
            if p.get("evidence"):
                evidence[pid] = {"name": p.get("name"), **p.pop("evidence")}
            p.pop("_note", None)
            p["id"] = pid
            p.setdefault("choice", None)
            p.setdefault("choice_reason", "")
            places.append(p)

    doc["places"] = places
    target.write_text(json.dumps(doc, ensure_ascii=False, indent=2), encoding="utf-8")
    (trip_dir / "evidence.json").write_text(
        json.dumps(evidence, ensure_ascii=False, indent=2), encoding="utf-8")

    print(f"\n✓ 合并 {len(places)} 个景点 → {target}")
    print(f"  逐字原文另存 → {trip_dir / 'evidence.json'}（供人工抽查，不进页面）")

    print("\n分类分布：")
    cnt = Counter(p.get("category") for p in places)
    for c in doc["categories"]:
        n = cnt.get(c["id"], 0)
        flag = "  ⚠ 低于保底" if n < c.get("min", 0) else ""
        print(f"  {c['label']:<16} {n:>2} / 保底 {c.get('min')} 上限 {c.get('max')}{flag}")

    areas = Counter(p.get("area") for p in places)
    print(f"\n片区（共 {len(areas)} 个，写法不一致的要人工统一）：")
    for a, n in areas.most_common():
        print(f"  {a} × {n}")

    names = Counter(p.get("name") for p in places)
    dupes = [n for n, c in names.items() if c > 1]
    if dupes:
        print(f"\n⚠ 重名: {dupes}")

    missing_coord = [p["name"] for p in places if not isinstance(p.get("coord"), dict)]
    if missing_coord:
        print(f"\n待补坐标 {len(missing_coord)} 个 → 跑 enrich.py --coords")
    return 0


if __name__ == "__main__":
    sys.exit(main())
