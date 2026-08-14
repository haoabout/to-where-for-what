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
