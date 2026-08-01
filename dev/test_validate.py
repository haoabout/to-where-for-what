#!/usr/bin/env python3
"""validate.py 的回归测试：故意造坏数据，断言校验器能抓到。

    python3 dev/test_validate.py
"""
from __future__ import annotations

import copy
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "skills/travel-planner/scripts"))
import validate  # noqa: E402


def base_doc() -> dict:
    """一份最小的、应当完全通过的文档。"""
    return {
        "schema_version": 1,
        "trip": {
            "destination": "大阪", "destination_local": "大阪", "country": "JP",
            "bbox": [135.35, 34.55, 135.65, 34.80],
            "timezone": "Asia/Tokyo",
            "output_language": "zh-CN", "local_language": "ja",
            "dates": {"start": "2026-09-12", "end": "2026-09-13"},  # 周六、周日
            "days": 2, "party": "情侣 2 人", "pace": "中等",
            "generated_at": str(validate.date.today()),
            "verified_at": str(validate.date.today()),
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


def run(doc: dict) -> validate.Report:
    rep = validate.Report()
    validate.check_top_level(doc, rep)
    for i, p in enumerate(doc["places"]):
        validate.check_place(p, i, doc, rep)
    validate.check_cross(doc, rep)
    return rep


def messages(rep: validate.Report, level: str) -> str:
    return " || ".join(m for lv, _, m in rep.items if lv == level)


PASS, FAIL = "\033[92m✓\033[0m", "\033[91m✗\033[0m"
results: list[bool] = []


def case(name: str, mutate, level: str, needle: str) -> None:
    doc = base_doc()
    mutate(doc)
    rep = run(doc)
    got = messages(rep, level)
    ok = needle in got
    results.append(ok)
    print(f"  {PASS if ok else FAIL} {name}")
    if not ok:
        print(f"      期望 {level} 含 {needle!r}")
        print(f"      实际 {level}: {got or '(无)'}")


def main() -> int:
    print("\n基准文档：零 P0，且唯一的 P1 是「样本太小」这个预期内的提醒")
    rep = run(base_doc())
    p1s = [m for _, _, m in rep.of("P1")]
    expected_p1 = [m for m in p1s if "总共只有 2 个景点" in m]
    clean = (not rep.of("P0")) and len(p1s) == 1 and len(expected_p1) == 1
    results.append(clean)
    print(f"  {PASS if clean else FAIL} 基准文档干净（仅剩预期内的样本量提醒）")
    if not clean:
        for lv, w, m in rep.items:
            if lv in ("P0", "P1"):
                print(f"      [{lv}] {w}: {m}")

    print("\nP0 · 必须拦下的")
    case("缺 sources（防幻觉主闸门）",
         lambda d: d["places"][1].pop("sources"), "P0", "sources 为空")
    case("sources 里是非 http 的假链接",
         lambda d: d["places"][1].update(sources=[{"title": "x", "url": "内部资料"}]),
         "P0", "合法的 http(s) url")
    case("坐标写成数组（经纬度易写反）",
         lambda d: d["places"][1].update(coord=[135.49, 34.69]), "P0", "不许用数组")
    case("经纬度写反 → 落到 bbox 外",
         lambda d: d["places"][1].update(coord={"lon": 34.6914, "lat": 135.4914}),
         "P0", "超出合法范围")
    case("坐标搜错了同名地点（东京的点混进大阪）",
         lambda d: d["places"][1].update(coord={"lon": 139.767, "lat": 35.681}),
         "P0", "bbox 之外")
    case("闭馆日覆盖整个行程（周末去，但周末闭馆）",
         lambda d: d["places"][1].update(closed_days=[6, 7]), "P0", "闭馆日覆盖整个行程")
    case("status 非 open 却不说明",
         lambda d: d["places"][1].update(status="renovating"), "P0", "缺少 status_note")
    case("id 重复",
         lambda d: d["places"][1].update(id="os-001"), "P0", "重复")
    case("tier 枚举非法",
         lambda d: d["places"][1].update(tier="SS"), "P0", "tier='SS' 非法")
    case("parent_id 指向不存在的景点",
         lambda d: d["places"][1].update(scale="spot", parent_id="os-999"),
         "P0", "指向不存在")
    case("category 未定义",
         lambda d: d["places"][1].update(category="ufo"), "P0", "未在 categories 中定义")
    case("photo_index 越界",
         lambda d: d["places"][1].update(photo_index=9), "P0", "应在 1–5")
    case("bbox min/max 写反",
         lambda d: d["trip"].update(bbox=[135.65, 34.80, 135.35, 34.55]), "P0", "顺序反了")

    print("\nP1 · 应当警告的")
    case("当地语言不同却缺 name_local",
         lambda d: d["places"][1].pop("name_local"), "P1", "name_local")
    case("分类数量低于保底",
         lambda d: d["categories"].append({"id": "food", "label": "餐饮", "min": 2, "max": 5}),
         "P1", "低于保底")
    case("两个景点坐标几乎重合",
         lambda d: d["places"][1].update(coord={"lon": 135.52591, "lat": 34.68731}),
         "P1", "疑似重复录入")
    case("verified_at 过期",
         lambda d: d["trip"].update(verified_at=str(validate.date.today() - validate.timedelta(days=45))),
         "P1", "距今 45 天")

    print("\nP2 · 应当提示的")
    case("缺 photo_note",
         lambda d: d["places"][1].pop("photo_note"), "P2", "photo_note")
    case("需预约却没给预约地址",
         lambda d: d["places"][1].pop("booking_url"), "P2", "booking_url")
    case("detail 太短",
         lambda d: d["places"][1].update(detail="很好看"), "P2", "偏薄")
    # 端到端实测改的规则：微景点在片区里本来就没有主景点是常态（渡船口、街边小神社），
    # 强制 parent_id 会造出假的从属关系，故降级为提示。
    case("spot 没有 parent_id（应只提示，不拒绝）",
         lambda d: d["places"][1].update(scale="spot"), "P2", "将作为独立卡片显示")

    ok, total = sum(results), len(results)
    print(f"\n{'\033[92m' if ok == total else '\033[91m'}{ok}/{total} 通过\033[0m")
    return 0 if ok == total else 1


if __name__ == "__main__":
    sys.exit(main())
