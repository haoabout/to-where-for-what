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
