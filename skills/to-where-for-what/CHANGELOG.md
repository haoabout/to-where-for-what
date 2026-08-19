# Changelog

The installed version is the `version:` field in `SKILL.md` frontmatter.
This file ships inside the skill directory so every install carries its own
history — including zip installs with no git metadata.

Bump rules:

- **MAJOR** — breaks existing user state: a `schema_version` bump, a field
  rename or semantic change in `places.json`, a `preferences.md` section
  whose meaning changed. Requires migration notes in the entry.
- **MINOR** — a sizeable new capability: a new view, a new pipeline stage,
  a reworked interaction model. Backward compatible.
- **PATCH** — everything smaller, and it is the *default* bump: fixes, copy
  edits, and small behavior improvements all land here (1.4.5-style).
  Routine work should move the third number, not the second.

> **Renumbered 2026-08-13**: the 2.x line was over-eager — by the rules
> above, nothing in it broke user state, so those releases were MINORs
> wearing MAJOR numbers. Old ↔ new: 2.1.0 = 1.2.0, 2.2.0 = 1.3.0,
> 2.3.0 = 1.4.0, 2.4.0 = 1.5.0. An install reporting 2.x is *older* than
> 1.5.0 despite the bigger number.

---

## 1.10.0 — 2026-08-19

Measured end to end on a 6-day Osaka run: **2h50m from "plan me a trip" to
the user seeing a page.** The two quality passes were most of it and both sat
in the critical path — the image agent 31.4 min (12.3 of them spent serially
re-downloading the very candidate images `enrich.py` had fetched minutes
earlier), the verify agent 38.4 min (20.4 of them a real browser loading slow
Japanese official sites one page at a time). This release fetches the bytes
once, judges them locally, and stops making the user wait for either pass.

### Changed

- **The page is delivered the moment it validates — new stage A3½.** At zero
  P0 with `build.py --serve` up, the page goes to the user as v1 instead of
  waiting behind the image and verify passes. v1 is validated, sourced data —
  the never-guess rule is intact; what's still pending is the *visual* image
  review and a fresh-eyes re-check, and neither is worth half an hour in front
  of nothing. Both agents are then spawned **together, in one announcement,
  and run in the background**: they touch disjoint data (the image agent
  reaches `images` only through `--apply-image-review`; the verify agent
  writes nothing and reports findings back), so neither can clobber the other,
  and stages B + C proceed while they work. When they return — usually while
  the user is still filtering — both are closed out in one pass: apply the
  patch, adjudicate the findings, rebuild, and send **one message saying what
  changed since v1**, or that nothing did. Not a running commentary on two
  agents. On the measured run this moves the first user-visible page from
  ~2h50m to ~35–40 min. The pre-delivery self-check no longer spawns anything;
  it confirms both passes are closed out and re-verifies whatever stage-D work
  invalidated (places added or re-timed while writing the guide were never
  seen by either agent).
- **The image agent judges saved files; downloading is banned.** The briefing
  now says: a candidate carrying `file` is read from disk with the Read tool,
  **no `curl`, no `wget`, and no refetching a URL that has a `file`** — send
  10–15 Reads in parallel per turn instead. Only an ambiguous or file-less
  `full`-tier candidate may go back to its URL, and the report has to say how
  many did. Measured on 47 places: **4.8 min against the old pass's 31.4 min**,
  with the local-file read catching one wrong image the earlier approach had
  missed. Deliberately still a single agent — it no longer occupies the user's
  wait, so splitting it would buy time nobody is waiting on, at the cost of
  place-range coordination and patch-merge races.
- **The verify agent is WebFetch-first, parallel, and capped.** Four hard
  rules ahead of the numbered checks: WebFetch first, a real browser only for
  pages that genuinely need rendering and the report must name them; fire
  independent fetches in parallel in one turn; **start no local server** —
  `preview_start`, `build.py --serve` and `http.server` are all out, opening
  the built page is the main conversation's job (the old run burned 2.8 min
  there); and a hard sampling ceiling — at most 5 places over the two
  source-spot-check items, ≤2 pages each, ~12 fetches total, with the
  pure-data checks staying offline and the staleness check touching only
  genuinely expired entries. The old run had drifted to ~15 places and 34
  navigations. Its fresh-eyes rationale, over-report bias and findings format
  are unchanged.

### Added

- **`enrich.py --images` keeps the candidate images it collects.** The check
  pass already GETs every candidate — it just discarded the bytes and left a
  URL, which is why the review agent downloaded the same pictures again. Every
  kept candidate whose check passed is now fetched once more in full and
  written under `image-review/` next to `places.json`, and its audit record
  gains an optional **`file`** — the path relative to the trip directory.
  Two-phase on purpose, so only survivors pay the transfer: the 64 KB check
  pass over the Osaka set ran 155 s and downloading everything in full ran
  410 s, and the difference is spent on the ~60 candidates that live. Bytes
  are the URL's own, unresized and undecoded. `existing` images and
  single-candidate `glance` places are saved too — the agent deciding whether
  to *replace* a photo has to be able to see it. Per place, identical bytes
  arriving from two families are stored once; the loser stays in the audit as
  `duplicate-bytes:<url of the copy that was kept>`, uncounted, in the same
  spirit as the filename filter's negatives.

### Fixed

- **A 64 KB check body could be served as if it were the whole image.**
  `_HTTP_CACHE` was keyed on URL alone, so the truncated body from the check
  pass was handed straight to any later full-size request for the same URL —
  harmless while nothing asked for full bytes, fatal the moment something did.
  Entries now record the cap they were fetched under, and a hit counts only
  when the body ended naturally before its own cap (so it is complete) or the
  cap was at least as large as what's being asked for; otherwise the caller
  refetches and overwrites. Errors and non-2xx have empty bodies and are
  complete under any cap, so dead links still cost one request, not one per
  caller.
- **The image junk filter was catching nothing.** Cross-tabbed against the
  last path segment of the Osaka run's 90 real candidates, the old
  `logo|icon|share|ogp|sprite|avatar|favicon|placeholder` pattern matched
  **0** of them while 13 URLs were plainly site furniture. The pattern gained
  exactly the measured families — `btn_*`, `ico[-_]*`, `header_facebook` /
  `header_instagram`, `spacer` — and catches all 13 with no false hits. Short
  tokens are anchored to the start of the segment and need a separator, so a
  photo whose name merely contains those letters is untouched.

### Notes for updaters

- **No schema change.** `places.json` validates byte-for-byte as before,
  `SCHEMA_VERSION` is unchanged, and `image-audit.json` stays at
  `schema_version: 1` — `file` is optional and additive, present exactly when
  bytes are on disk. It is absent for a failed check, a byte-duplicate, an
  image at or over 2 MB (a truncated photo is worse than none — the agent
  refetches that one URL), a failed second fetch, a dry run, and a
  health-skipped place with no file to inherit.
- **`image-review/` is scratch, not data.** Created lazily, one place's files
  replaced wholesale when that place is re-collected (`--recheck` refreshes
  every place), inherited across incremental runs when the file is still on
  disk, and **deleted outright once `--apply-image-review` merges a patch** —
  a rejected patch leaves it intact so the agent can retry. Deleting it by
  hand is safe: candidates without `file` simply send the agent back to the
  URL. It holds full-size bytes now (≤2 MB each, at most 2 per place), so it
  is the one directory in a trip worth not committing anywhere.
- **The user now receives the page twice.** Once as v1, mid-pipeline, with the
  pending passes stated in plain words (SKILL.md's glossary carries the
  wording), and once at final delivery with a note on what the two passes
  changed — that disclosure is now on checklist.md's must-state list. Without
  subagent capability the fallbacks are unchanged: both passes are done in the
  main conversation.
- `dev/test_enrich_images.py` 27 → 39 checks (saving and magic bytes, byte
  dedupe, the cap-aware cache at the `urlopen` level, incremental carry-over,
  and the merge's directory cleanup). Two existing assertions were rewritten
  against the new contract, with reasons: one URL now costs **two** GETs
  (verify once, save once) rather than one — the run cache's guarantee was
  always "not once per family", not "once ever" — and fixtures that shared a
  canned JPEG had to be given distinct bytes, since byte-dedupe would
  otherwise correctly call them the same photo.

---

## 1.9.0 — 2026-08-16

### Added

- **"Generate transport" — one button at the top of the day plan turns a
  visit order into actual routes.** Until now the day plan knew the order and
  nothing else: whether two points are a 300 m stroll or a 900 m walk around a
  river was invisible, and that is exactly what you want to know while
  rearranging a day. Pressing the button routes every leg in the trip through
  the FOSSGIS OSRM instances — walking under 2 km, driving above, per leg — and
  each leg becomes a row between the two stops showing time and distance, with
  a daily total under the day. Any leg can be switched to walking, driving or
  transit from a small menu on its row. Transit gets no route and no numbers:
  there is no open timetable to route against, so it keeps a dashed line and
  the note the user writes on it, which is the honest representation. Reorder a
  day and its legs go stale on the spot — grey rows, straight lines again, and
  the button offers "update transport (n legs)". Everything degrades: a failed
  leg shows ⚠ and falls back to a straight line, a total failure raises a
  toast, and nothing that worked before stops working. Measured on a 3-day
  Osaka trip: 9 legs in ~7 s; pressing the button again mid-run aborts and
  keeps what finished; "update (5 legs)" issued 4 requests because the fifth
  was transit.
- **The map draws the real path, and legs light up as you point at them.**
  Each day's line is now assembled from the routed legs rather than drawn
  point-to-point (123 and 86 coordinates on a sample where the straight version
  had 9 and 9), and hovering or tabbing a leg row glows that leg on the map.
  Route colors, arrows, dash animation and the day filter are untouched, and
  with no legs routed the line is byte-for-byte the one 1.8.6 drew.
- **`itinerary[].places[].leg` — the routed leg, stored per arriving entry.**
  `{mode, dist_m, dur_s, geometry, sig, note}`, contract in
  [data-schema.md](references/data-schema.md). **Page-written: the AI must not
  fill it in**, least of all `sig`, which is the page's own record of which two
  coordinates the numbers were computed for. Geometry rides along as an encoded
  polyline6 at roughly 310 bytes per leg (16 legs added 4,962 B to a 126 KB
  `places.json`; a 60-leg trip extrapolates to ~18 KB), which is why the
  requests ask for `overview=simplified` — `overview=full` measured 2–12 KB per
  leg, 240 KB over the same 60.

### Changed

- **A walking time the page routed is no longer an "estimate" in the guide.**
  Stage D's rule was that every walking leg gets marked "estimate", because the
  alternative was intuition. A `leg` written by the page is not intuition — a
  routing engine answered a query for those two exact coordinates, the same
  class of fact as a transit-planner result — so
  [route-design.md](references/route-design.md) now lets those numbers into the
  table unmarked, on three conditions: name OSM routing as the source, say it
  is not a timetable, and keep public transport entirely under the
  item-by-item official lookups (the page never routes transit). A leg with no
  `leg`, or one the page shows as stale, is an estimate again. The delivery
  checklist gains the matching disclosure: page numbers and timetable numbers
  sit on the same page and look alike.
- **The day plan's drag handling now counts entries, not DOM children.** Leg
  rows live between the items, so SortableJS's `newIndex` stopped meaning
  "position among places"; reorder positions are computed from the `.ditem`
  predecessors instead. The full drag matrix (11 cases) was retested before and
  after generating transport, comparing the array written back against the DOM
  order captured at drop.

### Notes for updaters

- `leg` is optional and additive: existing `places.json` files validate
  byte-for-byte as before, `SCHEMA_VERSION` is unchanged, and a page with no
  legs behaves exactly as it did in 1.8.6. The validator gained P0/P1/P2 checks
  for the new field (`dev/test_validate.py` 77 → 94 cases,
  `dev/test_server.py` 15 → 18).
- **`geometry` is a cache, not a fact.** When the browser saves on exit via
  `sendBeacon`, a payload over 64 KB is refused, so the page retries with the
  geometry keys stripped. A leg that comes back without geometry still shows
  its real time and distance and simply draws straight until the next update —
  it is a designed state, not corruption, and re-running the button heals it.
  Deleting geometry by hand is safe for the same reason.
- **The short-code channel carries no legs.** A pasted `D1 D2 …` code encodes
  the schedule only; when you rewrite `itinerary` from a code, do not drop the
  `leg` objects already on disk.
- **These numbers come from route planning, not timetables.** A duration
  answers "how long does this take", never "when does the next one leave", and
  transit is never routed at all. State this when you deliver — it is now on
  the pre-delivery disclosure list.
- **It depends on a free public service.** Routing goes to FOSSGIS's OSRM
  instances at `routing.openstreetmap.de` (no key, CORS open, works from
  `file://`), throttled to one request every 800 ms with a 12 s timeout. It can
  be slow, rate-limited or gone; every failure falls back to a straight line
  and the rest of the page is unaffected. `dev/osrm-probe.html` tells you
  whether the service or your code is at fault.

---

## 1.8.6 — 2026-08-14

### Added

- **`run: {start, end}` — a limited-run window for festivals, pop-ups and
  limited-run exhibitions.** Found on a live Osaka trip: a two-day matsuri
  (Sep 12–13) dragged onto Sep 14 raised no warning, because the conflict
  machinery only knew `status` and `closed_days` — and a two-day festival
  has no weekly closure day at all; its dates lived only in prose. The
  window is now structured: scheduling a day outside it is a P0 (same
  severity as scheduling on a closure day), a window that misses the trip
  entirely is a P1, and the page's day rows and cards say "ended on 09-13" /
  "not on until 09-20" / "on 09-13 only" in both UI languages. Outside its
  window a limited-run place isn't *shut*, it isn't *happening* — the
  wording keeps that distinction.
- **Runtime photo fallback and a "more photos" gallery.** A verified image
  that dies after delivery (two did, measured, on the Osaka run) or a place
  with no image no longer leaves a broken tile: the page searches Wikimedia
  Commons in the viewer's browser and shows a stand-in — always chipped
  "auto-searched, unverified", never disguised as a reviewed photo. Places
  the collection pass marked `image_gallery: true` additionally get a lazy,
  session-cached 4-thumb gallery in the dialog and on the front deck card —
  where the want/maybe/skip call is actually made. Events never auto-fill:
  a random venue photo under a festival is worse than no photo. Offline,
  everything degrades to a quiet "no photo" line.

### Changed

- **Image collection and visual review now tier by find-evidence, not
  uniformly.** Measured on the Osaka audit: `medium` candidates were
  rejected by the visual pass 79% of the time (eyes stay), but corroborated
  `high` hits still carried ~10% real errors — neighbor landmarks, interior
  shots, a museum's holdings instead of the museum. So: a place whose two
  identity families (Wikipedia exact, Wikidata) produce a live corroborated
  `high` keeps that one candidate and skips the five slow families
  (official-site crawling included); everything else — no `high`, every
  event, and any name resolving to several in-bbox Wikidata entities — gets
  the full scan, still capped at 2 candidates. The audit records
  `review: "glance" | "full"`; the visual pass gives glance places one
  contact-sheet look with no hand-search duty and spends its full
  discipline on the hard tier. Osaka: 28 glance / 19 full, audit candidates
  107 → 66. The ambiguity guard caught 藤田美術館 — whose Wikidata `high`
  really was a photo of its holdings — on its first run.

### Notes for updaters

- Both new fields (`run`, `image_gallery`) are optional and additive:
  existing `places.json` files validate byte-for-byte as before, and the
  template treats their absence as "no window / no gallery".
  `image-audit.json` gains a `review` key per place; its former verdict
  block is now `review_result` (nothing in the repo read it by name).

---

## 1.8.5 — 2026-08-14

### Changed

- **Image candidate collection now runs 5 places in parallel.** The 0.35s
  politeness throttle was implemented as one global queue, so every request
  waited behind every other request regardless of host. It is now what it
  always meant to be: strictly serial *per host* (a per-host lock held
  across the whole request cycle), parallel across hosts. The HTTP cache
  gained an in-flight map so a URL requested by several places at once hits
  the wire exactly once. Measured on the Osaka run (47 places,
  `--images --recheck`): 11m15s → 4m26s with a byte-identical
  `image-audit.json`. Nominatim (`--coords`) and Overpass (`--transit`)
  don't go through this path and stay serial.
- **A dead domain now costs one lesson, not one per URL.** The per-URL
  stop-loss re-paid 2 × 12s timeouts for every candidate URL on the same
  unreachable host — five official-site images on one dead domain cost two
  minutes. Two consecutive transport-layer failures (OSError only: timeouts,
  DNS, resets) now condemn the host for the rest of the process; later
  requests return `host-dead:<first error>` without touching the wire, and
  that reason lands in `image-audit.json` as usual. Any HTTP response at
  all — a 404 included — clears the streak, so a flaky moment cannot
  blacklist a live site.

### Fixed

- **Official-site images with non-ASCII filenames are fetchable again.**
  urllib raises `UnicodeEncodeError` before a single packet leaves for URLs
  whose path carries raw Japanese (glico.com's `og:image`, among five real
  losses on the Osaka run). `http_get` now percent-encodes the path and
  query up front (`%` kept safe so already-encoded URLs aren't double
  encoded), before cache and in-flight dedup, so the cache key matches what
  goes on the wire.

### Notes for updaters

- No schema, template, or contract change; `image-audit.json` output is
  identical on unchanged inputs, just produced faster. Existing
  `places.json` files validate as before.

---

## 1.8.4 — 2026-08-14

### Fixed

- **A place can no longer be "unverifiable" and "open" at the same time.**
  Measured on a stage-A comparison run: a subagent honestly flagged
  `光の教会` as unverifiable — the church's site carries no visitor
  information and its blog's last word on tours is a COVID-era suspension —
  and then wrote `status: "open"` next to that flag. The page cannot show
  the contradiction (`warnOf()` sends `status="open"` and an empty status
  down the same branch, both landing on the "unverified" chip), so it
  reached `places.json` unchallenged — and that file, not the page, is what
  stage D, the verify subagent and the exported `guide.md` all read. A
  `verify.state` of `blocked` or `partial` alongside `status: "open"` is now
  a P1; leaving `status` empty was already permitted by the same
  exemption that lets `hours` and `ticket` be empty. This is the one
  machine-checkable corner of the playbook's "never guess `status`" rule —
  the rest still rests on discipline.

---

## 1.8.3 — 2026-08-14

### Changed

- **SKILL.md slimmed from 706 lines / 35.8KB to 476 lines / 22.0KB** (body
  −40%). What went: content that was word-for-word duplicated in a reference
  the flow already requires reading at that moment (A2/Stage-D key points →
  playbook / route-design; stub completion steps → subagent-briefing +
  data-schema; pre-delivery checkboxes → checklist; subagent mechanics → the
  briefings), plus illustrative prose (worked examples, the anti-pattern
  table — every row restated a rule that stays). What stayed, compressed but
  complete: the four hard rules, the four-beat questioning method, B+C page
  operations and short-code parsing, trip-resume and stub-scan triggers, the
  model-tier section (the briefings cite it as authority), and every
  degraded-path fallback.
- **The post-trip retro flow moved to `references/retro.md`** — SKILL.md keeps
  the trigger (new trip, pre-A1, `dates.end` passed, `trip.retro` unset) and
  routes there. Cross-references in data-schema.md and research-playbook.md
  now point at retro.md directly.
- References absorbed the relocated rules a release earlier in the same day:
  lodging timing (data-schema "Lodging"), to-dos ownership (route-design),
  the ✅❌ render check and first-trip preferences offer (checklist).
- A typical new-trip start now loads ~78KB of required context
  (SKILL + playbook + schema) instead of ~91KB.

### Notes for updaters

- Documentation restructuring only — no script, schema, or template change;
  the behavior contract is unchanged and existing `places.json` files
  validate as before. A rule-by-rule traceability check and six behavioral
  scenario traces were run against the new layout before release.

---

## 1.8.2 — 2026-08-14

Data-chain hardening from the 2026-08 repository review (its P1-1, P1-3,
P1-4, P2-1): the page's own edits could silently miss the disk, the save
endpoint trusted anyone, and the validator could die on the very input it
exists to reject.

### Fixed

- **`prep.checked` now survives localhost autosave.** Ticking "I confirmed
  the verify items" wrote localStorage and fired autosave, but the patch
  never carried `prep` — the page said "saved" while `places.json` stayed
  stale, and localStorage masked the loss on the same browser. The wire
  `choices` tuple grew a 4th slot (mirroring the localStorage shape) and the
  server merges it with the page's own delete-when-false rule. A 3-wide
  tuple from a page built before 1.8.2 leaves `prep` untouched rather than
  clearing it.
- **The validator no longer crashes on malformed structure.** `trip` as an
  array died with an `AttributeError` before reporting anything; unhashable
  values in enum checks and ids raised `TypeError`. Containers are now
  type-checked before their fields are read: a wrong shape is a P0 finding,
  the rest of the document still gets checked, and any parseable JSON exits
  through the normal report path (new `check_document()` entry point).
- **`theme_hue` is a known trip field.** It's been in data-schema.md and
  required by Stage A since 1.6.0 but never entered `KNOWN_TRIP_FIELDS`, so
  every legal trip was flagged "fields outside the contract". Now accepted
  and validated as an integer 0–359 (violations are P1 — build.py falls
  back to the default palette rather than failing).

### Added

- **The save endpoint now authenticates.** Binding to 127.0.0.1 never
  stopped other websites in the same browser from firing blind cross-origin
  POSTs at localhost. Every `--serve` mints a per-launch token
  (`.server.token`, deleted on stop), build injects it into the page, and
  the page sends it in the patch body — sendBeacon can't set headers, and a
  query string could leak through logs or Referer. Wrong or missing token →
  403 and the disk is untouched; Origin allowlist and Content-Type checks
  ride along as depth; dotfiles (the token file included) are no longer
  served by the static half of the server.
- **`dev/test_server.py`** — black-box tests that build a throwaway trip and
  talk to a real `--serve` process over HTTP: prep round-trip, all the
  rejection paths, dotfile 404, stop cleanup. The server code lives in a
  string literal and can't be imported; now it's tested as what it is.
- Git tags exist again from this release on (`v1.8.1`, `v1.8.2`) so the
  updating.md flow can fetch the exact installed version as a merge base.

### Notes for updaters

- `places.json` schema unchanged — existing trips validate as before.
- A `trip.html` built before 1.8.2 has no token constant: it can still be
  viewed, but saving through a new server returns 403 until the page is
  rebuilt (`--serve` rebuilds automatically, so in practice: restart the
  server, then reload the tab).
- A browser tab kept open across a server restart holds the old token;
  saves fail with "stale page — reload it" until the tab is reloaded.

---

## 1.8.1 — 2026-08-13

### Added

- **Festivals and public holidays are now a required, named check** —
  research-playbook.md gains a destination-level section for it. Until now
  the only hook was the `event` category's one-word "seasonal", and every
  worked example under it was about museum special exhibitions; a run could
  miss a Songkran-sized event entirely and nothing in the pipeline would
  notice. The check has two halves: **what's on** (local-language calendar
  search, the tourism bureau's events page, venue news lists — English-only
  queries return the three festivals every tourist blog knows) and **what a
  public holiday does to the other 40 places** (mass closures, holiday-shifted
  closure rules, transport, surcharges, crowds).
- The **event-category subagent** now carries the check explicitly
  (subagent-briefing.md), reports its findings in its reply, and the main
  conversation writes them into `trip.note` on merge — a subagent owns only
  its own `partial-<group>.json`.
- **Stage D consumes it**: route-design.md treats an `event` place as
  date- and hour-pinned (schedule it first, like a booked slot) and puts the
  holiday consequences into "Caveats".
- **checklist.md 1-9** and a delivery line make "nothing significant on" a
  statement the user actually receives — an unchecked empty `event` category
  and a checked-and-empty one are indistinguishable in the data otherwise.

### Fixed

- **`trip.note` is finally documented** in data-schema.md. `validate.py` has
  always allowed it and SKILL.md has always used it for half-day trip shapes,
  but it was missing from the `trip` field table.

### Notes for updaters

- Documentation only — no script, schema, or template change, and `event`
  quotas stay 0–6 (the obligation added is to *look*, not to fill). Existing
  `places.json` files validate unchanged.

---

## 1.8.0 — 2026-08-13

### Changed

- **Image flow reworked into a candidate pipeline** (`enrich.py --images`).
  Instead of writing the first hit, each place now collects up to 2
  verified, deduplicated candidates across all source families (Wikipedia
  exact title + redirects → Wikidata P18 → Wikipedia search → official
  meta/body images → Commons category via P373 → geosearch → Openverse),
  graded `high`/`medium`/`low` by identity evidence. Only exact-identity
  `high` candidates are provisionally written, and only for places with no
  image; official-site images and events' venue hits cap at `medium`
  (a clean-named news photo passes any filename filter — Siam Paragon
  lesson), and geo hits whose title doesn't match the place stay `low`
  no matter how close (Old Customs House lesson).
- Every candidate is verified with a real streaming `GET` (2xx + image MIME
  + magic bytes) — og:image URLs routinely 404 (theCOMMONS `share.webp`
  lesson), and `HEAD` lies on some hosts. Network layer gains a per-run
  cache, per-domain throttling, and 429/5xx retries honoring `Retry-After`.
  Failures are recorded, not silently swallowed.
- Existing images are re-verified each run as `existing` candidates; a dead
  URL triggers fresh collection, but existing images are **never
  auto-replaced** — that decision belongs to the visual pass. Incremental
  by default; `--recheck` re-collects everywhere.

### Added

- **`image-audit.json`** next to `places.json` (own `schema_version: 1`;
  metadata and URLs only, no image bytes): every candidate with source,
  confidence, matched title, network check, and visual verdict.
- **`enrich.py --apply-image-review images-patch.json`** — validates the
  review agent's output (now `patches` + `reviews`), applies it atomically,
  and writes verdicts back into the audit. An invalid patch changes nothing.
- `dev/test_enrich_images.py` — 21 no-network regression checks for the
  pipeline.

`places.json` schema unchanged — no `schema_version` bump; existing trips
keep working. The A3 image subagent now judges pre-collected candidates
(briefing rewritten) instead of searching from scratch, and defaults to
**Sonnet** — the visual pass is a yes/no judgment loop, measured no better
on a bigger model, just slower.

Refinements landed during the Bangkok live run, same release: network
retries are asymmetric (429/5xx get 3, connection timeouts get 1 — dead
domains were stretching a run past 20 minutes), low-confidence candidates
no longer crowd higher families out of the cap, a Wikipedia exact-title hit
needs corroboration (title match or in-bbox article coordinate) before it
counts as `high` ("Speakerbox" → "Loudspeaker enclosure" lesson), and the
image checker recognizes AVIF/HEIC.

---

## 1.7.0 — 2026-08-13

### Added

- **Pre-departure to-dos** — a new auto-generated guide section derived from
  the schedule: booking-required and booking-advised visits (one row per
  visit) and places whose verification didn't complete (`verify.check`
  items). Each row has a checkbox; ticking writes back into the data and
  prints as a paper checklist. The same toggles appear in the place detail
  dialog.
- **Schema (additive, no `schema_version` bump)**: `itinerary[].places[].booked`
  (per-visit — bookings are date-bound, two scheduled visits are two
  tickets) and place-level `prep.checked`. Both are page-written; the AI
  must not pre-fill them. `validate.py` type-checks both (P0) and warns
  (P1) when departure is ≤14 days away with booking-required visits still
  unticked.
- Markdown export marks booked visits on their booking line.

---

## 1.6.0 — 2026-08-13

### Changed

- **Deck cards now carry the full detail** — the card IS the detail page
  (shared body with the dialog via `detailBodyHTML`), scrollable in place,
  so reading and deciding never leave the deck and the throw/stamp physics
  stay visible. Cards grew to 560px × up to ~860px (progress folded into
  the toolbar as a quiet `n / total`; maybe pile moved into the left wing
  under no; action buttons flattened to one band with keys beside them).
  Replaces the short-lived detail-lightbox browsing (`←/→` paging) that
  never shipped in a release.
- **Throw detection is sector-based** — one radial threshold (120px), and
  you throw toward where the pile actually sits: right cone = yes,
  down/down-left = maybe, the rest of the left half = no, straight up
  springs back. The card shrinks toward mini-card size as it travels;
  stamps are centred, hollow and big. On touch, vertical pan scrolls the
  card (maybe = button/S); the mouse keeps all four directions.
- **Rating tokens unified as literal no / maybe / yes** in every language,
  ordered no-left / maybe / yes-right everywhere (cards' pick row, filters,
  piles). Keys: A/S/D rate — in the deck and in any place-detail dialog
  (list/map open it; no advance there); Z / Backspace undo.
- `enrich.py --images` finds far more: composite display names retried as
  variants, two geo fallbacks (nearest Wikipedia article; Commons photos
  shot at the spot), official-page og:image in the chain (events try it
  first), Openverse queried in the local language. Measured on the Osaka
  trip: 25 missing → 25 candidates (verification pass still adjudicates).

### Fixed

- Transit legend collapses to a single chip row with a `+N` overflow chip;
  over-long line refs (Bangkok's airport APM) truncate with the full name
  in the tooltip.
- The disabled Guide tab now says why: instant hover/focus bubble plus a
  toast on click/tap (`aria-disabled`, so Safari and touch get it too).
- Portrait and square photos display whole on the media band's paper
  backing instead of being cover-cropped to a sliver; photo-less pile minis
  get the same paper fill and category mark.

---

## 1.5.0 — 2026-08-13

### Added

- **Subagent model tier: one tier down, confirmed once** — every subagent
  (search, image, stub completion, transit lookup, verify) now defaults to
  a model one tier below the main conversation's when the platform allows
  choosing (still vision-capable where the briefing requires it). The tier
  is the user's call, asked **once per conversation** with real model
  names — folded into the A1½ confirmation, or whatever beat precedes the
  first spawn when continuing an old trip — with same-tier and no-subagents
  as alternatives; every later spawn announces itself in one line and never
  re-asks. Platforms without model choice inherit the main model, stated in
  the same question. New SKILL.md section "Subagent model tier — confirm
  once, then announce"; all four briefings' pre-spawn steps gained a model
  item.

---

## 1.4.0 — 2026-08-13

### Added

Three more subagent delegations, same pattern as 1.3.0's image agent
(subagents produce reports or patch files; adjudication and merging stay in
the main conversation; without subagent capability the flow is unchanged):

- **Pre-delivery verify subagent** (always) — after `validate.py` hits zero
  P0, one read-only agent re-checks the web-facing checklist items (source
  spot-checks, status re-confirmation, closure/date conflicts, coordinate
  sanity, stale `verified_at`, tier inflation) with fresh eyes, returning a
  findings list. The main conversation keeps the page-render check, all fix
  decisions, and delivery. New
  [references/verify-agent-briefing.md](references/verify-agent-briefing.md).
- **P3 stub-completion subagent** (3+ stubs) — user-added map stubs are
  completed by one agent running the stage-A research pass, images included;
  it writes `partial-stubs.json`, merged by `id` preserving `origin`,
  `choice`, and schedule references. New "Variant: completing user stubs"
  section in
  [references/subagent-briefing.md](references/subagent-briefing.md).
- **Stage-D transit-lookup subagent** (a day's worth of segments or more) —
  the per-segment transit lookups (no-estimating rule unchanged) go to one
  agent; segment planning, the "better routing" judgment, and writing the
  Transport table stay in the main conversation. New "Delegate the lookups"
  section in [references/route-design.md](references/route-design.md).

---

## 1.3.0 — 2026-08-12

### Added

- **A3 image subagent** — the manual half of A3 is now split by kind of work.
  Coordinate misses stay in the main conversation (few, and the bbox judgment
  calls need trip context); image work — finding images for places the
  `enrich.py` chain missed, and visually verifying every image it filled —
  moves to a single background subagent spawned unconditionally right after
  `enrich.py --coords --images`. It runs while the main conversation fixes
  coordinates and pulls `--transit`, writes only `images-patch.json`
  (reviewed and merged by the main conversation before validation), and its
  prompt is built from the new
  [references/image-agent-briefing.md](references/image-agent-briefing.md).
  Without subagent capability the flow is unchanged — same work, same
  playbook rules, done in the main conversation.

---

## 1.2.0 — 2026-08-11

### Added

- **Swipe deck mode** — a card-deck browse mode on the places tab (a Cards/Grid
  toggle at the left of the toolbar) for first-pass triage.
  Every unrated place (not lodging, not an uncompleted user stub) is dealt as
  a card; decide by dragging (right = yes, left = no, down = maybe), arrow
  keys, or buttons, with Z/Backspace undo. Decided cards fly onto three
  scattered piles; clicking a pile opens a browse overlay (flat grid, quick
  re-assign, skip-reason chips and free text on the "no" pile only). Card
  tap / Enter opens the shared detail dialog. Rating "no" from the deck is
  deliberately silent — reasons are optional, added later in the overlay or
  the list view.
- First open of a trip with unrated places lands on the deck; the stored
  mode/view preference always wins afterwards. Sorting the last card toasts;
  the deck stays put, with browsable piles and the Cards/Grid switch at
  hand. All decisions go through the existing
  `setChoice()` path, so auto-save, localStorage, the list, the map and the
  progress tallies stay in sync; choices made in other views update the deck
  live. The standalone `guide.html` build carries no deck.

### Removed

- **Museum deep-dive and film/anime pilgrimage modules**:
  `references/museum-module.md` and `references/media-pilgrimage.md` deleted
  (unreviewed; recoverable from git history). The `media` / `museum` place
  fields left the data contract and `validate.py`'s field allowlist with
  them. The museum and media **categories stay** — such places are still
  searched, quota'd, and listed; only the specialized deep-dive treatment is
  gone.
- **`to-where-for-what-lite`**: the companion skill is removed. Its guard
  against over-triggering moved into the main skill's description — a casual
  "what's worth seeing in X" is answered directly in conversation (verified,
  with sources), and the pipeline starts only when the user asks to plan.
- Two delivery-statement items in `checklist.md`: the RTL-layout caveat and
  the Xiaohongshu/Bilibili coverage caveat.

### Added

- **Stage-A subagent briefing** (`references/subagent-briefing.md`): a
  fill-in prompt template for search subagents — they read the playbook and
  schema themselves; the template pins subagent-specific rules (own partial
  file only, no scripts, honest shortfall reporting, only search-relevant
  preference lines passed in).
- **`references/updating.md`**: the skill-update flow, extracted from
  SKILL.md; loaded only when the user asks about updating.
- Tables of contents with read-when annotations atop `data-schema.md` and
  `research-playbook.md`.

### Changed / fixed

- Command examples in references now use the `<PY>` placeholder instead of a
  hardcoded `python3`; `enrich.py`'s completion hint prints the actual
  interpreter it ran under.
- Known limitations deduplicated: `checklist.md` "Must be stated at
  delivery" is the single authoritative list; SKILL.md keeps a pointer.
- SKILL.md slimmed; trip-page cards drop their resting shadow (hover only).

### Notes for updaters

- **`schema_version` stays 1 — nothing hard-breaks.** Trips created under
  1.x that carry `media` / `museum` fields still open, build, and pass P0;
  `validate.py` now emits a P2 "outside the contract" note for them. Leaving
  the fields in place is safe; deleting them silences the note. (The trip
  page never rendered these objects — they only fed guide writing.)
- If you had installed the skill pair, delete the `to-where-for-what-lite`
  directory; nothing references it anymore.
- MAJOR because capabilities were removed and the `places[]` contract
  narrowed — update deliberately, and reread "Stage A" if you relied on the
  museum/media deep dives.

## 1.1.0 — 2026-08-08

### Added

- **Interest-aware quotas with hard floors** (research-playbook): High
  categories aim at quota Max, Low at Min; no category drops below Min unless
  explicitly "Not interested". Cross-category picks must stand on their own
  merit (no preference-flavored fillers). 2–3 wildcard slots per search —
  deliberate off-profile picks, honestly labeled in `pitch`.
- **Post-trip retro loop** (SKILL.md, "Retro on past trips"): before a new
  trip, ask once — skippably — how the most recent finished trip actually
  went. Raw feedback lands in new optional place fields `verdict` /
  `verdict_note`; `trip.retro` marks the trip as asked. Distilled conclusions
  go into a new **"Proven preferences"** section of `preferences.md`, only
  with user-confirmed wording; proven entries outrank declared weights.
- **In-passing preference capture**: durable preferences stated
  mid-conversation are proposed for `preferences.md` instead of evaporating.
- **First-delivery fill offer**: when `preferences.md` is still placeholders
  at first-trip delivery, offer a two-minute fill of the interest weights.

### Notes for updaters

- All new fields are optional; existing trip data validates unchanged.
- Behavior change to expect: the first new trip after updating may ask a
  one-time retro question about a past trip. Skipping is permanent per trip.

## 1.0.0 — baseline

Everything before versioning was introduced: the four-stage pipeline
(search → filter → schedule → guide), the single-file trip page with three
views, `enrich.py` / `validate.py` / `build.py`, the preferences file, user
stubs, the verify contract, transit layer, weather, and theming.
