#!/usr/bin/env python3
"""把 places.json + route.md 注入模板，生成单文件 trip.html。

用法:
    python3 build.py <trip-dir>                 # 生成 trip.html
    python3 build.py <trip-dir> --serve         # 生成并起后台服务，打印 URL 后立即返回
    python3 build.py <trip-dir> --stop          # 停掉该目录的后台服务
    python3 build.py <trip-dir> --standalone    # 只输出攻略页 guide.html（用于分享/部署）

为什么把 JSON 内联进 HTML 而不是让页面 fetch()：
    file:// 下 fetch 会被 CORS 拦死。内联后双击打开和 http 打开都能用。

为什么默认建议配 --serve：
    file:// 不发 Referer，OSM 官方瓦片会返回「Access blocked」图片（HTTP 200，
    肉眼才看得出来）。走 http://localhost 则完全合规。
    注意：保存文件的能力与协议无关（实测 file:// 下 showSaveFilePicker 同样可用），
    只取决于浏览器是不是 Chromium 系。
"""

from __future__ import annotations

import argparse
import json
import os
import re
import signal
import subprocess
import sys
import time
import webbrowser
from pathlib import Path

SKILL_ROOT = Path(__file__).resolve().parent.parent
TEMPLATE = SKILL_ROOT / "assets" / "template-trip.html"

DATA_MARK = "/*__TRIP_DATA__*/null"
ROUTE_MARK = "/*__ROUTE_HTML__*/null"
TRANSIT_MARK = "/*__TRANSIT__*/null"
BUILT_MARK = "/*__BUILT_AT__*/null"
PID_FILE = ".server.pid"


# ------------------------------------------------------------------ markdown

def md_to_html(md: str) -> str:
    """极简 Markdown → HTML。攻略正文由 AI 写在 route.md 里，只需要常用子集。

    刻意不引第三方库：skill 要能在任何只有 python3 的环境里跑。
    """
    if not md.strip():
        return ""

    lines = md.replace("\r\n", "\n").split("\n")
    out: list[str] = []
    in_ul = in_ol = False
    in_code = False
    in_table = False
    para: list[str] = []      # 累积当前段落
    quote: list[str] = []     # 累积当前引用块

    # Markdown 的段落由空行分隔，而不是由换行分隔。
    # 不做累积的话，写在同一自然段里的连续几行会被拆成好几个 <p>，正文看起来支离破碎。
    def flush_para() -> None:
        nonlocal para
        if para:
            out.append("<p>" + "".join(inline(x) for x in para) + "</p>")
            para = []

    def flush_quote() -> None:
        nonlocal quote
        if quote:
            out.append("<blockquote><p>" + "".join(inline(x) for x in quote) + "</p></blockquote>")
            quote = []

    def close_lists() -> None:
        nonlocal in_ul, in_ol, in_table
        flush_para(); flush_quote()
        if in_ul:
            out.append("</ul>"); in_ul = False
        if in_ol:
            out.append("</ol>"); in_ol = False
        if in_table:
            out.append("</tbody></table></div>"); in_table = False

    def inline(t: str) -> str:
        t = (t.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;"))
        t = re.sub(r"`([^`]+)`", r"<code>\1</code>", t)
        t = re.sub(r"\*\*([^*]+)\*\*", r"<strong>\1</strong>", t)
        t = re.sub(r"(?<!\*)\*([^*]+)\*(?!\*)", r"<em>\1</em>", t)
        t = re.sub(r"~~([^~]+)~~", r"<del>\1</del>", t)
        t = re.sub(r"\[([^\]]+)\]\(([^)\s]+)\)",
                   r'<a href="\2" target="_blank" rel="noopener">\1</a>', t)
        return t

    for raw in lines:
        line = raw.rstrip()

        if line.strip().startswith("```"):
            close_lists()
            out.append("</pre>" if in_code else "<pre>")
            in_code = not in_code
            continue
        if in_code:
            out.append(line.replace("&", "&amp;").replace("<", "&lt;"))
            continue

        if not line.strip():
            close_lists()
            continue

        # 表格
        if line.lstrip().startswith("|") and line.rstrip().endswith("|"):
            cells = [c.strip() for c in line.strip().strip("|").split("|")]
            if all(re.fullmatch(r":?-{2,}:?", c) for c in cells):
                continue  # 分隔行
            if not in_table:
                close_lists()
                out.append('<div class="table-wrap"><table><tbody>')
                in_table = True
            tag = "td"
            out.append("<tr>" + "".join(f"<{tag}>{inline(c)}</{tag}>" for c in cells) + "</tr>")
            continue
        if in_table:
            out.append("</tbody></table></div>"); in_table = False

        m = re.match(r"^(#{1,4})\s+(.*)$", line)
        if m:
            close_lists()
            lv = len(m.group(1))
            out.append(f"<h{lv}>{inline(m.group(2))}</h{lv}>")
            continue

        if re.match(r"^\s*[-*+]\s+", line):
            if not in_ul:
                close_lists(); out.append("<ul>"); in_ul = True
            out.append(f"<li>{inline(re.sub(r'^\s*[-*+]\s+', '', line))}</li>")
            continue

        if re.match(r"^\s*\d+[.)]\s+", line):
            if not in_ol:
                close_lists(); out.append("<ol>"); in_ol = True
            out.append(f"<li>{inline(re.sub(r'^\s*\d+[.)]\s+', '', line))}</li>")
            continue

        if re.match(r"^\s*>\s?", line):
            flush_para()
            quote.append(re.sub(r"^\s*>\s?", "", line))
            continue
        flush_quote()

        if re.fullmatch(r"\s*([-*_])\s*(\1\s*){2,}", line):
            close_lists(); out.append("<hr>"); continue

        # 普通正文：累积进当前段落，等空行或块级元素再吐出
        if in_ul or in_ol or in_table:
            close_lists()
        para.append(line)

    if in_code:
        out.append("</pre>")
    close_lists()
    return "\n".join(out)


# ------------------------------------------------------------------ build

def build(trip_dir: Path, standalone: bool = False) -> Path:
    places_path = trip_dir / "places.json"
    if not places_path.exists():
        sys.exit(f"找不到 {places_path}")
    if not TEMPLATE.exists():
        sys.exit(f"找不到模板 {TEMPLATE}")

    try:
        data = json.loads(places_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as e:
        sys.exit(f"places.json 解析失败: {e}")

    route_md = ""
    route_path = trip_dir / "route.md"
    if route_path.exists():
        route_md = route_path.read_text(encoding="utf-8")

    # 轨道交通图层。没有就没有——地铁层是加分项，不该阻塞出图。
    transit = None
    transit_path = trip_dir / "transit.geojson"
    if transit_path.exists():
        try:
            transit = json.loads(transit_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as e:
            print(f"  ⚠ transit.geojson 解析失败，本次不含地铁层: {e}")

    html = TEMPLATE.read_text(encoding="utf-8")
    for mark in (DATA_MARK, BUILT_MARK):
        if mark not in html:
            sys.exit(f"模板缺少占位符 {mark}")

    # </script> 出现在 JSON 字符串里会提前关闭标签；转义掉。
    data_js = json.dumps(data, ensure_ascii=False, separators=(",", ":")).replace("</", "<\\/")
    route_js = json.dumps(md_to_html(route_md), ensure_ascii=False).replace("</", "<\\/")
    transit_js = json.dumps(transit, ensure_ascii=False, separators=(",", ":")).replace("</", "<\\/")

    html = html.replace(DATA_MARK, data_js)
    html = html.replace(ROUTE_MARK, route_js)
    html = html.replace(TRANSIT_MARK, transit_js)
    html = html.replace(BUILT_MARK, json.dumps(time.strftime("%Y-%m-%d %H:%M")))
    if standalone:
        html = html.replace("__STANDALONE__", "true")
    else:
        html = html.replace("__STANDALONE__", "false")

    out = trip_dir / ("guide.html" if standalone else "trip.html")
    out.write_text(html, encoding="utf-8")

    n = len(data.get("places") or [])
    chosen = sum(1 for p in data.get("places") or [] if p.get("choice"))
    kind = "攻略页（独立分享用）" if standalone else "行程页（三视图）"
    print(f"✓ {kind}: {out}")
    print(f"  {n} 个景点，{chosen} 个已表态，{out.stat().st_size / 1024:.0f} KB"
          + ("，含攻略正文" if route_md else "，攻略正文尚未生成"))
    if transit:
        print(f"  地铁层：{len(transit.get('lines', {}).get('features') or [])} 条线路 / "
              f"{len(transit.get('stations', {}).get('features') or [])} 个车站")
    elif not standalone:
        print("  无地铁层（跑 enrich.py --transit 可生成 transit.geojson）")
    return out


# ------------------------------------------------------------------ serve

SERVER_SRC = r'''
import json, sys
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

ROOT = Path(sys.argv[2]).resolve()

class H(SimpleHTTPRequestHandler):
    """静态服务 + 一个 /__save__ 写回端点。

    为什么需要这个端点：File System Access API 在多数内置浏览器里
    「函数存在但写入被拒」（createWritable 抛 NotAllowedError），
    剪贴板也常被禁。POST 回本地服务是唯一在所有浏览器里都可靠的回传方式。
    """
    def __init__(self, *a, **k):
        super().__init__(*a, directory=str(ROOT), **k)

    def log_message(self, *a):
        pass

    def do_POST(self):
        if self.path.rstrip("/") != "/__save__":
            self.send_error(404)
            return
        try:
            n = int(self.headers.get("Content-Length") or 0)
            if n <= 0 or n > 20 * 1024 * 1024:
                raise ValueError("请求体大小异常")
            doc = json.loads(self.rfile.read(n).decode("utf-8"))
            if not isinstance(doc, dict) or "places" not in doc:
                raise ValueError("不是合法的 places.json 结构")
            # 只允许写这一个文件名，且必须落在 ROOT 内——不接受来自页面的任意路径
            target = (ROOT / "places.json").resolve()
            if ROOT not in target.parents and target.parent != ROOT:
                raise ValueError("路径越界")
            target.write_text(json.dumps(doc, ensure_ascii=False, indent=2), encoding="utf-8")
            n_choice = sum(1 for p in doc["places"] if p.get("choice"))
            body = json.dumps({"ok": True, "path": str(target), "chosen": n_choice},
                              ensure_ascii=False).encode()
            self.send_response(200)
        except Exception as e:
            body = json.dumps({"ok": False, "error": str(e)}, ensure_ascii=False).encode()
            self.send_response(400)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

# 只绑 127.0.0.1，不对局域网暴露写接口
ThreadingHTTPServer(("127.0.0.1", int(sys.argv[1])), H).serve_forever()
'''


def serve(trip_dir: Path, page: Path, port: int) -> None:
    stop(trip_dir, quiet=True)
    proc = subprocess.Popen(
        [sys.executable, "-c", SERVER_SRC, str(port), str(trip_dir)],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True)
    (trip_dir / PID_FILE).write_text(f"{proc.pid} {port}")
    time.sleep(0.8)
    if proc.poll() is not None:
        sys.exit(f"服务启动失败（端口 {port} 可能被占用），可用 --port 换一个")

    url = f"http://localhost:{port}/{page.name}"
    print(f"✓ 本地服务已启动: {url}")
    print(f"  停止: python3 build.py {trip_dir} --stop")
    print("  页面「保存筛选结果」会 POST 到 /__save__ 由本服务写回 places.json")
    print("  （走 http 还能让 OSM 官方光栅底图合规可用；矢量底图 file:// 下也能用）")
    try:
        webbrowser.open(url)
    except Exception:  # noqa: BLE001
        pass


def stop(trip_dir: Path, quiet: bool = False) -> None:
    f = trip_dir / PID_FILE
    if not f.exists():
        if not quiet:
            print("没有正在运行的服务")
        return
    try:
        pid, port = f.read_text().split()
        os.killpg(os.getpgid(int(pid)), signal.SIGTERM)
        if not quiet:
            print(f"✓ 已停止端口 {port} 上的服务")
    except (ProcessLookupError, ValueError, PermissionError):
        if not quiet:
            print("服务已不在运行")
    finally:
        f.unlink(missing_ok=True)


# ------------------------------------------------------------------ cli

def main() -> int:
    ap = argparse.ArgumentParser(description="生成行程页")
    ap.add_argument("trip_dir")
    ap.add_argument("--serve", action="store_true", help="起后台本地服务并打开浏览器")
    ap.add_argument("--stop", action="store_true", help="停掉该目录的后台服务")
    ap.add_argument("--port", type=int, default=8787)
    ap.add_argument("--standalone", action="store_true", help="只输出攻略页 guide.html")
    args = ap.parse_args()

    trip_dir = Path(args.trip_dir).resolve()
    if not trip_dir.is_dir():
        sys.exit(f"目录不存在: {trip_dir}")

    if args.stop:
        stop(trip_dir)
        return 0

    page = build(trip_dir, standalone=args.standalone)
    if args.serve:
        serve(trip_dir, page, args.port)
    else:
        print(f"  直接打开: open {page}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
