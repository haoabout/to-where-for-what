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

## 1.8.0 — 2026-08-13

### Changed

- **Image flow reworked into a candidate pipeline** (`enrich.py --images`).
  Instead of writing the first hit, each place now collects up to 3
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
