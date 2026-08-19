#!/usr/bin/env python3
"""Black-box tests for build.py's local save server.

merge() and do_POST live inside build.py's SERVER_SRC string literal and run
in a detached child process — they can't be imported. So this suite tests the
real thing: build a throwaway trip dir, start the server with --serve, and
talk to it over HTTP exactly the way the page (and a hostile web page) would.

Covers the two data-chain fixes from the 2026-08 review:
- prep.checked round-trips through the patch endpoint (4-wide choices tuple),
  and a 3-wide tuple from an older page never clears it;
- the per-launch save token: missing/wrong token → 403 and the disk stays
  untouched; Origin and Content-Type depth checks; dotfiles never served.

Run: python3 dev/test_server.py
"""

import json
import random
import shutil
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
from pathlib import Path

BUILD_PY = Path(__file__).resolve().parent.parent / "skills" / "medium-roam" / "scripts" / "build.py"

results = []


def check(name, cond, detail=""):
    ok = bool(cond)
    results.append(ok)
    mark = "\033[92m✓\033[0m" if ok else "\033[91m✗\033[0m"
    print(f"  {mark} {name}" + ("" if ok else f"  {detail}"))
    return ok


def fixture(trip_dir: Path):
    doc = {
        "schema_version": 1,
        "trip": {"destination": "Testville", "country": "JP",
                 "bbox": [135.3, 34.5, 135.7, 34.8], "timezone": "Asia/Tokyo",
                 "output_language": "zh", "local_language": "ja",
                 "days": 2, "party": "solo", "pace": "normal",
                 "generated_at": "2026-08-14", "verified_at": "2026-08-14",
                 "dates": {"start": "2026-09-12", "end": "2026-09-13"}},
        "categories": [{"id": "sight", "label": "Sight"}],
        "places": [{"id": "t-001", "name": "Test Place", "kind": "attraction",
                    "category": "sight", "coord": {"lat": 34.68, "lon": 135.5},
                    "area": "Chuo", "origin": "research",
                    "sources": [{"url": "https://example.com", "note": "x"}]}],
        "itinerary": [],
    }
    (trip_dir / "places.json").write_text(
        json.dumps(doc, ensure_ascii=False, indent=2), encoding="utf-8")


def start_server(trip_dir: Path):
    """Start --serve on a random high port; one retry on collision."""
    for _ in range(2):
        port = random.randint(20000, 40000)
        r = subprocess.run(
            [sys.executable, str(BUILD_PY), str(trip_dir), "--serve",
             "--no-open", "--port", str(port)],
            capture_output=True, text=True, timeout=60)
        if r.returncode == 0:
            return port
    sys.exit(f"could not start the server:\n{r.stdout}{r.stderr}")


def wait_ready(base: str, deadline_s: float = 8.0):
    """Poll instead of trusting serve()'s fixed sleep."""
    deadline = time.time() + deadline_s
    while time.time() < deadline:
        try:
            urllib.request.urlopen(base + "/trip.html", timeout=1)
            return
        except Exception:
            time.sleep(0.1)
    sys.exit("server never became ready")


def post(base, body, ctype="application/json", origin=None):
    req = urllib.request.Request(base + "/__save__",
                                 data=json.dumps(body).encode(),
                                 headers={"Content-Type": ctype}, method="POST")
    if origin:
        req.add_header("Origin", origin)
    try:
        r = urllib.request.urlopen(req, timeout=5)
        return r.status, json.loads(r.read())
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read() or b"{}")


def get_status(base, path):
    try:
        return urllib.request.urlopen(base + path, timeout=5).status
    except urllib.error.HTTPError as e:
        return e.code


def main() -> int:
    trip_dir = Path(tempfile.mkdtemp(prefix="medium-roam-server-test-"))
    try:
        fixture(trip_dir)
        port = start_server(trip_dir)
        base = f"http://127.0.0.1:{port}"
        wait_ready(base)
        token = (trip_dir / ".server.token").read_text(encoding="utf-8").strip()
        disk = lambda: json.loads((trip_dir / "places.json").read_text(encoding="utf-8"))

        print("\ntoken injection")
        page = (trip_dir / "trip.html").read_text(encoding="utf-8")
        check("build injects the launch token into trip.html",
              f'const SAVE_TOKEN = "{token}"' in page)

        print("\nprep round-trip (4-wide choices tuple)")
        s, r = post(base, {"patch": 1, "token": token, "itinerary": [],
                           "choices": [["t-001", "yes", "", {"checked": True}]]})
        p = disk()["places"][0]
        check("checked save → 200 and prep lands on disk",
              s == 200 and p.get("prep") == {"checked": True} and p.get("choice") == "yes",
              f"status={s} place={p}")

        s, _ = post(base, {"patch": 1, "token": token, "itinerary": [],
                           "choices": [["t-001", "yes", "", None]]})
        check("null slot (unticked) → prep key removed",
              s == 200 and "prep" not in disk()["places"][0])

        post(base, {"patch": 1, "token": token, "itinerary": [],
                    "choices": [["t-001", "yes", "", {"checked": True}]]})
        s, _ = post(base, {"patch": 1, "token": token, "itinerary": [],
                           "choices": [["t-001", "maybe", ""]]})
        p = disk()["places"][0]
        check("3-wide tuple (older page) leaves prep alone",
              s == 200 and p.get("prep") == {"checked": True} and p.get("choice") == "maybe",
              f"place={p}")

        s, _ = post(base, {"patch": 1, "token": token, "itinerary": [],
                           "choices": [["t-001", "maybe", "", {"checked": "yes"}]]})
        check("non-boolean checked is treated as unticked, not stored",
              s == 200 and "prep" not in disk()["places"][0])

        print("\nitinerary leg round-trip (segment-level transport)")
        # merge() replaces the itinerary wholesale and filters entries only by
        # "does this id still exist on disk" — it does not filter entry keys.
        # The leg feature depends on exactly that, so this case nails the
        # currently-incidental behaviour down as contract.
        #
        # Why merge deliberately gets NO entry allowlist (unlike added_places'
        # stub_fields): an allowlist that forgets a key drops user data
        # silently, and the loss is invisible in the browser — the page keeps
        # showing the leg from its in-memory copy until the next reload. The
        # stub allowlist exists because stubs are new objects injected by a
        # browser; entries are the page writing back its own state, and the
        # line against invented keys is drawn in validate.py as a P2 instead,
        # where it is reported rather than executed.
        full = {"mode": "foot", "dist_m": 1840, "dur_s": 1420,
                "geometry": "abc_defgh", "sig": "t-001|t-002|135.5,34.68",
                "note": "沿河走"}
        s, _ = post(base, {"patch": 1, "token": token, "choices": [],
                           "itinerary": [{"n": 1, "date": "2026-09-12",
                                          "places": [{"id": "t-001", "leg": full}]}]})
        got = disk()["itinerary"][0]["places"][0].get("leg")
        check("a complete leg round-trips key for key",
              s == 200 and got == full, f"status={s} leg={got}")

        # sendBeacon caps a payload at 64KB; over that the page re-sends a lean
        # copy with the geometry keys deleted (deleted, not nulled — null is a
        # legal transit value). The server must accept that shape as-is.
        lean = {k: v for k, v in full.items() if k != "geometry"}
        s, _ = post(base, {"patch": 1, "token": token, "choices": [],
                           "itinerary": [{"n": 1, "date": "2026-09-12",
                                          "places": [{"id": "t-001", "leg": lean}]}]})
        got = disk()["itinerary"][0]["places"][0].get("leg")
        check("the beacon-degraded leg (no geometry key) is stored as sent",
              s == 200 and got == lean and "geometry" not in got, f"status={s} leg={got}")

        # A leg is not a reason to keep an entry the AI has since deleted:
        # the alive filter drops the whole entry, leg included.
        s, _ = post(base, {"patch": 1, "token": token, "choices": [],
                           "itinerary": [{"n": 1, "date": "2026-09-12",
                                          "places": [{"id": "gone-001", "leg": full},
                                                     {"id": "t-001"}]}]})
        kept = disk()["itinerary"][0]["places"]
        check("a leg on a deleted place is dropped with its entry",
              s == 200 and kept == [{"id": "t-001"}], f"status={s} places={kept}")

        # Not tested on purpose: a patch whose itinerary carries no leg wipes
        # the legs on disk. That is the existing wholesale-replacement
        # semantics note and booked already live under — the page always sends
        # its complete itinerary — and page and data ship from the same build,
        # so "old page meets new data" is not a reachable combination.

        print("\nsave endpoint gates")
        before = disk()
        s, r = post(base, {"patch": 1, "itinerary": [],
                           "choices": [["t-001", "no", "", None]]})
        check("missing token → 403 and disk untouched",
              s == 403 and disk() == before, f"status={s} body={r}")

        s, _ = post(base, {"patch": 1, "token": "x" * 43, "itinerary": [],
                           "choices": [["t-001", "no", "", None]]})
        check("wrong token → 403 and disk untouched",
              s == 403 and disk() == before)

        s, _ = post(base, {"patch": 1, "token": token, "choices": []},
                    ctype="text/plain")
        check("text/plain Content-Type → 400", s == 400)

        s, _ = post(base, {"patch": 1, "token": token, "choices": []},
                    origin="https://evil.example")
        check("foreign Origin → 403", s == 403)

        s, _ = post(base, {"patch": 1, "token": token, "choices": [],
                           "itinerary": []}, origin=f"http://localhost:{port}")
        check("own localhost Origin → 200", s == 200)

        print("\nstatic file server")
        for path in ("/.server.token", "/.server.pid", "/%2Eserver.token"):
            check(f"GET {path} → 404", get_status(base, path) == 404)
        check("GET /trip.html still serves", get_status(base, "/trip.html") == 200)

        print("\nlifecycle")
        subprocess.run([sys.executable, str(BUILD_PY), str(trip_dir), "--stop"],
                       capture_output=True, timeout=30)
        check("--stop removes pid and token files",
              not (trip_dir / ".server.pid").exists()
              and not (trip_dir / ".server.token").exists())
    finally:
        subprocess.run([sys.executable, str(BUILD_PY), str(trip_dir), "--stop"],
                       capture_output=True, timeout=30)
        shutil.rmtree(trip_dir, ignore_errors=True)

    ok, total = sum(results), len(results)
    print(f"\n{'\033[92m' if ok == total else '\033[91m'}{ok}/{total} passed\033[0m")
    return 0 if ok == total else 1


if __name__ == "__main__":
    sys.exit(main())
