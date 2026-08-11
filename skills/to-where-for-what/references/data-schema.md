# places.json data contract

This is the core of the whole skill. **Everything the AI produces converges into
this one file**: all four views render from it, and user choices are written
back into it.

**Hard rule: never invent fields.** If you need a new field, change this file and
`scripts/validate.py` first, then use it.

## Contents

First time here, read the whole file — it is the contract. Returning for one
thing, jump straight to it:

- [Top-level structure](#top-level-structure) — incl. when `schema_version` bumps
- [`trip`](#trip) — trip metadata · [Picking `theme_hue`](#picking-theme_hue)
- [`categories`](#categories)
- [`places[]`](#places) — the bulk of the contract:
  - [Identity and classification](#identity-and-classification) — incl.
    [Lodging](#lodging-kind-lodging) and [User stubs](#user-stubs-origin-user)
    (read the latter when completing map-added places)
  - [Location](#location) · [Opening information](#opening-information-must-be-fetched-online-in-the-first-pass-of-stage-a) ·
    [Verification state](#verification-state-verify)
  - [Route-planning fuel](#route-planning-fuel) · [Content](#content) ·
    [Images and sources](#images-and-sources)
  - [User choices](#user-choices-written-back-by-the-page-the-ai-must-not-pre-fill) — page-written, never pre-fill
  - [Post-trip feedback](#post-trip-feedback-written-only-by-the-retro-flow) — only in the retro flow
- [`itinerary[]`](#itinerary-scheduling-result-written-back-by-the-page) — page-written; read before any stage-D edit
- [`ui`](#ui-ui-string-overrides--only-for-languages-other-than-enzh) — only when output language is neither en nor zh
- [Complete example](#complete-example)
- [Validation levels](#validation-levels) — when triaging `validate.py` output

---

## Top-level structure

```jsonc
{
  "schema_version": 1,
  "trip":       { ... },   // parameters of this trip
  "categories": [ ... ],   // category definitions + quotas
  "places":     [ ... ],   // attractions and lodging
  "itinerary":  [ ... ],   // optional. Scheduling result: which day, what order (written back by the page)
  "ui":         { ... }    // optional. UI string overrides for languages other than en/zh — see "ui"
}
```

### When `schema_version` bumps

**Adding optional fields never bumps it** — old data stays valid, an old
validator merely notes the unknown field, and trips keep opening on both
sides. (`verdict` and `trip.retro` were added exactly this way.)

It bumps only on a **breaking change**: a field renamed, a field's meaning or
type changed, an optional field made required. A bump makes every existing
trip fail P0 on the old number, so the change that bumps it must ship with
migration notes in the skill's `CHANGELOG.md` — and corresponds to a MAJOR
skill version. Prefer designing around additive changes; a bump is a last
resort, not a routine.

---

## `trip`

| Field | Type | Required | Notes |
|---|---|:--:|---|
| `destination` | string | ✅ | Destination, in the user's language |
| `destination_local` | string | | Local-language name; omit when same as the user's language |
| `destination_en` | string | | English name, used for exports |
| `theme_hue` | int 0–359 | | This trip's colour. See [Picking `theme_hue`](#picking-theme_hue). Omit and the page keeps its default palette |
| `country` | string | ✅ | ISO 3166-1 alpha-2, e.g. `JP` |
| `bbox` | `[minLon,minLat,maxLon,maxLat]` | ✅ | Destination bounding box, **used to validate coordinates** |
| `timezone` | string | ✅ | IANA timezone, e.g. `Asia/Tokyo` |
| `output_language` | string | ✅ | BCP-47, e.g. `zh-CN` / `en`. Determines the body-text language |
| `local_language` | string | ✅ | Local language. `name_local` is only needed when it differs from `output_language` |
| `dates` | `{start,end}` | | `YYYY-MM-DD`. Omit while dates are undecided; the weather and limited-run-event modules degrade gracefully |
| `days` | int | ✅ | Number of days |
| `party` | string | ✅ | Travel party, e.g. "couple, 2 people" |
| `pace` | string | ✅ | Stamina, e.g. "moderate; up to 12 km walking per day is fine" |
| `bases` | array | | Home bases `[{name, coord, nights}]` |
| `generated_at` | string | ✅ | `YYYY-MM-DD`, when the data was generated |
| `verified_at` | string | ✅ | `YYYY-MM-DD`, last online verification. **If >30 days before today, the page shows a staleness warning** |
| `retro` | `done`\|`skipped` | | Post-trip retro state (SKILL.md, "Retro on past trips"). Absent = not yet asked; either value = never ask again |

### Picking `theme_hue`

One number colours the four pills in the title band — destination, dates, party,
pace. `build.py` derives all four from it: lightness and chroma are fixed and
only the hue rotates, so every trip's header keeps the same contrast and only
its flavour changes. Omitting the field keeps the template's default palette,
which is exactly what `theme_hue: 334` produces.

**Take the destination's dominant material or landscape — the colour of what
you will actually be looking at for those days.** Osaka's neon and takoyaki
stalls sit around 334; Kyoto's moss and timber around 128; Nara's deer and
earthen walls around 55.

Do **not** pick from a mood word ("lively", "serene") or from a flag or a
cuisine. A palette hung on adjectives degrades into stereotype within a few
trips and keeps producing the same three colours; a material is something you
can check against a photograph.

**No hue is reserved — blue included.** Hue 198–258 used to be blocked to keep
the destination pill from reading as the navigation, on the premise that the nav
is a saturated cyan. The rebuilt title band made that false: `--pill-nav` is
`#E7E2DB` and `--pill-nav-on` is `#F6F6F6`, chroma .011 and .000, a warm grey
and a neutral grey that nothing can be mistaken for on hue. A seaside trip whose
material is deep blue keeps it, and `build.py` says nothing about it.

One limitation worth knowing: because lightness is frozen high, the system
expresses **hue only, never darkness**. "Deep, cold Hokkaido winter" comes out
as pale ice-blue, not navy.

---

## `categories`

Quota system. When a small city can't reach `min`, **never pad with fabricated
entries** — just say so honestly (validation only raises a P1 warning).

```jsonc
{ "id": "museum", "label": "Museums & galleries", "min": 3, "max": 8 }
```

Write `label` in the user's language. Default quotas: `research-playbook.md`.

---

## `places[]`

### Identity and classification

| Field | Type | Required | Notes |
|---|---|:--:|---|
| `id` | string | ✅ | Globally unique; suggested `<city-abbrev>-<3-digit-seq>`, e.g. `os-018` |
| `name` | string | ✅ | Name in **the user's language** |
| `name_local` | string | conditional | Local-language name, **must be findable on the map**. Required when `local_language ≠ output_language` |
| `name_en` | string | | English name. More reliable than the user's language when exporting to Google My Maps |
| `kind` | `attraction`\|`lodging` | | Default `attraction`. See "Lodging" below |
| `category` | string | ✅ | Must be one of `categories[].id` (lodging exempt) |
| `tier` | `S`\|`A`\|`B`\|`C` | ✅ | Recommendation tier, graded on how much detour the place is worth. Rubric: [research-playbook.md](research-playbook.md), "Grading" |
| `scale` | enum | ✅ | Visit scale, see below |
| `parent_id` | string | | A micro-spot may point at a major place in the same area; the shortlist folds it underneath. **When the area has no suitable parent, leave it empty** — forcing one fabricates a false hierarchy (observed: ferry piers and small roadside shrines are typical cases) |
| `area` | string | ✅ | District, e.g. "Nakanoshima". **Stage D clusters the route by this** — keep it consistent |
| `origin` | `user` | | Provenance marker. `user` = added manually by the user via the trip page's map search (Nominatim); see "User stubs" below. **Keep this field after the AI completes the entry** — it records where the point came from, not whether it's been completed |

`scale` values: `spot` (5–15-minute photo stop), `30min`, `1-2h`, `2-3h`, `half-day`, `full-day`

#### Lodging `kind: "lodging"`

A hotel is not an attraction: it has no tier, tickets, closure days, or photo
spots, and forcing the attraction contract onto it just coerces fake data. So it
gets a reduced required set:

| Required | Exempt |
|---|---|
| `id` `name` `area` `coord` `sources` | everything else |

`sources` is not exempt — it's the main anti-hallucination gate; a hotel must
also actually be looked up to confirm it exists and get its address.

On the page, lodging renders as a house icon in a neutral color, **doesn't take a
number in the day sequence** (attractions stay 1, 2, 3 consecutively), and
doesn't count toward the attraction-total quotas. It may appear twice in one day
(check out of A, check in at B).

#### User stubs `origin: "user"`

Points the user added ad hoc via the trip page's map search. The page only has
what the search result gave it (name + coordinates + OSM link) — none of the
research fields — **deliberately**: forcing the page to make up hours/tier would
only produce fake data. The division of labor is "the user adds stubs, the AI
completes them afterwards".

- id prefix `u-` (the page generates a base36 timestamp, e.g. `u-mjq3k8x1`),
  which never collides with the AI's `<city-abbrev>-<seq>` sequence.
- **A stub is defined as `origin=="user"` with no `tier`.** `origin` is a
  permanent provenance marker; completion is judged by whether `tier` exists.
- Until completed, the reduced required set applies (the validator agrees):

| Required | Exempt |
|---|---|
| `id` `name` `coord` `sources` | everything else (`sources` holds the OSM entry link — the name and coordinates genuinely came from it) |

- **Coordinates outside `trip.bbox` are only P1 for stubs, not P0**: spontaneous
  additions often sit just outside the bbox (adding Nara to an Osaka trip), and
  the coordinates come from OSM, not from the AI — the prior of a swap or
  mis-search is far lower.
- When the AI continues work on an existing trip, treat every
  "`origin=="user"` and no `tier`" point as a research to-do and run it through
  the research pipeline (see SKILL.md, "Completing user-added stubs"). Once
  completed, the full attraction required set applies.

### Location

```jsonc
"coord": { "lon": 135.4959, "lat": 34.6937 }
```

**Object form only — never an array.** Array form is `[lon,lat]` in
GeoJSON/MapLibre but `[lat,lng]` in Leaflet; swap them once and Osaka lands in
the Indian Ocean while everything looks fine. Named keys eliminate the bug class.

### Opening information (**must be fetched online in the first pass of stage A**)

Without these, the user's filtering is wasted — they pick favorites and then
find out the place is closed.

| Field | Type | Required | Notes |
|---|---|:--:|---|
| `hours` | string | ✅ | e.g. `10:00-17:00`; write "24 hours" for always-open |
| `last_entry` | string | | Last-entry time. **Required for the last place of each trip day** |
| `closed_days` | `int[]` | ✅ | ISO weekdays, 1 = Monday … 7 = Sunday. `[]` for no closures. **Structured field used for conflict validation** |
| `closed` | string | ✅ | Full closure description, e.g. "Mondays; between exhibitions; New Year holidays". Write "none" if none |
| `ticket` | string | ✅ | e.g. `¥1300 (special exhibitions ¥1500)`; write "free" if free |
| `booking` | enum | ✅ | `required` booking mandatory / `recommended` walk-up possible but booking advised / `none` |
| `booking_url` | string | conditional | Should be present when `booking ≠ none` (missing = P2) |
| `status` | enum | ✅ | `open` / `renovating` / `seasonal_closed` / `permanently_closed` |
| `status_note` | string | conditional | Required when `status ≠ open`; state the dates |
| `duration_min` | int | ✅ | Suggested visit minutes; stage D uses it for the timeline |

> **Never guess `status`.** Without online confirmation, `open` is forbidden.
> This is the only gate against "arrived to find it under renovation".

### Verification state `verify`

**Orthogonal to `status`**: `status` describes the venue's operating state;
`verify` describes **how far we got confirming it**. A place can be operating
normally while its site is down, bot-blocked, or renders data via JS we can't
read — then we must not pretend we verified it, **and must not drop it from the
list just because we couldn't check.**

```jsonc
"verify": {
  "state": "blocked",
  "note": "Operator site senyo.co.jp failed repeatedly (socket closed / 404, 4 paths tried); second-hand sources quote ¥700–¥1300, unconfirmable",
  "check": ["opening hours", "ticket price", "any temporary closure"]
}
```

| Field | Value | Meaning |
|---|---|---|
| `state` | `verified` | Key fields verified verbatim against official sources. **Omitting `verify` implies this** |
| | `partial` | Some fields verified; others unfindable or contradictory |
| | `blocked` | **Verification blocked**: site unreachable, anti-bot, SSL failure, JS-rendered |
| `note` | string | Required when `state ≠ verified`. State **what was tried and why it failed** |
| `check` | string[] | Items the user should confirm themselves |

**Hard rule: unverifiable ≠ delete.**

> Observed counterexample: a ferris wheel's operator site failed on all 4 paths
> tried, and a subagent simply replaced it with a different, easier-to-verify
> attraction. That was wrong — the user never learned the option existed, and
> "I couldn't verify it" is not "it isn't good".

The correct move is to **keep the place**, fill what you could confirm, put
`null` in what you couldn't, and record `verify.blocked` with the specifics. The
page flags it prominently as "unverified"; the user can check it themselves and
tell the AI to fill it in.

When `state` is `blocked`, `sources` should still contain the official URLs you
attempted — the user needs them to check on their own.

### Route-planning fuel

Without these three fields, stage D can only improvise.

| Field | Type | Required | Notes |
|---|---|:--:|---|
| `indoor` | bool | ✅ | Indoors? The **rain-alternative pool** draws from this |
| `night` | bool | ✅ | Night-worthy / has night views? Evening slots only take `true` |
| `area` | string | ✅ | (see above) At most 1–2 areas per day |

### Content

| Field | Type | Required | Notes |
|---|---|:--:|---|
| `pitch` | string | ✅ | One-line hook. The card clamps it to three lines (over that = P2); the detail dialog repeats it in full as a lede |
| `detail` | string | ✅ | Two or three paragraphs, shown in the detail dialog under the `pitch` lede |
| `photo_index` | int 1–5 | ✅ | Photogenic score. Anchors: [research-playbook.md](research-playbook.md), "Grading". Shown in the detail dialog only — not on the card |
| `photo_note` | string | | What the shot looks like and how to take it, e.g. "bamboo path in the garden; best front-lit in the morning" (missing = P2) |
| `tags` | string[] | | e.g. `["hidden gem","film location","rainy-day indoor"]` |

### Images and sources

```jsonc
"images": [
  { "url": "https://…", "credit": "© Osaka City", "source_url": "https://…" }
],
"sources": [
  { "title": "Official site · hours", "url": "https://…" }
]
```

- `sources` **must be non-empty** and every `url` must be `http(s)`. This is the
  main anti-hallucination gate — **a place without sources is rejected as P0**.
- `images` optional. Every image needs a `credit`. The page hides broken images
  via `onerror`; `validate.py --check-links` flags dead links.

### User choices (written back by the page; the AI must not pre-fill)

| Field | Type | Notes |
|---|---|---|
| `choice` | `null`\|`yes`\|`maybe`\|`no` | Always `null` when the AI generates |
| `choice_reason` | string | The user's reason when picking "skip" |

### Post-trip feedback (written only by the retro flow)

Recorded when the user, asked after a trip has ended, reports how places
actually turned out (SKILL.md, "Retro on past trips"). Both optional; only
places the user volunteers get them — never fill by inference.

| Field | Type | Notes |
|---|---|---|
| `verdict` | `loved`\|`ok`\|`disappointed` | How the visit actually landed. `choice` records what attracted before the trip; `verdict` records what delivered — the gap between them is the signal |
| `verdict_note` | string | The user's reason, one line, their wording |

Not rendered by the page (yet). The distilled conclusions go — with the user's
confirmation — into the "Proven preferences" section of `preferences.md`.

---

## `itinerary[]` (scheduling result, written back by the page)

The user assigns places to days and orders them in the scheduling view; the
result lands here.

**Do not pre-fill this field in stage A.** When the page opens with an empty
`itinerary`, it auto-creates the empty per-day containers from `trip.dates`
(dates and weekdays computed). Building the same data in two places will
eventually disagree, so the generation logic lives in exactly one place — the
page. When `trip.dates` is missing it falls back to `trip.days` containers with
`date` left null — closure-conflict validation is impossible then, but the
containers still work.

Stage D writes the guide by expanding this user-arranged list.

```jsonc
"itinerary": [
  {
    "n": 1,                        // integer. 0 means "Day 0 (arrival evening)"
    "date": "2026-09-12",          // may be null — Day 0 may have no date of its own
    "label": "Day 1",
    "places": [                    // array order = visit order
      { "id": "os-h01" },                          // lodging, unnumbered
      { "id": "os-014" },                          // → shown as number 1
      { "id": "os-031", "note": "night session" }, // → shown as number 2
      { "id": "os-h01" }                           // back to the same hotel at night
    ]
  }
]
```

| Field | Type | Required | Notes |
|---|---|:--:|---|
| `n` | int | ✅ | Day number, unique. `0` = arrival evening |
| `date` | string\|null | | `YYYY-MM-DD`. **Closure-conflict validation needs it** |
| `label` | string | | Display name; generated from `n` in the UI language when absent. **The page no longer writes this field** — leave it out so the file stays language-neutral |
| `places[].id` | string | ✅ | Must exist in `places[]` |
| `places[].note` | string | | Note for this particular visit (distinguishes purposes when a place is visited twice) |

### Why the top-level key is `itinerary`, not `days`

`trip.days` is already "number of days", an integer. Same name at different
levels with different types confuses both the JSON writer and the code reader.

### Three rules that are easy to get wrong

1. **Order lives only in the array.** Don't add `day` / `seq` fields to a place
   — storing one fact in two places always ends in conflict (delete one point
   and every seq needs renumbering). The page computes numbering at render time.
2. **The same id may appear on multiple days, or twice in one day.** Two
   consecutive Expo days, daytime plus night views, the hotel every day — all
   normal. Give repeat visits a `note`, or the validator asks you to confirm it
   wasn't a mis-drag.
3. **Absent from every `itinerary[].places` = unassigned.** There is no separate
   "unassigned" array.
4. **`n` may be 0.** "Day 0 (arrival evening)" is common — the flight lands in
   the evening and there's only time for a stroll near the hotel. The user adds
   it manually on the page; its date is the day before `dates.start`.

---

## `ui` (UI string overrides — only for languages other than en/zh)

The trip page's interface language follows `trip.output_language`: any `zh*`
value gets the built-in Chinese strings, everything else gets the built-in
English. **When the output language is neither**, translate the UI at trip
creation and put the result here:

1. Open `assets/template-trip.html` in the skill and find the `I18N.en` table
   (`const I18N = { en: {...}`). That table is the canonical key list.
2. Translate every value into `output_language` and write them as a top-level
   `ui` object with **the same keys**:

```jsonc
"ui": {
  "tabList": "Liste", "tabMap": "Carte", "tabGuide": "Guide",
  "dayN": "Jour {n}",
  "quick": ["Trop loin", "Trop de monde", "…"],   // array, same as I18N.en.quick
  "wmo": { "0": "Ciel clair", "1": "…" }          // object: WMO code → text
}
```

Rules:

- Keep `{x}` placeholders exactly as they appear in the English value — the
  page substitutes them at runtime.
- `quick` is an array of strings; `wmo` is an object; every other value is a
  plain string. The validator enforces these types (P0 on mismatch).
- Missing keys fall back to English silently — translating the whole table is
  still strongly preferred.
- Weekday and date names are **not** in the table; the page derives them from
  `output_language` via `Intl.DateTimeFormat`.
- When `output_language` is en/zh, **omit `ui` entirely** (the validator flags
  it as a P2 — it would only shadow the built-ins).

---

## Complete example

```jsonc
{
  "id": "os-018",
  "name": "Nakanoshima Museum of Art",
  "name_local": "大阪中之島美術館",
  "name_en": "Nakanoshima Museum of Art, Osaka",
  "category": "museum",
  "tier": "A",
  "scale": "2-3h",
  "area": "Nakanoshima",
  "coord": { "lon": 135.4914, "lat": 34.6914 },

  "hours": "10:00-18:00",
  "last_entry": "17:30",
  "closed_days": [1],
  "closed": "Mondays (following day when Monday is a holiday); closed between exhibitions",
  "ticket": "Permanent collection ¥1200; special exhibitions extra",
  "booking": "recommended",
  "booking_url": "https://nakka-art.jp/",
  "status": "open",
  "duration_min": 120,

  "indoor": true,
  "night": false,

  "pitch": "Black-cube landmark; the collection centers on Osaka modern art and Saeki Yūzō.",
  "detail": "Opened in 2022 … (two or three paragraphs)",
  "photo_index": 4,
  "photo_note": "The red escalator in the five-story atrium is the signature shot; avoid backlit midday.",
  "tags": ["architecture", "rainy-day indoor"],

  "images": [
    { "url": "https://…/nakka.jpg", "credit": "© Nakanoshima Museum", "source_url": "https://nakka-art.jp/" }
  ],
  "sources": [
    { "title": "Official site · hours & tickets", "url": "https://nakka-art.jp/" }
  ],

  "choice": null,
  "choice_reason": ""
}
```

---

## Validation levels

`scripts/validate.py` gates at three levels; **any P0 makes the exit code 1**.

### P0 · Reject

- Missing required field, or required string empty
- Duplicate `id`
- Illegal enum value (`tier` / `scale` / `status` / `booking` / `choice` /
  `verdict` / `trip.retro`)
- `category` not defined in `categories`
- `coord` missing, non-numeric, out of lat/lon range, or **outside `trip.bbox`**
- `sources` empty, or containing a non-`http(s)` URL
- `status ≠ open` without a `status_note`
- **Closure days cover the whole trip** — `closed_days` collides with every trip
  day, i.e. the place can't be visited at all
- `parent_id` pointing at a nonexistent id
- Illegal `kind` (only `attraction` / `lodging`)

Scheduling checks (only when `itinerary` exists):

- `itinerary[].n` not an integer, or duplicated
- `itinerary[].places[]` not objects of the form `{"id": "..."}`
- `itinerary[].places[].id` not present in `places[]`
- **A place scheduled on a day it's closed** — not a judgment call; it can't be
  visited that day
- A scheduled place whose `status` is `permanently_closed`
- `itinerary[].date` not in `YYYY-MM-DD` format

### P1 · Warn

- `--check-links` found dead links (`sources` / `images` / `booking_url`)
- A category count below `min` or above `max`
- `local_language ≠ output_language` but `name_local` missing
- Two places with nearly identical coordinates (<25 m), likely duplicates
- `verified_at` more than 30 days old
- Last place of a trip day missing `last_entry` (needs route.md to judge; checked in stage D)
- A day with no places at all
- A `kind: lodging` entry that appears on no day

### P2 · Note

- Missing `photo_note`
- `booking ≠ none` but no `booking_url`
- Missing `images`
- `detail` shorter than 60 characters
- The same place scheduled on multiple days without a `note` (confirm it's a
  deliberate repeat visit, not a drag mistake)
