#!/usr/bin/env python3
"""Regression tests for enrich.py's image candidate pipeline — no network.

All HTTP goes through enrich.http_get (one choke point), so most cases stub
that with a routing fake; the retry/method cases go one level deeper and stub
urllib.request.urlopen.

    python3 dev/test_enrich_images.py
"""
from __future__ import annotations

import io
import json
import sys
import tempfile
import urllib.error
import urllib.parse
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "skills/to-where-for-what/scripts"))
import enrich  # noqa: E402

PASS, FAIL = "\033[92m✓\033[0m", "\033[91m✗\033[0m"
results: list[bool] = []

JPEG = b"\xff\xd8\xff\xe0" + b"\x00" * 32
PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 32


def check(name: str, ok: bool, detail: str = "") -> None:
    results.append(ok)
    print(f"  {PASS if ok else FAIL} {name}")
    if not ok and detail:
        print(f"      {detail}")


# --------------------------------------------------------------- fake network

class FakeNet:
    """Routes URLs to canned http_get results by substring match (all
    fragments of a key must appear in the URL). Unrouted URLs 404."""

    def __init__(self):
        self.routes: list[tuple[tuple[str, ...], dict]] = []
        self.log: list[str] = []

    def on(self, *frags: str, status=200, body=b"", ctype="", json_body=None):
        if json_body is not None:
            body = json.dumps(json_body).encode()
            ctype = "application/json"
        self.routes.append((frags, {"status": status, "body": body,
                                    "ctype": ctype, "error": None}))

    def img(self, *frags: str, body=JPEG):
        self.on(*frags, status=200, body=body, ctype="image/jpeg")

    def get(self, url, accept="*/*", cap=800_000, timeout=20):
        self.log.append(url)
        # Most-specific route wins (longest matched fragments), so a broad
        # page route never swallows an image URL on the same host.
        best, score = None, -1
        for frags, res in self.routes:
            if all(f in url for f in frags):
                s = sum(len(f) for f in frags)
                if s > score:
                    best, score = res, s
        if best is not None:
            return dict(best)
        return {"status": 404, "body": b"", "ctype": "", "error": None}


def pageimages(filename: str | None, title: str, coord=None) -> dict:
    pg = {"title": title}
    if filename:
        pg["pageimage"] = filename
    if coord:
        pg["coordinates"] = [{"lon": coord[0], "lat": coord[1]}]
    return {"query": {"pages": [pg]}}


def thumbinfo(url: str) -> dict:
    return {"query": {"pages": [{"imageinfo": [{
        "thumburl": url, "descriptionurl": url + ".about",
        "extmetadata": {"Artist": {"value": "Someone"},
                        "LicenseShortName": {"value": "CC BY 4.0"}}}]}]}}


def place(**kw) -> dict:
    p = {"id": "bkk-x01", "name": "测试地点", "name_en": "Test Place",
         "category": "museum", "sources": []}
    p.update(kw)
    return p


TRIP = {"destination": "曼谷", "destination_local": "กรุงเทพ",
        "destination_en": "Bangkok", "local_language": "th",
        "bbox": [100.45, 13.65, 100.66, 13.87]}


def run_pipeline(places: list[dict], net: FakeNet, tmp: Path,
                 recheck: bool = False) -> tuple[dict, dict, int]:
    doc = {"schema_version": 1, "trip": dict(TRIP), "places": places}
    path = tmp / "places.json"
    path.write_text(json.dumps(doc, ensure_ascii=False), encoding="utf-8")
    old_get, old_sleep = enrich.http_get, enrich.time.sleep
    enrich.http_get, enrich.time.sleep = net.get, lambda *_: None
    enrich._HTTP_CACHE.clear()
    enrich._DOMAIN_LAST.clear()
    try:
        out = io.StringIO()
        old_stdout, sys.stdout = sys.stdout, out
        try:
            wrote = enrich.fill_images(doc, str(path), dry=False, recheck=recheck)
        finally:
            sys.stdout = old_stdout
    finally:
        enrich.http_get, enrich.time.sleep = old_get, old_sleep
    audit = json.loads((tmp / "image-audit.json").read_text(encoding="utf-8"))
    return doc, audit, wrote


def cands(audit: dict, pid: str) -> list[dict]:
    return audit["places"][pid]["candidates"]


# -------------------------------------------------------------------- cases

def case_composite_name(tmp: Path) -> None:
    """「与/&」复合名称经变体拆分命中 General Post Office (Bangkok) 的重定向,
    成为 high 并自动写入无图地点。"""
    net = FakeNet()
    # Only the split-off segment has an article, via redirect to the GPO.
    # The redirect target's title doesn't match any name variant, so the
    # article's in-bbox coordinate is what corroborates identity.
    net.on("en.wikipedia.org", "pageimages",
           urllib.parse.quote_plus("Grand Postal Building"),
           json_body=pageimages("GPO.jpg", "General Post Office (Bangkok)",
                                coord=(100.514, 13.727)))
    net.on("commons.wikimedia.org", "GPO.jpg",
           json_body=thumbinfo("https://upload.wikimedia.org/gpo-960.jpg"))
    net.img("upload.wikimedia.org/gpo-960.jpg")
    p = place(name="大邮政大楼与 TCDC 曼谷", name_en="Grand Postal Building & TCDC Bangkok")
    doc, audit, wrote = run_pipeline([p], net, tmp)
    got = doc["places"][0].get("images") or []
    check("composite name reaches the GPO redirect and writes high",
          wrote == 1 and got and got[0]["url"].endswith("gpo-960.jpg"),
          f"wrote={wrote} images={got}")
    c = next((c for c in cands(audit, "bkk-x01") if c["source"] == "wikipedia"), None)
    check("audit records matched_title from the redirect target",
          bool(c) and c["confidence"] == "high"
          and c["matched_title"] == "General Post Office (Bangkok)",
          f"cand={c}")


def case_geo_neighbor(tmp: Path) -> None:
    """坐标偏移时更近的邻居(旧海关大楼)标题不匹配 → 只能进 low,不写入。"""
    net = FakeNet()
    net.on("en.wikipedia.org", "geosearch",
           json_body={"query": {"geosearch": [{"title": "Old Customs House", "dist": 40.2}]}})
    net.on("en.wikipedia.org", "pageimages", urllib.parse.quote_plus("Old Customs House"),
           json_body=pageimages("Customs.jpg", "Old Customs House"))
    net.on("commons.wikimedia.org", "Customs.jpg",
           json_body=thumbinfo("https://upload.wikimedia.org/customs-960.jpg"))
    net.img("upload.wikimedia.org/customs-960.jpg")
    p = place(name="某艺术空间", name_en="Some Art Space",
              coord={"lon": 100.514, "lat": 13.727})
    doc, audit, wrote = run_pipeline([p], net, tmp)
    c = next((c for c in cands(audit, "bkk-x01") if c["source"] == "wiki-geo"), None)
    check("nearest-by-distance neighbor stays low and is not written",
          wrote == 0 and not doc["places"][0].get("images")
          and bool(c) and c["confidence"] == "low",
          f"wrote={wrote} cand={c}")


def case_og_dead_body_alive(tmp: Path) -> None:
    """og:image 404 后继续扫正文,拿到正文图;官网图为 medium,不自动写入。"""
    net = FakeNet()
    html = ('<meta property="og:image" content="/dead.jpg">'
            '<img src="/hall.jpg">')
    net.on("official.example", status=200, body=html.encode(), ctype="text/html")
    net.img("official.example/hall.jpg")
    net.on("official.example/dead.jpg", status=404)
    p = place(sources=[{"title": "官网", "url": "https://official.example/"}])
    doc, audit, wrote = run_pipeline([p], net, tmp)
    cs = cands(audit, "bkk-x01")
    dead = next((c for c in cs if c["url"].endswith("dead.jpg")), None)
    body = next((c for c in cs if c["url"].endswith("hall.jpg")), None)
    check("dead og:image recorded as http:404, body image still found",
          bool(dead) and not dead["check"]["ok"] and "404" in dead["check"]["reason"]
          and bool(body) and body["check"]["ok"] and body["source"] == "official-body",
          f"dead={dead} body={body}")
    check("official images grade medium and are not auto-written",
          wrote == 0 and not doc["places"][0].get("images")
          and body and body["confidence"] == "medium")


def case_get_not_head(tmp: Path) -> None:
    """验证走真实 GET(部分服务器对 HEAD 404):urlopen 层断言方法。"""
    methods: list[str] = []

    def fake_urlopen(req, timeout=0):
        methods.append(req.get_method())

        class R:
            status = 200
            headers = {"Content-Type": "image/jpeg"}
            def read(self, n): return JPEG
            def __enter__(self): return self
            def __exit__(self, *a): return False
        return R()

    old = enrich.urllib.request.urlopen
    enrich.urllib.request.urlopen = fake_urlopen
    enrich._HTTP_CACHE.clear()
    try:
        res = enrich.check_image_url("https://head-hater.example/photo.jpg")
    finally:
        enrich.urllib.request.urlopen = old
    check("image verification uses GET, never HEAD",
          res["ok"] and methods == ["GET"], f"methods={methods} res={res}")


def case_commons_subcat(tmp: Path) -> None:
    """P373 分类只有子分类时,下探一层拿到文件。"""
    net = FakeNet()
    net.on("wikidata.org", "wbsearchentities",
           json_body={"search": [{"id": "Q1"}]})
    net.on("wikidata.org", "wbgetentities", json_body={"entities": {"Q1": {
        "labels": {"en": {"value": "Test Place"}},
        "claims": {
            "P625": [{"mainsnak": {"datavalue": {"value": {"longitude": 100.5, "latitude": 13.75}}}}],
            "P373": [{"mainsnak": {"datavalue": {"value": "TopCat"}}}]}}}})
    net.on("commons.wikimedia.org", "categorymembers", "TopCat",
           json_body={"query": {"categorymembers": [{"title": "Category:SubCat"}]}})
    net.on("commons.wikimedia.org", "categorymembers", "SubCat",
           json_body={"query": {"categorymembers": [{"title": "File:Sub.jpg"}]}})
    net.on("commons.wikimedia.org", "Sub.jpg",
           json_body=thumbinfo("https://upload.wikimedia.org/sub-960.jpg"))
    net.img("upload.wikimedia.org/sub-960.jpg")
    _, audit, _ = run_pipeline([place()], net, tmp)
    c = next((c for c in cands(audit, "bkk-x01") if c["source"] == "commons-category"), None)
    check("P373 with only subcats descends one level to a file",
          bool(c) and c["check"]["ok"] and c["confidence"] == "medium", f"cand={c}")


def case_event_priority(tmp: Path) -> None:
    """事件:官网候选排最前,且场馆的 Wikipedia 精确命中被降为 medium,
    不自动写入——展览不能被场馆外观替代。"""
    net = FakeNet()
    html = '<meta property="og:image" content="/keyvisual.jpg">'
    net.on("event.example", status=200, body=html.encode(), ctype="text/html")
    net.img("event.example/keyvisual.jpg")
    net.on("en.wikipedia.org", "pageimages", urllib.parse.quote_plus("Venue Hall"),
           json_body=pageimages("Venue.jpg", "Venue Hall"))
    net.on("commons.wikimedia.org", "Venue.jpg",
           json_body=thumbinfo("https://upload.wikimedia.org/venue-960.jpg"))
    net.img("upload.wikimedia.org/venue-960.jpg")
    p = place(name="特展 · Venue Hall", name_en="Special Show · Venue Hall",
              category="event",
              sources=[{"title": "活动页", "url": "https://event.example/"}])
    doc, audit, wrote = run_pipeline([p], net, tmp)
    cs = [c for c in cands(audit, "bkk-x01") if c["check"]["ok"]]
    check("event: official key visual is the first candidate",
          bool(cs) and cs[0]["source"] == "official-meta",
          f"order={[c['source'] for c in cs]}")
    wiki = next((c for c in cs if c["source"] == "wikipedia"), None)
    check("event: venue's exact-title hit is downgraded, nothing auto-written",
          wrote == 0 and not doc["places"][0].get("images")
          and (wiki is None or wiki["confidence"] != "high"),
          f"wrote={wrote} wiki={wiki}")


def case_openverse_last(tmp: Path) -> None:
    """Openverse 排最后:官网与 Wikipedia 候选在前;凑满 3 张后根本不查询。"""
    net = FakeNet()
    net.on("en.wikipedia.org", "pageimages", urllib.parse.quote_plus("Test Place"),
           json_body=pageimages("TP.jpg", "Test Place"))
    net.on("commons.wikimedia.org", "TP.jpg",
           json_body=thumbinfo("https://upload.wikimedia.org/tp-960.jpg"))
    net.img("upload.wikimedia.org/tp-960.jpg")
    html = ('<meta property="og:image" content="/a.jpg">'
            '<img src="/b.jpg"><img src="/c.jpg">')
    net.on("official.example", status=200, body=html.encode(), ctype="text/html")
    for f in ("a.jpg", "b.jpg", "c.jpg"):
        net.img(f"official.example/{f}")
    net.on("api.openverse.org", json_body={"results": [
        {"thumbnail": "https://ov.example/t.jpg", "creator": "x",
         "source": "flickr", "license": "by"}]})
    p = place(sources=[{"title": "官网", "url": "https://official.example/"}])
    _, audit, _ = run_pipeline([p], net, tmp)
    srcs = [c["source"] for c in cands(audit, "bkk-x01") if c["check"]["ok"]]
    check("wikipedia and official fill the cap before openverse",
          len(srcs) == 3 and "openverse" not in srcs, f"sources={srcs}")
    check("openverse not even queried once the cap is reached",
          not any("openverse" in u for u in net.log))


def case_retry_429(tmp: Path) -> None:
    """429 两次后成功;无 Retry-After 时按 1/2s 退避。"""
    calls, sleeps = [], []

    def fake_urlopen(req, timeout=0):
        calls.append(1)
        if len(calls) < 3:
            raise urllib.error.HTTPError(req.full_url, 429, "slow down", {}, None)

        class R:
            status = 200
            headers = {"Content-Type": "image/jpeg"}
            def read(self, n): return JPEG
            def __enter__(self): return self
            def __exit__(self, *a): return False
        return R()

    old_open, old_sleep = enrich.urllib.request.urlopen, enrich.time.sleep
    enrich.urllib.request.urlopen = fake_urlopen
    enrich.time.sleep = lambda s: sleeps.append(s)
    enrich._HTTP_CACHE.clear()
    enrich._DOMAIN_LAST.clear()
    try:
        res = enrich.http_get("https://throttled.example/x.jpg")
    finally:
        enrich.urllib.request.urlopen, enrich.time.sleep = old_open, old_sleep
    backoffs = [s for s in sleeps if s >= 1]
    check("429 twice then success, exponential backoff",
          res["status"] == 200 and len(calls) == 3 and backoffs == [1.0, 2.0],
          f"calls={len(calls)} sleeps={sleeps} res={res}")


def case_cache_and_dedupe(tmp: Path) -> None:
    """同一 URL 只抓一次(缓存);两族来源撞同一图只留一个候选(去重)。"""
    net = FakeNet()
    # Both the exact-title path and the search path produce the same file.
    net.on("en.wikipedia.org", "pageimages", urllib.parse.quote_plus("Test Place"),
           json_body=pageimages("Same.jpg", "Test Place"))
    net.on("en.wikipedia.org", "list=search",
           json_body={"query": {"search": [{"title": "Test Place"}]}})
    net.on("commons.wikimedia.org", "Same.jpg",
           json_body=thumbinfo("https://upload.wikimedia.org/same-960.jpg"))
    net.img("upload.wikimedia.org/same-960.jpg")
    _, audit, _ = run_pipeline([place()], net, tmp)
    urls = [c["url"] for c in cands(audit, "bkk-x01")]
    fetches = [u for u in net.log if "same-960.jpg" in u]
    check("identical URL from two families dedupes to one candidate",
          urls.count("https://upload.wikimedia.org/same-960.jpg") == 1, f"urls={urls}")
    check("the image URL is fetched exactly once (run cache)",
          len(fetches) == 1, f"fetches={len(fetches)}")


def case_cap_three(tmp: Path) -> None:
    """候选上限 3 生效:官网正文多图时只保留 3 个有效候选。"""
    net = FakeNet()
    imgs = "".join(f'<img src="/p{i}.jpg">' for i in range(6))
    net.on("official.example", status=200, body=imgs.encode(), ctype="text/html")
    for i in range(6):
        net.img(f"official.example/p{i}.jpg")
    p = place(sources=[{"title": "官网", "url": "https://official.example/"}])
    _, audit, _ = run_pipeline([p], net, tmp)
    ok_n = sum(1 for c in cands(audit, "bkk-x01") if c["check"]["ok"])
    check("verified candidates capped at 3", ok_n == 3, f"ok={ok_n}")


def case_existing_flow(tmp: Path) -> None:
    """现有图有效 → 增量跳过不重收集;现有图失效 → 触发收集但绝不自动改写。"""
    net = FakeNet()
    net.img("cdn.example/alive.jpg")
    net.on("cdn.example/dead.webp", status=404)
    net.on("en.wikipedia.org", "pageimages", urllib.parse.quote_plus("Test Place"),
           json_body=pageimages("TP.jpg", "Test Place"))
    net.on("commons.wikimedia.org", "TP.jpg",
           json_body=thumbinfo("https://upload.wikimedia.org/tp-960.jpg"))
    net.img("upload.wikimedia.org/tp-960.jpg")
    alive = place(id="bkk-a", name="有图有效", name_en="Alive",
                  images=[{"url": "https://cdn.example/alive.jpg", "credit": "c"}])
    dead = place(id="bkk-b", name="有图失效", name_en="Test Place",
                 images=[{"url": "https://cdn.example/dead.webp", "credit": "c"}])
    doc, audit, wrote = run_pipeline([alive, dead], net, tmp)
    a = cands(audit, "bkk-a")
    check("healthy existing image: recorded, no re-collection",
          len(a) == 1 and a[0]["source"] == "existing" and a[0]["check"]["ok"],
          f"cands={a}")
    b = cands(audit, "bkk-b")
    fresh = [c for c in b if c["source"] != "existing" and c["check"]["ok"]]
    check("broken existing image: failure recorded, new candidates collected",
          any(c["source"] == "existing" and not c["check"]["ok"] for c in b)
          and fresh, f"cands={[(c['source'], c['check']) for c in b]}")
    check("broken existing image is never auto-replaced",
          wrote == 0 and doc["places"][1]["images"][0]["url"].endswith("dead.webp"))


def case_generic_redirect(tmp: Path) -> None:
    """Speakerbox 回归:品牌名被重定向进普通名词条目(Loudspeaker
    enclosure,无坐标、标题不匹配)→ 只能 low,绝不自动写入。"""
    net = FakeNet()
    net.on("en.wikipedia.org", "pageimages", urllib.parse.quote_plus("Speakerbox"),
           json_body=pageimages("Speakers.JPG", "Loudspeaker enclosure"))
    net.on("commons.wikimedia.org", "Speakers.JPG",
           json_body=thumbinfo("https://upload.wikimedia.org/speakers-960.jpg"))
    net.img("upload.wikimedia.org/speakers-960.jpg")
    p = place(name="Speakerbox独立现场空间", name_en="Speakerbox")
    doc, audit, wrote = run_pipeline([p], net, tmp)
    c = next((c for c in cands(audit, "bkk-x01") if c["source"] == "wikipedia"), None)
    check("generic-noun redirect grades low and is not written",
          wrote == 0 and not doc["places"][0].get("images")
          and bool(c) and c["confidence"] == "low"
          and c["matched_title"] == "Loudspeaker enclosure",
          f"wrote={wrote} cand={c}")


def case_lows_dont_crowd(tmp: Path) -> None:
    """theCOMMONS 回归:垃圾 wiki-search low 不得把官网正文图挤出上限;
    logo 文件名在所有来源都被过滤,并以 filename:negative 入审计。"""
    net = FakeNet()
    # wiki-search returns two junk articles (titles unrelated → low) plus a
    # logo file; the official page holds the real photo.
    net.on("en.wikipedia.org", "list=search",
           json_body={"query": {"search": [{"title": "Wireless House"},
                                           {"title": "Lumphini Station"}]}})
    net.on("en.wikipedia.org", "pageimages", urllib.parse.quote_plus("Wireless House"),
           json_body=pageimages("WH_Logo.svg.png", "Wireless House"))
    net.on("en.wikipedia.org", "pageimages", urllib.parse.quote_plus("Lumphini Station"),
           json_body=pageimages("Platform.jpg", "Lumphini Station"))
    net.on("commons.wikimedia.org", "WH_Logo.svg.png",
           json_body=thumbinfo("https://upload.wikimedia.org/WH_Logo.svg.png"))
    net.on("commons.wikimedia.org", "Platform.jpg",
           json_body=thumbinfo("https://upload.wikimedia.org/platform-960.jpg"))
    net.img("upload.wikimedia.org/platform-960.jpg")
    net.img("upload.wikimedia.org/WH_Logo.svg.png")
    html = '<img src="/api/media/file/DSC06722.webp">'
    net.on("thecommons.example", status=200, body=html.encode(), ctype="text/html")
    net.img("thecommons.example/api/media/file/DSC06722.webp")
    p = place(name="theCOMMONS 测试", name_en="theCOMMONS Test",
              sources=[{"title": "官网", "url": "https://thecommons.example/"}])
    _, audit, _ = run_pipeline([p], net, tmp)
    cs = cands(audit, "bkk-x01")
    ok = [(c["source"], c["confidence"]) for c in cs if c["check"]["ok"]]
    logo = next((c for c in cs if "WH_Logo" in c["url"]), None)
    check("official body photo survives despite junk low search hits",
          ("official-body", "medium") in ok, f"ok={ok}")
    check("logo filename filtered in non-official families too",
          bool(logo) and not logo["check"]["ok"]
          and logo["check"]["reason"] == "filename:negative", f"logo={logo}")


def case_apply_review(tmp: Path) -> None:
    """--apply-image-review:合法 patch 原子合并 + verdict 写回审计;
    非法 patch 一个字节都不改。"""
    sub = tmp / "review"
    sub.mkdir()
    doc = {"schema_version": 1, "trip": dict(TRIP), "places": [
        place(id="bkk-r1", images=[{"url": "https://cdn.example/old.jpg", "credit": "c"}]),
        place(id="bkk-r2")]}
    (sub / "places.json").write_text(json.dumps(doc, ensure_ascii=False), encoding="utf-8")
    audit = {"schema_version": 1, "generated": "", "places": {
        "bkk-r1": {"name": "测试地点", "checked": "", "written": None,
                   "candidates": [
                       {"url": "https://cdn.example/old.jpg", "source": "existing",
                        "confidence": "existing", "check": {"ok": True}, "verdict": None},
                       {"url": "https://cdn.example/new.jpg", "source": "official-body",
                        "confidence": "medium", "check": {"ok": True}, "verdict": None}]}}}
    (sub / "image-audit.json").write_text(json.dumps(audit), encoding="utf-8")
    good = {"patches": [
        {"id": "bkk-r1", "images": [{"url": "https://cdn.example/new.jpg",
                                     "credit": "official.example"}]},
        {"id": "bkk-r2", "images": []}],
        "reviews": [{"id": "bkk-r1",
                     "accepted": ["https://cdn.example/new.jpg"],
                     "rejected": [{"url": "https://cdn.example/old.jpg",
                                   "reason": "shows the neighbor"}]}]}
    (sub / "patch.json").write_text(json.dumps(good), encoding="utf-8")
    rc = enrich.apply_image_review(str(sub / "places.json"), str(sub / "patch.json"))
    after = json.loads((sub / "places.json").read_text(encoding="utf-8"))
    audit2 = json.loads((sub / "image-audit.json").read_text(encoding="utf-8"))
    c_new = next(c for c in audit2["places"]["bkk-r1"]["candidates"]
                 if c["url"].endswith("new.jpg"))
    c_old = next(c for c in audit2["places"]["bkk-r1"]["candidates"]
                 if c["url"].endswith("old.jpg"))
    check("valid patch replaces images wholesale ([] keeps place imageless)",
          rc == 0 and after["places"][0]["images"][0]["url"].endswith("new.jpg")
          and after["places"][1]["images"] == [],
          f"rc={rc}")
    check("verdicts written back to the audit",
          c_new["verdict"] == "accepted" and c_old["verdict"] == "rejected"
          and c_old.get("verdict_reason") == "shows the neighbor")

    before_places = (sub / "places.json").read_bytes()
    before_audit = (sub / "image-audit.json").read_bytes()
    bad = {"patches": [{"id": "bkk-nope", "images": [{"url": "ftp://x", "credit": ""}]}]}
    (sub / "bad.json").write_text(json.dumps(bad), encoding="utf-8")
    err = io.StringIO()
    old_stderr, sys.stderr = sys.stderr, err
    try:
        rc = enrich.apply_image_review(str(sub / "places.json"), str(sub / "bad.json"))
    finally:
        sys.stderr = old_stderr
    check("invalid patch is rejected atomically — nothing changes",
          rc == 1 and (sub / "places.json").read_bytes() == before_places
          and (sub / "image-audit.json").read_bytes() == before_audit,
          f"rc={rc} stderr={err.getvalue()[:120]}")


def main() -> int:
    print("\nenrich.py image candidate pipeline")
    with tempfile.TemporaryDirectory() as td:
        base = Path(td)
        for i, fn in enumerate([case_composite_name, case_geo_neighbor,
                                case_og_dead_body_alive, case_get_not_head,
                                case_commons_subcat, case_event_priority,
                                case_openverse_last, case_retry_429,
                                case_cache_and_dedupe, case_cap_three,
                                case_existing_flow, case_generic_redirect,
                                case_lows_dont_crowd, case_apply_review]):
            d = base / f"c{i}"
            d.mkdir()
            fn(d)
    n_fail = results.count(False)
    print(f"\n{len(results)} checks, {n_fail} failed")
    return 1 if n_fail else 0


if __name__ == "__main__":
    sys.exit(main())
