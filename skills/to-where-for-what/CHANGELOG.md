# Changelog

The installed version is the `version:` field in `SKILL.md` frontmatter.
This file ships inside the skill directory so every install carries its own
history — including zip installs with no git metadata.

Bump rules:

- **MAJOR** — breaks existing user state: a `schema_version` bump, a field
  rename or semantic change in `places.json`, a `preferences.md` section
  whose meaning changed. Requires migration notes in the entry.
- **MINOR** — new behavior or new optional fields, backward compatible.
- **PATCH** — fixes and copy edits, no behavior change.

---

## 2.1.0 — 2026-08-11

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
  mode/view preference always wins afterwards. Sorting the last card toasts
  and flips the places tab to the grid. All decisions go through the existing
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
