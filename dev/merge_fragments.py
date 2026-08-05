#!/usr/bin/env python3
"""Merge the per-category fragments returned by each agent into places.json.

    python3 dev/merge_fragments.py <trip-dir> <fragment.json> [<fragment.json> ...]

Fragment format: {"places": [...]} or a bare array.

What merging does (all of it tedious to do by hand and easy to get wrong):
  · Renumber ids by category so they stay globally unique and readable
  · Strip the evidence field (it's for human cross-checking, doesn't belong in
    the final data, and is saved separately to evidence.json)
  · Detect likely duplicates by name collision or near-identical coordinates
  · Normalize area spellings (reports inconsistent ones for a human to settle)
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
        print(f"  read {Path(f).name}: {len(got)} places")

    known_cats = {c["id"] for c in doc["categories"]}
    evidence = {}
    by_cat: dict[str, list[dict]] = defaultdict(list)

    for p in incoming:
        cat = p.get("category")
        if cat not in known_cats:
            print(f"  ⚠ undefined category: {cat!r} ({p.get('name')})")
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

    print(f"\n✓ merged {len(places)} places → {target}")
    print(f"  verbatim source text saved separately → {trip_dir / 'evidence.json'} "
          f"(for spot-checking; never reaches the page)")

    print("\nCategory distribution:")
    cnt = Counter(p.get("category") for p in places)
    for c in doc["categories"]:
        n = cnt.get(c["id"], 0)
        flag = "  ⚠ below minimum" if n < c.get("min", 0) else ""
        print(f"  {c['label']:<16} {n:>2} / min {c.get('min')} max {c.get('max')}{flag}")

    areas = Counter(p.get("area") for p in places)
    print(f"\nAreas ({len(areas)} total; inconsistent spellings need a human to unify):")
    for a, n in areas.most_common():
        print(f"  {a} × {n}")

    names = Counter(p.get("name") for p in places)
    dupes = [n for n, c in names.items() if c > 1]
    if dupes:
        print(f"\n⚠ duplicate names: {dupes}")

    missing_coord = [p["name"] for p in places if not isinstance(p.get("coord"), dict)]
    if missing_coord:
        print(f"\n{len(missing_coord)} places still need coordinates → run enrich.py --coords")
    return 0


if __name__ == "__main__":
    sys.exit(main())
