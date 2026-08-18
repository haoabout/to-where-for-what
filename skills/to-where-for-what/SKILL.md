---
name: to-where-for-what
version: 1.9.0
source: https://github.com/haoabout/to-where-for-what
description: Plan a trip and produce an interactive itinerary page (attraction shortlist + map + guide in a single HTML file). Trigger on intent, in whatever language the user writes — "help me plan a trip to X", "how should I arrange N days in X", "make me a travel guide for X" («帮我规划去大阪的行程» «京都三日游怎么安排» «大阪旅行のプランを立てて»), or anything about exhaustively listing attractions, shortlisting them, sequencing a route, or writing a travel guide. Also for continuing an existing trip — re-filtering, adjusting the route, adding places. Note: if the user only asks what's worth seeing in X or what's fun nearby, without mentioning an itinerary or guide, do NOT start this pipeline — answer directly in conversation (verified, with source links), and offer the full planning flow only if they then ask to schedule it.
---

# Trip Planning

Split a trip into four stages and produce a **single `trip.html`** (three tabs: places, map, guide).

```
A search places →(you)→ ┌ ① shortlist ⇄ ② map (filter + schedule) ┐ →(you)→ ③ guide
                        └   the user iterates freely; you stay out ┘
```

You only work at A (search) and D (guide); filtering and scheduling happen on
the page.

---

## Four hard rules

Break any one of them and the output is bad.

**1. Never hand-write HTML.**
You only produce `places.json` and `route.md`, then run `build.py`. The template
already handles the views, map fallbacks, weather, responsive layout, and
theming; hand-written HTML gets you an inconsistent, buggy page.

**2. Never invent fields.**
Every field of `places.json` is defined in
[data-schema.md](references/data-schema.md). Fields outside the contract are
not rendered — the content is **silently lost**. If you truly need a new
field, change the schema and the validator first.

**3. Never write information you haven't verified online.**
Every place must have `sources` (real URLs). Never set `status` to `open` without
confirmation. The validator catches format problems, but it cannot catch
fabrication — that discipline is on you.

**4. Go / don't-go decisions belong to the user — always.**
Two halves. *Selection*: everything found within the quotas gets listed;
recommendation strength is expressed through `tier` and nothing else — never
drop a place because you judge it skippable. (Exception: a place that fails
verification — permanently closed, can't confirm it exists — is flagged, not
silently deleted.) *Scheduling*: never add, remove, reorder, or move places
between days on your own, at any stage. Propose first — what change, what the
result looks like, why — and touch `itinerary` only after the user agrees.
"I noticed a problem" earns a proposal, not an edit.

---

## Talking to the user

Every question asking the user to decide follows four beats, in order:

| Beat | What it does | AskUserQuestion field |
|---|---|---|
| **1 Re-ground** | Say which step they're on (they haven't looked in 20 minutes) | `header` (≤12 chars) + first line of `question` |
| **2 Simplify** | Plain words; never leak internal names ("stage B", "the `choice` field") | body of `question` |
| **3 Recommend** | One clear pick with the reason — nothing recommended causes decision paralysis | first option, label ends `(recommended)` |
| **4 Options** | 2–4 clickable choices — typing is friction | `options`, each label readable alone |

Beats 1–2 apply even with nothing to choose. The highest-stakes case is the
B + C handoff — the user leaves to operate a busy three-pane page:

> **Step 2 of 4 — over to you**
> The browser is open; both steps happen on the page:
> 1. In the shortlist, mark each place want / maybe / skip
> 2. On the map, drag the ones you want into a day — detours show up instantly
> Tell me when the schedule looks right and I'll write the guide.

Whether to ask at all:

- **Smart skip** — never ask what the user already told you; re-asking reads as
  not listening.
- **Merge** — independent questions go in one interaction, not three rounds.
- **Don't ask what you can decide** — exploratory choices are yours: decide,
  then state the assumption. Ask only what you genuinely can't settle alone.
- **will ≠ is** — never report work as done ("the page is generated") before it
  has actually run; say "I'll build it now" until it exists.

**No structured questioning tool** (Codex, plain chat)? The four beats become
prose — same content (don't assume the tool exists — check). Ask at most 1–3
critical things at a time; when a gap doesn't block starting, assume and
say so.

### Plain words everywhere, not only in questions

Beat 2 governs **every line the user sees** — progress updates, background-task
reports, delivery notes — not just the four beats. Describe consequences and
next steps, never internal grade names. Left column stays internal; say the
right column, translated into the user's language.

| Internal term | What to say |
|---|---|
| P0 | "N issues that must be fixed before the page can be delivered" — at zero, just "data check passed" |
| P1 | "N things worth double-checking", naming each one concretely |
| stage A / B / C / D | "step 1 / 2 / 3 / 4 (of 4)" |
| validate / validator | "checking the data for errors" |
| enrich | "auto-filling coordinates and images" |
| build / rebuild | "regenerating the page" |
| `choice` / `itinerary` | "the picks you marked" / "the days you arranged" |
| stub | "the place you added on the map, details pending" |
| tier | "recommendation level" |
| Nominatim / Overpass / Wikimedia / bbox | don't name them — "the map service" / "the photo library" |

So "validate finished — 0 P0, 2 P1" is said as: "Data check passed, the page is
ready. Two things worth double-checking: Kiyomizu-dera's closing time, and the
Gion → station walk I estimated rather than looked up."

---

## Preferences file

Long-term preferences live in **`~/.to-where-for-what/preferences.md`** —
deliberately outside the skill directory, so updating or reinstalling the
skill never touches it (the skill ships only `preferences.template.md`).

On startup:

1. Read it. If it doesn't exist, copy `<SKILL_ROOT>/preferences.template.md`
   over verbatim and tell the user "first run — I've created a preferences file".
2. If it lacks a section the template has since added: ask the user about that
   item, then **append — never rewrite the whole file** (that destroys
   accumulated preferences). Match sections **by meaning, not literal heading
   text** — an older-template file in another language has the same sections.
   Exception: a section filled by a flow, not by answers (currently "Proven
   preferences", retro-written) — append it empty and mention in one line that
   it fills itself.

**Capture in-passing declarations.** When the user states something durably
true mid-conversation — a dietary restriction, "we always travel with a
stroller" — propose the exact line and its section, append once they confirm.
One-trip-only facts stay in `brief.md`. Never write without showing the
wording first.

**Use your own read/write tools for these steps, not the shell.** `mkdir -p`
and `cp` fail under Windows PowerShell / cmd — and this is the very first step
of the whole flow.

---

## Which interpreter runs the scripts

**Do not hardcode `python3`** — on Windows that name is usually an alias that
opens the Microsoft Store. Probe once, then use the probed command for the
whole conversation (written `<PY>` below): try `py -3 --version` (official
Windows launcher), then `python --version` (confirm 3.x, not 2.7), then
`python3 --version` (the norm on macOS / Linux). Python 3.9+ is required; if
none works, tell the user to install it — don't push on.

---

## Subagent model tier

These subagents (rule-driven search, stub completion, transit lookups, fact
re-checks) don't need the main conversation's model: **when the platform lets
you pick, choose one tier below**, still vision-capable where the briefing
requires it — stage A alone spawns 2–4 agents.

The user pays per spawn, so the tier is their call — ask **once per
conversation, not once per spawn**:

- **Before the first spawn**, fold the question into the nearest user-facing
  beat (usually the A1½ confirmation): name the actual models, recommend one
  tier down, offer same-tier and no-subagents.
- **Every later spawn: announce in one line** — "image agent (<X>) running
  in the background" — and never re-ask.
- **Platform can't choose models?** Subagents inherit the main model — say so
  in that same question; the choice collapses to "spawn or not".

---

## Before starting · a trip already in progress?

When the user says "continue" or "tweak my X trip", **do not restart from the
opening questionnaire** — the trip data is on disk, independent of any chat
session, and re-running a search wipes the `choice` values and `itinerary`
from last time.

1. Locate the trips root (next section), find the matching trip, read its
   `places.json`
2. That file is the whole truth: `choice` is what the user filtered,
   `itinerary` is the days and ordering they arranged
3. `trip.html` is a build artifact — **don't read it, don't hand-edit it**

One rebuild restores the page:

```bash
<PY> <SKILL_ROOT>/scripts/build.py trips/<trip> --serve
```

**Not sure which trip it is? List the trips under the root and let the user
pick.** Don't guess.

"But I did arrange a schedule" while `places.json` has none → they opened the
page via `file://` (no auto-save); the changes live only in that
machine/browser/address's localStorage, unreadable to you. Have them open that
same page and click "Save choices & schedule" once.

### Completing user-added stubs

The page's map search lets the user add places; what lands in `places.json` is
name + coordinates + OSM link, `origin: "user"`, no research fields — by
design: **the user adds stubs, you complete them afterwards**.

**Whenever you continue an existing trip — whatever was asked — first scan**
for entries with `origin == "user"` and no `tier`, and complete them **even
when the user doesn't mention them**: once they added the point, they consider
it handed off. **3 or more stubs → spawn one completion
subagent** ([subagent-briefing.md](references/subagent-briefing.md), "Variant:
completing user stubs" — it finds and verifies images too); 1–2 → main
conversation. Contract and preservation rules (keep `origin`, `choice`, and
schedule references; out-of-bbox handling):
[data-schema.md](references/data-schema.md), "User stubs". Validate after.

---

## Before a new trip · retro

When starting a **new** trip, before the A1 questionnaire: scan `trips_root`
for trips whose `dates.end` has passed and `trip.retro` is unset. Found
one → read **[retro.md](references/retro.md)** and run the retro
(most recent trip only — never backlog-interrogate). It's the only step that
captures what actually *delivered* versus what attracted.

---

## Where trip files live

**Ask once on first use, record it as `trips_root` in `preferences.md`, never
ask again.** Otherwise trips land in whatever directory happened to be open —
stuffed into an unrelated repo, unfindable later.

Resolve in this order:

1. `preferences.md` has `trips_root` → use it
2. The current directory already contains `trips/` → use it, no need to ask
3. Otherwise ask, suggesting **`~/travel-plans/`** (not a hidden dir — the
   user opens and shares these files; not `~/Documents` — its name varies by
   system language), and write the answer into `preferences.md`

You create the trip directory; the user never touches a file dialog. Below,
`trips/<trip>/` means `<trips_root>/<trip>/`.

---

## Stage A · Search for places

### A1. Opening questionnaire

Destination is mandatory. Four more:

| Ask | Why |
|---|---|
| **Travel dates + number of days** | Closure conflicts, festivals, holidays, weather — none checkable without dates |
| **Arrival and departure times** | See below |
| **Party + stamina** | Route intensity and place selection |
| **Home base** | Address if booked, rough area if not — each day's start and end |

Transport mode, budget tier, and interest weights are **not asked here** — they
live in `preferences.md`.

#### Why ask down to the hour

"How many days" alone misses the half-day shapes: a 3 pm landing is half a
day, a noon departure fits one shopping street, arriving the night before adds
a "Day 0". Once you know:

| Situation | How it lands in the data |
|---|---|
| Arrival = evening before `dates.start` | Tell the user the page can add "Day 0" |
| First or last day is half | Write it into `trip.note`; stage D plans a half day |
| All full days | Nothing to do |

**Do not pre-fill the `itinerary` field.** The page auto-creates the empty
per-day containers from `dates` when it opens; building the same data in two
places will eventually disagree.

### A1½. Confirm, announce, then search

One mandatory beat before the first search: play back destination, dates
(incl. any half-day shape), party, home base, plus **which categories you'll
search and roughly how many places each** (quota table: playbook). Get a yes —
the last cheap moment for corrections.

In the same message, set two expectations:

- **The search takes roughly 10–20 minutes** and they can walk away.
- **If you can spawn subagents, search in them** — dozens of searches would
  bloat the context stages B–D still need. Build each prompt from
  **[subagent-briefing.md](references/subagent-briefing.md)** —
  copy the template, don't improvise (a subagent inherits nothing; the file
  carries the partial-file protocol and merge steps). This message is also
  where the one-time model-tier question lands. No subagent capability?
  Search in the main conversation — the time warning matters even more.

### A2. Search and produce `places.json`

Read **[research-playbook.md](references/research-playbook.md)**
first — the complete contract for this stage: category quotas (35–50 total,
never pad), the information that must be fetched in the first pass, the
festival / public-holiday check, search strategy, anti-hallucination rules,
grading, and image sourcing. Two reminders that keep getting missed:

- **Create the lodging entry the moment the questionnaire yields a hotel name
  or address** — `kind: "lodging"`, on the map from the first build (contract:
  [data-schema.md](references/data-schema.md), "Lodging").
- Set **`trip.theme_hue`** — one integer derived from the destination's
  dominant material or landscape
  ([data-schema.md](references/data-schema.md#picking-theme_hue)).

### A3. Fill coordinates & images · validate · build

**Don't fill coordinates and images yourself — run the scripts.** They already
handle Nominatim's rate limit, bbox validation, and Wikimedia's API
requirements:

```bash
<PY> <SKILL_ROOT>/scripts/enrich.py   trips/<trip>/places.json --coords --images
<PY> <SKILL_ROOT>/scripts/enrich.py   trips/<trip>/places.json --transit
<PY> <SKILL_ROOT>/scripts/validate.py trips/<trip>/places.json --check-links
<PY> <SKILL_ROOT>/scripts/build.py    trips/<trip> --serve
```

Run `--transit` separately (Overpass throttles back-to-back requests); if it
fails, skip it — transit is a bonus, never a blocker.

`enrich.py` reports what it can't fill (it prefers a blank over a plausible
wrong value); the manual work splits:

- **Coordinates — fix them yourself, in the main conversation.** Misses are
  few, and the judgment calls need trip context only you have (playbook,
  "Getting coordinates").
- **Images — spawn one image subagent, always**, the moment
  `--coords --images` finishes: it judges the candidates in `image-audit.json`
  visually while you fix coordinates and run `--transit`. Prompt from
  [image-agent-briefing.md](references/image-agent-briefing.md) —
  it carries timing, the `--apply-image-review` merge, and the no-subagent
  fallback. Prefer a vision-capable model.

**Delivery requires zero P0.** Read each P1 and decide to fix or ignore — and
when reporting either to the user, translate per the glossary in "Talking to
the user".

**Prefer `--serve`**: under `file://` the OSM basemap returns "Access blocked"
tiles (HTTP 200 — only eyes catch it). With an embedded preview pane, use
`--serve --no-open` and open the printed URL there; you can then screenshot
the page yourself for the pre-delivery check.

---

## Stages B + C · The user filters and schedules (you're not involved)

Hand off with the pattern from "Talking to the user": **filter** (mark want /
maybe / skip; markers recolor live, no need to come back to you), then
**schedule** (drag places into days, or select a day and click dots; reorder
by drag or ↑↓; the map links each day's points in visit order — detours
visible at a glance; a place may repeat across or within days; `+` in the
day-plan header adds "Day 0").

Once a day is roughly in shape, one button at the top of the day plan
**generates the transport**: every leg is routed through OSM routing (walking
under 2 km, driving above, switchable per leg) and drawn on the map as the real
path instead of a straight line, with time and distance on each leg and a daily
total. Transit legs are not routed — there is no open timetable — so they stay a
dashed line carrying the user's own note. Reordering a day marks its legs stale;
the button then offers to update them.

**Don't tell the user to hit save.** Under a `--serve` server, changes
auto-write to `places.json` after a few idle seconds (status at the page
bottom). Only `file://` needs the "Save choices & schedule" button; browsers
without direct write fall back to "Download JSON" or "Copy code".

**Don't press "generate transport" for them either.** Like filtering and
scheduling, it is a stage-B/C action taken in the browser on an arrangement the
user considers settled — running it from your side routes an itinerary they may
be about to change, and its numbers are page-written data (`leg`), never
something you fill in by hand.

In a pasted code, `+ ? -` lines are choices, `D1 D2 …` lines the schedule
(**in-line order = route order**, parentheses are notes). Update `choice` and
`itinerary` from it, then rebuild.

Then **stop and wait**. What to cut and which day to go are trade-offs, not
computations — they belong to the user.

When they say done: re-read `places.json`, confirm the `choice` distribution
and `itinerary`, move to D. If choices contradict the declared interest
weights, mention it once — but **never write `preferences.md` from stage-B
data**: choices measure attraction, not experience; only the retro earns
write access.

---

## Stage D · Design the route

Read **[route-design.md](references/route-design.md)** first — the
complete contract for this stage: clustering by `area`, constraints
(`closed_days` / `night` / `indoor`), transport lookups (delegable; segment
planning stays yours), guide structure, page-generated sections, and the `---`
page-break system.

**When `places.json` has an `itinerary`, write to it — do not regroup.** It is
the user's own day assignment; overriding it throws away trade-offs they just
made. Disagree? Say so in the guide body and let them change it. Propose your
own only when `itinerary` is missing or empty — and hard rule 4 applies
throughout: every itinerary edit is proposed with the concrete before/after
and applied only after the user agrees.

Write to `trips/<trip>/route.md`, then rebuild:

```bash
<PY> <SKILL_ROOT>/scripts/build.py trips/<trip> --serve
<PY> <SKILL_ROOT>/scripts/build.py trips/<trip> --standalone   # guide.html — the guide alone, no filtering UI
```

The guide view exports itself as `guide.md` — `route.md` verbatim plus the
schedule and checklist from current choices. That's the form to hand back to
an AI; the built page is ~600KB of mostly template.

---

## File layout

```
<trips_root>/2026-09-osaka/          # root: see "Where trip files live"
├── brief.md          # answers to the opening questionnaire
├── places.json       # ★ single source of truth; every view renders from it
├── transit.geojson   # metro lines & stations (enrich.py --transit)
├── image-audit.json  # image candidates + verdicts (enrich.py --images)
├── route.md          # guide body (you write this)
└── trip.html         # build artifact — never hand-edit
```

`places.json` is the single truth; user choices update its fields in place, so
the shortlist and the map can never disagree. `trip.html` is a **snapshot at
build time** — self-contained and shareable, but its readers see the data as
of that build; later in-browser changes live in localStorage, not in the file.
Rebuild after every `places.json` write (the `--serve` server does this on
save).

---

## Language rules

**UI language of the trip page**: follows `trip.output_language`. `zh*` gets the
built-in Chinese interface, everything else the built-in English one. For any
other language, translate the template's `I18N.en` table into a top-level `ui`
object in `places.json` when creating the trip — contract in
[data-schema.md](references/data-schema.md), "ui". Weekdays/dates localize
automatically.

**Body text (`pitch` / `detail` / `route.md`)**:

- Place names in **the user's language**; where the local language differs,
  write "user-language name (local-language name)" on **first** occurrence,
  then the user-language name alone.
- The local-language name must be **findable on the map**; the user-language
  name must be natural and consistent throughout.
- With no established translation, transliterate or translate freely — but
  **never mix multiple renderings** of the same place in one document.

---

## Pre-delivery self-check

Once `validate.py` is at zero P0, **spawn the verify subagent** — prompt from
[verify-agent-briefing.md](references/verify-agent-briefing.md). It re-opens
sources with fresh eyes (checking your own data repeats your own misreadings)
while you do the one thing it can't: open the built page and look. The
briefing carries the division of labor, adjudication rules (it over-reports by
design), and the no-subagent fallback.

Then run **[checklist.md](references/checklist.md)** end to end — the delivery
gate, including everything that must be stated at delivery (staleness,
estimates, the first-trip `preferences.md` offer).

---

## Known limitations

The authoritative list, with delivery phrasing, is
[checklist.md](references/checklist.md), "Must be stated at delivery". The one
limitation that shapes earlier work — `file://` degradation — is covered in
"Stages B + C".

---

## Updating this skill

When the user asks whether or how to update this skill, read
[updating.md](references/updating.md) **before answering** — the order there
matters (reassure about user data first, detect local edits, then merge the
directory as one unit).

---

## Resource guide

| File | When to read |
|---|---|
| [data-schema.md](references/data-schema.md) | Before writing `places.json` — required |
| [research-playbook.md](references/research-playbook.md) | Before stage-A searching — required |
| [subagent-briefing.md](references/subagent-briefing.md) | When spawning stage-A search subagents |
| [image-agent-briefing.md](references/image-agent-briefing.md) | When spawning the A3 image subagent |
| [verify-agent-briefing.md](references/verify-agent-briefing.md) | When spawning the pre-delivery verify subagent |
| [route-design.md](references/route-design.md) | Before stage-D routing — required |
| [retro.md](references/retro.md) | When a finished trip awaits its retro |
| [checklist.md](references/checklist.md) | Before delivery |
| [updating.md](references/updating.md) | When the user asks to update this skill |
| `scripts/enrich.py` | Fill coordinates & images after `places.json` is written |
| `scripts/validate.py` | After every `places.json` change |
| `scripts/build.py` | Generate/update the page |
