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

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "skills/medium-roam/scripts"))
import enrich  # noqa: E402

PASS, FAIL = "\033[92m✓\033[0m", "\033[91m✗\033[0m"
results: list[bool] = []

JPEG = b"\xff\xd8\xff\xe0" + b"\x00" * 32
PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 32


def jpg(tag: str) -> bytes:
    """A JPEG whose bytes are unique to `tag`. Two candidates of one place
    that carry byte-identical bodies are now deliberately collapsed into one
    (`duplicate-bytes:`), so every fixture that means "two different photos"
    has to actually serve two different photos."""
    return JPEG + tag.encode()


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
    enrich._DOMAINS.clear()
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


def rec(audit: dict, pid: str) -> dict:
    """The place's audit record — `written` is the per-place answer to "was an
    image adopted", which fill_images' return value no longer is on its own:
    since 32eedfb it counts every places.json edit, image_gallery flips
    included."""
    return audit["places"][pid]


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
    r = rec(audit, "bkk-x01")
    # 一次写图 + 一次 image_gallery 置位 = 2 处 places.json 改动。
    check("composite name reaches the GPO redirect and writes high",
          wrote == 2 and r["written"] == "https://upload.wikimedia.org/gpo-960.jpg"
          and got and got[0]["url"].endswith("gpo-960.jpg"),
          f"wrote={wrote} written={r['written']} images={got}")
    check("corroborated high lands in the glance tier and flags the gallery",
          r["review"] == "glance" and doc["places"][0].get("image_gallery") is True
          and len(r["candidates"]) == 1,
          f"review={r['review']} cands={len(r['candidates'])}")
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
    # AVIF 回归:曼谷实测 WordPress 官网以 image/avif 提供主图,不得误拒。
    avif = b"\x00\x00\x00 ftypavif" + b"\x00" * 24
    check("AVIF magic bytes recognized as an image",
          enrich.sniff_image(avif) == "avif")


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
    net.img("event.example/keyvisual.jpg", body=jpg("keyvisual"))
    net.on("en.wikipedia.org", "pageimages", urllib.parse.quote_plus("Venue Hall"),
           json_body=pageimages("Venue.jpg", "Venue Hall"))
    net.on("commons.wikimedia.org", "Venue.jpg",
           json_body=thumbinfo("https://upload.wikimedia.org/venue-960.jpg"))
    net.img("upload.wikimedia.org/venue-960.jpg", body=jpg("venue"))
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
    """Openverse 排最后:官网与 Wikipedia 候选在前;凑满上限后根本不查询。

    身份两可(同名多个 Wikidata 实体)的地点拿不到 glance 档,整条链因此
    照旧跑完 —— 这正是分档后仍需验证来源顺序的场景。"""
    net = FakeNet()
    # 两个同名实体都落在 bbox 内 → ambiguous,glance 档被否掉;只给 P373
    # 不给 P18,免得 wikidata 家族自己先把上限占满。
    net.on("wikidata.org", "wbsearchentities",
           json_body={"search": [{"id": "Q1"}, {"id": "Q2"}]})
    net.on("wikidata.org", "wbgetentities", json_body={"entities": {
        eid: {"labels": {"en": {"value": "Test Place"}}, "claims": {
            "P625": [{"mainsnak": {"datavalue": {"value": {
                "longitude": 100.5, "latitude": 13.75}}}}],
            "P373": [{"mainsnak": {"datavalue": {"value": f"Cat{eid}"}}}]}}
        for eid in ("Q1", "Q2")}})
    net.on("en.wikipedia.org", "pageimages", urllib.parse.quote_plus("Test Place"),
           json_body=pageimages("TP.jpg", "Test Place"))
    net.on("commons.wikimedia.org", "TP.jpg",
           json_body=thumbinfo("https://upload.wikimedia.org/tp-960.jpg"))
    net.img("upload.wikimedia.org/tp-960.jpg", body=jpg("tp"))
    html = ('<meta property="og:image" content="/a.jpg">'
            '<img src="/b.jpg"><img src="/c.jpg">')
    net.on("official.example", status=200, body=html.encode(), ctype="text/html")
    for f in ("a.jpg", "b.jpg", "c.jpg"):
        net.img(f"official.example/{f}", body=jpg(f))
    net.on("api.openverse.org", json_body={"results": [
        {"thumbnail": "https://ov.example/t.jpg", "creator": "x",
         "source": "flickr", "license": "by"}]})
    p = place(sources=[{"title": "官网", "url": "https://official.example/"}])
    _, audit, _ = run_pipeline([p], net, tmp)
    srcs = [c["source"] for c in cands(audit, "bkk-x01") if c["check"]["ok"]]
    check("ambiguous identity denies the glance tier",
          rec(audit, "bkk-x01")["review"] == "full",
          f"review={rec(audit, 'bkk-x01')['review']}")
    check("wikipedia and official fill the cap before openverse",
          srcs == ["wikipedia", "official-meta"], f"sources={srcs}")
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
    enrich._DOMAINS.clear()
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
    # Two GETs per *URL*, not per family: the 64KB verification and the full
    # fetch that saves the bytes. The run cache is what keeps the second
    # family from adding a third and fourth — before candidate saving existed
    # this assertion read `== 1`.
    check("the image URL is fetched once to verify and once to save",
          len(fetches) == 2, f"fetches={len(fetches)}")


def case_cap_limit(tmp: Path) -> None:
    """候选上限(MAX_CANDIDATES)生效:官网正文多图时只保留上限数量的有效候选。"""
    net = FakeNet()
    imgs = "".join(f'<img src="/p{i}.jpg">' for i in range(6))
    net.on("official.example", status=200, body=imgs.encode(), ctype="text/html")
    for i in range(6):
        net.img(f"official.example/p{i}.jpg", body=jpg(f"p{i}"))
    p = place(sources=[{"title": "官网", "url": "https://official.example/"}])
    _, audit, _ = run_pipeline([p], net, tmp)
    ok_n = sum(1 for c in cands(audit, "bkk-x01") if c["check"]["ok"])
    check(f"verified candidates capped at {enrich.MAX_CANDIDATES}",
          ok_n == enrich.MAX_CANDIDATES, f"ok={ok_n}")


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
    # 失效地点这一轮拿到了被印证的 high,于是升进 glance 档并置 image_gallery
    # ——那是 places.json 的一处改动(wrote 计入),但图本身仍归视觉复核决定。
    check("broken existing image is never auto-replaced",
          rec(audit, "bkk-a")["written"] is None
          and rec(audit, "bkk-b")["written"] is None
          and doc["places"][1]["images"][0]["url"].endswith("dead.webp")
          and wrote == 1 and doc["places"][1].get("image_gallery") is True,
          f"wrote={wrote}")


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
    net.img("upload.wikimedia.org/platform-960.jpg", body=jpg("platform"))
    net.img("upload.wikimedia.org/WH_Logo.svg.png", body=jpg("logo"))
    html = '<img src="/api/media/file/DSC06722.webp">'
    net.on("thecommons.example", status=200, body=html.encode(), ctype="text/html")
    net.img("thecommons.example/api/media/file/DSC06722.webp", body=jpg("dsc"))
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


def review_files(tmp: Path, pid: str = "") -> list[str]:
    d = tmp / enrich.REVIEW_DIR
    return sorted(f.name for f in d.glob(f"{pid}*")) if d.is_dir() else []


def case_saves_files(tmp: Path) -> None:
    """收集时把保留候选的字节存进 image-review/:文件名带扩展名且魔术字节相符,
    审计记录 file 相对路径;检查失败者无 file;满 2MB 者视为截断不存。"""
    net = FakeNet()
    hero, shot = jpg("hero"), PNG + b"shot"
    net.on("official.example", status=200, ctype="text/html",
           body=('<meta property="og:image" content="/dead.jpg">'
                 '<img src="/hero.jpg"><img src="/shot.png">').encode())
    net.on("official.example/dead.jpg", status=404)
    net.img("official.example/hero.jpg", body=hero)
    net.on("official.example/shot.png", status=200, body=shot, ctype="image/png")
    # glance 档只留一个候选,同样要存——复核 agent 判断"要不要换"时必须看得见它。
    net.on("en.wikipedia.org", "pageimages", urllib.parse.quote_plus("Glance Place"),
           json_body=pageimages("GP.jpg", "Glance Place"))
    net.on("commons.wikimedia.org", "GP.jpg",
           json_body=thumbinfo("https://upload.wikimedia.org/gp-960.jpg"))
    glance_body = jpg("glance")
    net.img("upload.wikimedia.org/gp-960.jpg", body=glance_body)
    # 正好顶到 cap:urllib 只是读满了额度,不代表图到此为止 → 不存。
    huge = JPEG + b"\x00" * (enrich.FULL_IMAGE_CAP - len(JPEG))
    net.on("en.wikipedia.org", "pageimages", urllib.parse.quote_plus("Huge Place"),
           json_body=pageimages("Huge.jpg", "Huge Place"))
    net.on("commons.wikimedia.org", "Huge.jpg",
           json_body=thumbinfo("https://upload.wikimedia.org/huge-960.jpg"))
    net.img("upload.wikimedia.org/huge-960.jpg", body=huge)
    places = [place(name_en="Official Place",
                    sources=[{"title": "官网", "url": "https://official.example/"}]),
              place(id="bkk-g1", name_en="Glance Place"),
              place(id="bkk-big", name_en="Huge Place")]
    _, audit, _ = run_pipeline(places, net, tmp)

    cs = cands(audit, "bkk-x01")
    by_url = {c["url"].rsplit("/", 1)[-1]: c for c in cs}
    saved = {}
    for key in ("hero.jpg", "shot.png"):
        c = by_url.get(key) or {}
        f = c.get("file") or ""
        saved[key] = (tmp / f).read_bytes() if f and (tmp / f).exists() else None
    check("kept candidates are saved under image-review/ with their real bytes",
          saved["hero.jpg"] == hero and saved["shot.png"] == shot
          and by_url["hero.jpg"]["file"] == f"{enrich.REVIEW_DIR}/bkk-x01_1.jpg"
          and by_url["shot.png"]["file"] == f"{enrich.REVIEW_DIR}/bkk-x01_2.png",
          f"files={[c.get('file') for c in cs]}")
    check("extension follows the sniffed format (jpeg→jpg, png→png)",
          saved["hero.jpg"].startswith(b"\xff\xd8\xff")
          and saved["shot.png"].startswith(b"\x89PNG\r\n\x1a\n"),
          f"on disk={review_files(tmp, 'bkk-x01')}")
    check("a candidate that failed its check gets no file",
          "file" not in by_url["dead.jpg"]
          and review_files(tmp, "bkk-x01") == ["bkk-x01_1.jpg", "bkk-x01_2.png"],
          f"dead={by_url['dead.jpg']}")

    g = cands(audit, "bkk-g1")
    gfile = g[0].get("file") if g else None
    check("the lone glance candidate is saved too",
          len(g) == 1 and gfile == f"{enrich.REVIEW_DIR}/bkk-g1_1.jpg"
          and (tmp / gfile).read_bytes() == glance_body,
          f"cands={g}")

    b = cands(audit, "bkk-big")
    check("a body that hits FULL_IMAGE_CAP is kept as a candidate but not saved",
          len(b) == 1 and b[0]["check"]["ok"] and "file" not in b[0]
          and review_files(tmp, "bkk-big") == [], f"cands={b}")


def case_byte_dedupe(tmp: Path) -> None:
    """两个来源给出字节完全相同的图 = 同一张照片:只落盘一次,次者以
    duplicate-bytes:<留存者 url> 记入审计且无 file。"""
    net = FakeNet()
    twin = jpg("twin")
    net.on("official.example", status=200, ctype="text/html",
           body=('<meta property="og:image" content="/twin-a.jpg">'
                 '<img src="/twin-b.jpg">').encode())
    net.img("official.example/twin-a.jpg", body=twin)
    net.img("official.example/twin-b.jpg", body=twin)
    p = place(name_en="Twin Place",
              sources=[{"title": "官网", "url": "https://official.example/"}])
    _, audit, _ = run_pipeline([p], net, tmp)
    cs = cands(audit, "bkk-x01")
    kept = [c for c in cs if c.get("file")]
    dup = [c for c in cs if not c["check"]["ok"]]
    check("byte-identical candidates collapse to a single saved file",
          len(cs) == 2 and len(kept) == 1
          and review_files(tmp, "bkk-x01") == ["bkk-x01_1.jpg"]
          and (tmp / kept[0]["file"]).read_bytes() == twin,
          f"cands={[(c['url'], c.get('file')) for c in cs]}")
    check("the duplicate is demoted with the winner's url and keeps no file",
          len(dup) == 1 and "file" not in dup[0]
          and dup[0]["check"]["reason"].startswith("duplicate-bytes:")
          and dup[0]["check"]["reason"].endswith(kept[0]["url"]),
          f"dup={dup}")


def case_cap_aware_cache(tmp: Path) -> None:
    """cap 感知缓存:64KB 检查体不得被当作全量结果喂给保存阶段;
    体在 cap 前自然结束的小图则照旧只抓一次。"""
    def responder(body: bytes, calls: list):
        def fake_urlopen(req, timeout=0):
            calls.append(req.full_url)

            class R:
                status = 200
                headers = {"Content-Type": "image/jpeg"}
                def read(self, n): return body[:n]
                def __enter__(self): return self
                def __exit__(self, *a): return False
            return R()
        return fake_urlopen

    big = JPEG + b"\x00" * 200_000
    small = jpg("small")
    big_calls, small_calls = [], []
    old_open, old_sleep = enrich.urllib.request.urlopen, enrich.time.sleep
    enrich.time.sleep = lambda *_: None
    enrich._HTTP_CACHE.clear()
    enrich._DOMAINS.clear()
    try:
        enrich.urllib.request.urlopen = responder(big, big_calls)
        r1 = enrich.http_get("https://big.example/x.jpg", cap=65_536)
        r2 = enrich.http_get("https://big.example/x.jpg", cap=enrich.FULL_IMAGE_CAP)
        enrich.urllib.request.urlopen = responder(small, small_calls)
        s1 = enrich.http_get("https://small.example/y.jpg", cap=65_536)
        s2 = enrich.http_get("https://small.example/y.jpg", cap=enrich.FULL_IMAGE_CAP)
    finally:
        enrich.urllib.request.urlopen, enrich.time.sleep = old_open, old_sleep
    check("a truncated cached body is refetched when a bigger cap is asked for",
          len(big_calls) == 2 and len(r1["body"]) == 65_536 and r2["body"] == big,
          f"calls={len(big_calls)} first={len(r1['body'])} second={len(r2['body'])}")
    check("a body that ended before its cap is complete and stays cached",
          len(small_calls) == 1 and s1["body"] == small and s2["body"] == small,
          f"calls={len(small_calls)}")


def case_files_survive_incremental(tmp: Path) -> None:
    """增量:健康跳过的地点整条记录被覆盖前,file 按 url 从旧记录继承(且文件仍在);
    --recheck 则先删本地点旧文件再写,不累积。"""
    net = FakeNet()
    net.img("cdn.example/live.jpg", body=jpg("live"))
    net.on("en.wikipedia.org", "pageimages", urllib.parse.quote_plus("Incremental Place"),
           json_body=pageimages("Inc.jpg", "Incremental Place"))
    net.on("commons.wikimedia.org", "Inc.jpg",
           json_body=thumbinfo("https://upload.wikimedia.org/inc-960.jpg"))
    net.img("upload.wikimedia.org/inc-960.jpg", body=jpg("inc"))
    p = place(id="bkk-inc", name="增量地点", name_en="Incremental Place",
              images=[{"url": "https://cdn.example/live.jpg", "credit": "c"}])
    _, audit1, _ = run_pipeline([p], net, tmp, recheck=True)
    first = review_files(tmp, "bkk-inc")
    existing1 = next(c for c in cands(audit1, "bkk-inc") if c["source"] == "existing")

    _, audit2, _ = run_pipeline([p], net, tmp)               # healthy → skipped
    c2 = cands(audit2, "bkk-inc")
    check("a healthy skipped place keeps the file its last collection saved",
          len(first) == 2 and len(c2) == 1
          and c2[0].get("file") == existing1.get("file")
          and (tmp / c2[0]["file"]).exists(),
          f"first={first} rec={c2}")

    stale = tmp / enrich.REVIEW_DIR / "bkk-inc_9.jpg"
    stale.write_bytes(jpg("stale"))
    _, audit3, _ = run_pipeline([p], net, tmp, recheck=True)
    check("--recheck replaces the place's files instead of piling them up",
          review_files(tmp, "bkk-inc") == first and not stale.exists()
          and all((tmp / c["file"]).exists()
                  for c in cands(audit3, "bkk-inc") if c.get("file")),
          f"files={review_files(tmp, 'bkk-inc')}")


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
    review_dir = sub / enrich.REVIEW_DIR
    review_dir.mkdir()
    (review_dir / "bkk-r1_1.jpg").write_bytes(jpg("r1"))
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
    check("a merged review deletes the saved candidate bytes",
          not review_dir.exists(), f"still there: {review_files(sub)}")

    # 被拒的 patch 不动目录:agent 可以原样再判一次,不必重收集。
    review_dir.mkdir()
    (review_dir / "bkk-r1_1.jpg").write_bytes(jpg("r1"))
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
          and (sub / "image-audit.json").read_bytes() == before_audit
          and review_files(sub) == ["bkk-r1_1.jpg"],
          f"rc={rc} stderr={err.getvalue()[:120]}")


def main() -> int:
    print("\nenrich.py image candidate pipeline")
    with tempfile.TemporaryDirectory() as td:
        base = Path(td)
        for i, fn in enumerate([case_composite_name, case_geo_neighbor,
                                case_og_dead_body_alive, case_get_not_head,
                                case_commons_subcat, case_event_priority,
                                case_openverse_last, case_retry_429,
                                case_cache_and_dedupe, case_cap_limit,
                                case_existing_flow, case_generic_redirect,
                                case_lows_dont_crowd, case_saves_files,
                                case_byte_dedupe, case_cap_aware_cache,
                                case_files_survive_incremental,
                                case_apply_review]):
            d = base / f"c{i}"
            d.mkdir()
            fn(d)
    n_fail = results.count(False)
    print(f"\n{len(results)} checks, {n_fail} failed")
    return 1 if n_fail else 0


if __name__ == "__main__":
    sys.exit(main())
