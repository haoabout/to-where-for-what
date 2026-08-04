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
    validate.check_itinerary(doc, rep)
    return rep


def with_itinerary(doc: dict, **kw) -> None:
    """给基准文档加一份两天的排程。行程日期是 09-12(周六) 与 09-13(周日)。"""
    doc["itinerary"] = [
        {"n": 1, "date": "2026-09-12", "label": "第 1 天",
         "places": [{"id": "os-001"}]},
        {"n": 2, "date": "2026-09-13", "label": "第 2 天",
         "places": [{"id": "os-002"}]},
    ]
    for k, v in kw.items():
        doc["itinerary"][0][k] = v


def hotel(doc: dict, **kw) -> dict:
    """往 places 里加一个住宿条目，返回它。"""
    h = {"id": "os-h1", "name": "梅田某酒店", "name_local": "梅田のホテル",
         "kind": "lodging",
         "area": "梅田", "coord": {"lon": 135.4980, "lat": 34.7025},
         # 住宿同样要过防幻觉闸门：AI 得真去查一下确认它存在、拿到地址
         "sources": [{"title": "官网", "url": "https://example.org/hotel"}]}
    h.update(kw)
    doc["places"].append(h)
    return h


def messages(rep: validate.Report, level: str) -> str:
    return " || ".join(m for lv, _, m in rep.items if lv == level)


PASS, FAIL = "\033[92m✓\033[0m", "\033[91m✗\033[0m"
results: list[bool] = []


def case(name: str, mutate, level: str, needle: str) -> None:
    """断言方式由 needle 决定：

        "文字"    该级别必须包含这段文字
        ""        该级别一条都不能有
        "!文字"   该级别必须**不**包含这段文字（其他告警可以有）

    空串不能走 `needle in got`——`"" in s` 恒为真，那样的用例永远通过、
    等于没写。而只想验证"某条误报消失了"时，往往不能要求整级为空——
    基准文档本身就带着「样本量太小」这类预期内的告警。"""
    doc = base_doc()
    mutate(doc)
    rep = run(doc)
    got = messages(rep, level)
    if needle == "":
        ok, expect = (not got), "一条都没有"
    elif needle.startswith("!"):
        ok, expect = (needle[1:] not in got), f"不含 {needle[1:]!r}"
    else:
        ok, expect = (needle in got), repr(needle)
    results.append(ok)
    print(f"  {PASS if ok else FAIL} {name}")
    if not ok:
        print(f"      期望 {level} {expect}")
        print(f"      实际 {level}: {got or '(无)'}")


def main() -> int:
    print("\n基准文档：零 P0，且唯一的 P1 是「样本太小」这个预期内的提醒")
    rep = run(base_doc())
    p1s = [m for _, _, m in rep.of("P1")]
    expected_p1 = [m for m in p1s if "only 2 places in total" in m]
    clean = (not rep.of("P0")) and len(p1s) == 1 and len(expected_p1) == 1
    results.append(clean)
    print(f"  {PASS if clean else FAIL} 基准文档干净（仅剩预期内的样本量提醒）")
    if not clean:
        for lv, w, m in rep.items:
            if lv in ("P0", "P1"):
                print(f"      [{lv}] {w}: {m}")

    print("\nP0 · 必须拦下的")
    case("缺 sources（防幻觉主闸门）",
         lambda d: d["places"][1].pop("sources"), "P0", "sources is empty")
    case("sources 里是非 http 的假链接",
         lambda d: d["places"][1].update(sources=[{"title": "x", "url": "内部资料"}]),
         "P0", "valid http(s) url")
    case("坐标写成数组（经纬度易写反）",
         lambda d: d["places"][1].update(coord=[135.49, 34.69]), "P0", "arrays are forbidden")
    case("经纬度写反 → 落到 bbox 外",
         lambda d: d["places"][1].update(coord={"lon": 34.6914, "lat": 135.4914}),
         "P0", "out of range")
    case("坐标搜错了同名地点（东京的点混进大阪）",
         lambda d: d["places"][1].update(coord={"lon": 139.767, "lat": 35.681}),
         "P0", "outside the destination bbox")
    case("闭馆日覆盖整个行程（周末去，但周末闭馆）",
         lambda d: d["places"][1].update(closed_days=[6, 7]), "P0", "closure days cover the whole trip")
    case("status 非 open 却不说明",
         lambda d: d["places"][1].update(status="renovating"), "P0", "status_note is missing")
    case("id 重复",
         lambda d: d["places"][1].update(id="os-001"), "P0", "duplicates")
    case("tier 枚举非法",
         lambda d: d["places"][1].update(tier="SS"), "P0", "tier='SS' is invalid")
    case("parent_id 指向不存在的景点",
         lambda d: d["places"][1].update(scale="spot", parent_id="os-999"),
         "P0", "points at a nonexistent place")
    case("category 未定义",
         lambda d: d["places"][1].update(category="ufo"), "P0", "not defined in categories")
    case("photo_index 越界",
         lambda d: d["places"][1].update(photo_index=9), "P0", "should be 1–5")
    case("bbox min/max 写反",
         lambda d: d["trip"].update(bbox=[135.65, 34.80, 135.35, 34.55]), "P0", "order is reversed")

    print("\nP1 · 应当警告的")
    case("当地语言不同却缺 name_local",
         lambda d: d["places"][1].pop("name_local"), "P1", "name_local")
    case("分类数量低于保底",
         lambda d: d["categories"].append({"id": "food", "label": "餐饮", "min": 2, "max": 5}),
         "P1", "below the minimum")
    case("两个景点坐标几乎重合",
         lambda d: d["places"][1].update(coord={"lon": 135.52591, "lat": 34.68731}),
         "P1", "possible duplicate")
    case("verified_at 过期",
         lambda d: d["trip"].update(verified_at=str(validate.date.today() - validate.timedelta(days=45))),
         "P1", "is 45 days old")

    print("\nP2 · 应当提示的")
    case("缺 photo_note",
         lambda d: d["places"][1].pop("photo_note"), "P2", "photo_note")
    case("需预约却没给预约地址",
         lambda d: d["places"][1].pop("booking_url"), "P2", "booking_url")
    case("detail 太短",
         lambda d: d["places"][1].update(detail="很好看"), "P2", "thin")
    # 端到端实测改的规则：微景点在片区里本来就没有主景点是常态（渡船口、街边小神社），
    # 强制 parent_id 会造出假的从属关系，故降级为提示。
    case("spot 没有 parent_id（应只提示，不拒绝）",
         lambda d: d["places"][1].update(scale="spot"), "P2", "renders as a standalone card")

    print("\nverify · 核实被拦截的处理")
    def blocked(d, **kw):
        p = d["places"][1]
        p["verify"] = {"state": "blocked", "note": "官网 404，专用域名连不上",
                       "check": ["营业时间", "票价"]}
        p.update(**kw)
    case("blocked 时 hours/ticket/status 允许为空",
         lambda d: blocked(d, hours=None, ticket=None, status=None), "P1", "verification blocked")
    case("blocked 但没写 note —— 必须拒绝",
         lambda d: d["places"][1].update(verify={"state": "blocked"}), "P0", "note is missing")
    case("verify.state 非法值",
         lambda d: d["places"][1].update(verify={"state": "maybe", "note": "x"}), "P0", "is invalid")
    case("verified 时不豁免必填",
         lambda d: d["places"][1].update(verify={"state": "verified"}, hours=None),
         "P0", "missing required field hours")

    print("\nitinerary · 排程结果")
    case("排程干净时不该有 P0",
         lambda d: with_itinerary(d), "P0", "")     # needle 为空串 → 只要不崩就算过
    case("排到不存在的 id",
         lambda d: (with_itinerary(d),
                    d["itinerary"][0]["places"].append({"id": "os-999"})),
         "P0", "does not exist in places")
    case("排到当天闭馆的日子（中之岛美术馆周一休，排进周一）",
         lambda d: (with_itinerary(d),
                    d["itinerary"][0].update(date="2026-09-14"),   # 周一
                    d["itinerary"][0]["places"].append({"id": "os-002"})),
         "P0", "closed that day")
    case("n 重复",
         lambda d: (with_itinerary(d), d["itinerary"][1].update(n=1)),
         "P0", "duplicates itinerary[0]")
    case("某一天空着",
         lambda d: (with_itinerary(d), d["itinerary"][1].update(places=[])),
         "P1", "has no places at all")
    case("条目不是对象（写成了裸 id）",
         lambda d: (with_itinerary(d), d["itinerary"][0].update(places=["os-001"])),
         "P0", "of the form")
    case("date 格式非法",
         lambda d: (with_itinerary(d), d["itinerary"][0].update(date="2026/09/12")),
         "P0", "date should be YYYY-MM-DD")
    case("永久关闭的地点被排进行程",
         lambda d: (with_itinerary(d),
                    d["places"][0].update(status="permanently_closed",
                                          status_note="2025 年拆除")),
         "P0", "permanently closed")
    case("同一地点排进两天却没写 note",
         lambda d: (with_itinerary(d),
                    d["itinerary"][1]["places"].append({"id": "os-001"})),
         "P2", "without a note")
    case("写了 note 就不再提示",
         lambda d: (with_itinerary(d),
                    d["itinerary"][1]["places"].append({"id": "os-001", "note": "夜景"})),
         "P2", "")
    # 酒店一天出现两次（早上出发、晚上回来）、两天共四次是常态，不该被当成误操作
    case("住宿天天出现不该被当成重复误操作",
         lambda d: (hotel(d), with_itinerary(d),
                    d["itinerary"][0]["places"].insert(0, {"id": "os-h1"}),
                    d["itinerary"][0]["places"].append({"id": "os-h1"}),
                    d["itinerary"][1]["places"].insert(0, {"id": "os-h1"}),
                    d["itinerary"][1]["places"].append({"id": "os-h1"})),
         "P2", "")
    case("住宿没被排进任何一天",
         lambda d: (hotel(d), with_itinerary(d)),
         "P1", "appears on no day")
    case("itinerary 不是数组",
         lambda d: d.update(itinerary={"n": 1}), "P0", "must be an array")

    print("\nkind · 住宿走精简必填集")
    case("住宿缺 tier/门票/闭馆日等不该报错",
         lambda d: (hotel(d), with_itinerary(d),
                    d["itinerary"][0]["places"].insert(0, {"id": "os-h1"})),
         "P0", "")
    case("住宿不该被问「闭馆日为什么是 null」",
         lambda d: (hotel(d), with_itinerary(d),
                    d["itinerary"][0]["places"].insert(0, {"id": "os-h1"})),
         "P1", "!closed_days is null")
    case("住宿仍然要有坐标",
         lambda d: (hotel(d, coord=None), with_itinerary(d),
                    d["itinerary"][0]["places"].insert(0, {"id": "os-h1"})),
         "P0", "missing required field coord")
    case("kind 非法值",
         lambda d: d["places"][1].update(kind="hostel"), "P0", "kind='hostel' is invalid")

    ok, total = sum(results), len(results)
    print(f"\n{'\033[92m' if ok == total else '\033[91m'}{ok}/{total} 通过\033[0m")
    return 0 if ok == total else 1


if __name__ == "__main__":
    sys.exit(main())
