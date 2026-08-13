---
name: to-where-for-what
version: 2.3.0
source: https://github.com/haoabout/to-where-for-what
description: Plan a trip and produce an interactive itinerary page (attraction shortlist + map + guide in a single HTML file). Trigger on intent, in whatever language the user writes — "help me plan a trip to X", "how should I arrange N days in X", "make me a travel guide for X" («帮我规划去大阪的行程» «京都三日游怎么安排» «大阪旅行のプランを立てて»), or anything about exhaustively listing attractions, shortlisting them, sequencing a route, or writing a travel guide. Also for continuing an existing trip — re-filtering, adjusting the route, adding places. Note: if the user only asks what's worth seeing in X or what's fun nearby, without mentioning an itinerary or guide, do NOT start this pipeline — answer directly in conversation (verified, with source links), and offer the full planning flow only if they then ask to schedule it.
---

# Trip Planning

Split a trip into four stages and produce a **single `trip.html`** (three tabs: places — as a swipe deck or a flat grid — plus map and guide).

```
A search places →(you)→ ┌ ① shortlist ⇄ ② map (filter + schedule) ┐ →(you)→ ③ guide
                        └   the user iterates freely; you stay out ┘
```

**Filtering and scheduling need no involvement from you** — the map view has three
panes side by side: shortlist | day plan | map. When the user changes a choice the
marker recolors instantly; assigning places to days and ordering them all happens
on the page. You only work at A (search) and D (writing the guide).

---

## Four hard rules

Break any one of them and the output is bad.

**1. Never hand-write HTML.**
You only produce `places.json` and `route.md`, then run `build.py` to generate the
page. The template already handles all the views, map fallbacks, weather,
responsive layout, and light/dark theming. Hand-written HTML gets you an
inconsistent, buggy page.

**2. Never invent fields.**
Every field of `places.json` is defined in
[references/data-schema.md](references/data-schema.md). Fields outside the contract
are not rendered by the template — the content is **silently lost**. If you truly
need a new field, change the schema and the validator first.

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
between days on your own, at any stage. Propose first — which places, what
change, what the result looks like, why — and touch `itinerary` only after the
user agrees. "I noticed a problem" earns a proposal, not an edit.

---

## Talking to the user

Every question that asks the user to decide follows four beats, in this order.
Drop one, or reorder them, and the question gets worse.

| Beat | What it does | Without it | AskUserQuestion field |
|---|---|---|---|
| **1 Re-ground** | Say which step they're on | They haven't looked at the screen in 20 minutes and open to a question with no context | `header` (≤12 chars) + first line of `question` |
| **2 Simplify** | Plain words for what's being asked | Internal names leak — "stage B", "the `choice` field" — and mean nothing to them | body of `question` |
| **3 Recommend** | One clear pick, with the reason | A row of options with nothing recommended causes decision paralysis | first option, label ends `(recommended)`, reason in `description` |
| **4 Options** | 2–4 clickable choices | Asking them to type is friction; they put it off | `options` — each label readable with the description covered |

Worked example, asking for `trips_root` on first use:

> **Where to store** ←1 · First run, so I need somewhere to keep trip files;
> I won't ask again ←2 · I'd suggest `~/travel-plans/` — it stays findable
> later from any directory ←3 · A) `~/travel-plans/` (recommended)
> B) the current directory C) let me pick a path ←4

Beats 1 and 2 apply even when there is nothing to choose. The handoff into
stages B + C is the highest-stakes case: the user leaves the conversation to
operate a page with three panes and dozens of markers.

> **Step 2 of 4 — over to you**
> The browser is open. Both of these happen on the page; you don't need to come
> back to me:
> 1. In the shortlist, mark each place want / maybe / skip
> 2. Switch to the map and drag the ones you want into a day — detours show up
>    the moment you do
> Tell me when the schedule looks right and I'll write the guide.

Four rules that decide *whether* to ask at all:

- **Smart skip** — never ask what the user already told you. "Two of us, skip
  Universal Studios, we're into architecture" answers three questions; asking
  again reads as not listening.
- **Merge** — questions with no dependency between them go in one interaction,
  not three rounds.
- **Don't ask what you can decide** — exploratory choices are yours. Decide,
  then state the assumption in your reply. Only ask what you genuinely cannot
  settle alone.
- **will ≠ is** — saying "the page is generated" before `build.py` has run sends
  the user to a link that isn't there. Say "I'll build it now" until it exists.

| Anti-pattern | Fix |
|---|---|
| Question with no re-grounding | Lead with which step they're on |
| Options with nothing recommended | Recommend one and say why |
| Asking for a free-form typed answer | Give A/B/C |
| Re-asking something already answered | Smart skip |
| Reporting work that hasn't run | will ≠ is |

**With no structured questioning tool** (Codex, plain chat), the four beats
become prose — same content, written out. **Don't assume the tool exists**;
decide by whether you actually have it. Ask at most 1–3 of the most critical
things at a time, and when a gap doesn't block starting, assume and say so.

---

## Preferences file

Long-term preferences live in **`~/.to-where-for-what/preferences.md`**, reused
across trips and across projects.

**Deliberately outside the skill directory**: updating or reinstalling the skill
(git pull, downloading a zip, or deleting and reinstalling) never touches it. The
skill directory only ships the `preferences.template.md` template.

On startup:

1. Read `~/.to-where-for-what/preferences.md`. If it doesn't exist, copy the content
   of `<SKILL_ROOT>/preferences.template.md` over verbatim and tell the user
   "first run — I've created a preferences file for you".
2. When the file exists but lacks a section the template has since added,
   **append, never rewrite** — ask the user about that one item, then add it.
   **Never rewrite the whole file**; that would destroy preferences the user has
   accumulated. Match sections **by meaning, not by literal heading text** — an
   existing file may have been created from an older template in another language
   (e.g. Chinese); a heading in a different language is the same section, not a
   missing one. One exception to "ask first": a section that is **populated by a
   flow, not by the user's answer** (currently "Proven preferences", written
   only by the post-trip retro) has nothing to ask about — append it empty with
   its explanatory text and mention in one line that it exists and fills itself.

**Capture in-passing declarations.** When the user states something durably
true mid-conversation — a dietary restriction, queue tolerance, "we always
travel with a stroller" — that's a preference leaking away unless caught:
propose the exact line and the section it belongs in, and append once they
confirm. One-trip-only facts (this hotel, this flight) stay in `brief.md`.
Never write without showing the wording first.

**Use your own read/write tools for these two steps, not the shell.**
`mkdir -p`, `[ -f ... ]`, and `cp` are POSIX-only and fail outright under
Windows PowerShell / cmd — and this is the very first step of the whole flow;
break here and the user can't even start.

---

## Which interpreter runs the scripts

**Do not hardcode `python3`.** On Windows, the python.org installer only installs
`python.exe` and `py.exe` — **no `python3.exe`** — while the system ships an app
execution alias of that exact name whose job is to **open the Microsoft Store**.
So for Windows users, `python3 build.py` most often doesn't error — it pops up a
store page.

Probe once the first time you need to run a script, then use the probed command
for the whole conversation (written as `<PY>` below):

| Order | Try | Notes |
|---|---|---|
| 1 | `py -3 --version` | Official Windows launcher, most reliable |
| 2 | `python --version` | Confirm the output is 3.x, not 2.7 |
| 3 | `python3 --version` | The norm on macOS / Linux |

Python 3.9+ is required. If none works, tell the user to install it — don't push on.

---

## Before starting · check for a trip already in progress

When the user says "continue", "pick up where we left off", or "tweak my X trip",
**do not restart from the opening questionnaire**.

The conversation is new, but the trip data has been on disk the whole time — **it
has no relationship to the chat session**. Re-running a search round isn't just
wasteful: it wipes out the `choice` values the user filtered and the `itinerary`
they arranged last time.

1. Locate the trips root in the order given in the next section, look for a
   matching trip, and read its `places.json`
2. That file is the whole truth: `choice` is what the user filtered, `itinerary`
   is the days and ordering they arranged
3. `trip.html` is a build artifact — **don't read it, don't hand-edit it** —
   rebuilding regenerates it

One rebuild restores the page to where it was last time:

```bash
<PY> <SKILL_ROOT>/scripts/build.py trips/<trip> --serve
```

**If you're not sure which trip it is, list the trips under the root and let the
user pick.** Don't guess.

If the user says "but I did arrange a schedule" and `places.json` has none: they
most likely opened the page by double-clicking (`file://`, which has no
auto-save), so the changes only live in localStorage on **that machine, that
browser, that address** (`file://` and `http://localhost` are two separate
stores) — you can't read them. Have them open that same page and click
"Save choices & schedule" once.

### Completing user-added stubs

The trip page's map has a search box (Nominatim). When the user spontaneously
wants to go somewhere, they search it and add it to the shortlist or to a day
with one click — what lands in `places.json` is only a name + coordinates + OSM
link, marked `origin: "user"`, with none of the research fields. This division of
labor is by design: **the user adds stubs, you complete them afterwards**.

Whenever you continue work on an existing trip (whatever the user asked for),
first scan:

1. Find entries in `places[]` with `origin == "user"` and **no `tier`** — that's
   the to-complete list
2. Run them through the stage-A research pipeline: verify hours / tickets /
   booking online, write `pitch` and `detail`, set `tier`/`scale`/`category`,
   fill `name_local` (contract: data-schema.md, "User stubs"). **3 or more
   stubs → spawn one completion subagent** (prompt: subagent-briefing.md,
   "Variant: completing user stubs" — it finds and verifies images too);
   1–2 → do it in the main conversation, a spawn costs more than it saves
3. **Keep the `origin: "user"` field** (it records provenance, not a to-do flag),
   and **keep the user's existing `choice` and any schedule references** — a
   place the user deliberately searched for and added usually already has
   `choice: yes`; don't touch it
4. After completing, run `validate.py`; coordinates outside the bbox only raise
   P1 — just confirm it isn't a same-name mismatch. If the point truly is well
   outside the bbox (e.g. Nara added to an Osaka trip), route it in the guide
   using realistic travel times

Complete these even when the user doesn't mention them — once they added the
point on the map, they consider it handed off to the AI.

---

## Before a new trip · retro on past trips

Stage-B choices record what *attracted* the user; only the trip itself shows
what *delivered*. That gap — the hyped spot that disappointed, the reluctant
add that became the highlight — is the most valuable preference signal there
is, and this is the only step that collects it.

**Trigger**: when starting a **new** trip, before the A1 questionnaire, scan
`trips_root` for trips whose `dates.end` has passed and whose `trip.retro` is
unset. Take the most recent one only — never backlog-interrogate.

**Ask lightly, once, two open questions**: which places turned out really
worth it, and which they regretted or found disappointing. Record what they
volunteer; don't chase the places they didn't mention. "Don't want to go over
it" is a full answer — write `trip.retro: "skipped"` and never raise that trip
again. (A months-late answer is not a worse answer: what still surfaces from
memory after weeks is precisely the durable signal.)

**Record on two levels**:

1. **Raw, into that trip's `places.json`**: set `verdict` /
   `verdict_note` on the places mentioned (contract: data-schema.md,
   "Post-trip feedback"), then `trip.retro: "done"`.
2. **Distilled, into `preferences.md` "Proven preferences"** — but the
   generalization is the dangerous step: "disliked teamLab" could mean
   queues, crowds, or immersive shows in general, and picking the wrong
   axis skews every future trip. So **propose the exact wording, with its
   evidence, and append only after the user confirms** — never write it
   silently. Each entry cites the trip and date.

Proven entries outrank the declared interest weights when they conflict
(playbook, "Grading") — and a wildcard pick the user reports loving is the
strongest promotion signal a category can get.

---

## Where trip files live

**Ask once on first use, record it as `trips_root` in `preferences.md`, never ask
again.**

If you don't ask, trips land in "whatever directory the user happened to have the
AI open in" — stuffed into an unrelated code repo, and unfindable when they ask
"continue my Kyoto trip" from a different directory.

Resolve in this order:

1. `preferences.md` has `trips_root` → use it
2. The current directory already contains `trips/` → use it (no need to bother
   the user)
3. Otherwise ask the user, suggesting **`~/travel-plans/`** as the default, and
   write the answer into `preferences.md`

The default is not `~/.to-where-for-what/trips/` (HTML files the user opens and
shares don't belong in a hidden directory) and not `~/Documents` (the directory
name varies by system language).

The trip directory itself is created by the AI; the user never touches a file
dialog. Below, `trips/<trip>/` always means `<trips_root>/<trip>/`.

---

## Stage A · Search for places

### A1. Opening questionnaire

Destination is mandatory. Four more:

| Ask | Why |
|---|---|
| **Travel dates + number of days** | Determines closure-day conflicts, seasonal specials, limited-run exhibitions, weather. Without dates, none of these can be done |
| **Arrival and departure times** | See "Why ask down to the hour" below |
| **Party + stamina** | Determines route intensity and place selection |
| **Home base** | Address if a hotel is booked, rough area if not. Determines each day's start and end points |

Transport mode, budget tier, and interest weights are **not asked here** — they
live in `preferences.md`, asked once and reused long-term.

#### Why ask down to the hour

"How many days" alone misses two very common shapes:

- **Landing at 3 pm on day one** — that day is really half a day; four museums
  will not fit
- **A noon flight on the last day** — the morning fits breakfast and one
  shopping street
- **Arriving the night before** — an extra "Day 0 (arrival evening)", enough for
  a stroll near the hotel

Once you know:

| Situation | How it lands in the data |
|---|---|
| Arrival = the evening before `dates.start` | Tell the user the scheduling page can add a "Day 0" |
| First or last day is half a day | Write it into `trip.note`; stage D plans that day as a half day |
| All full days | Nothing to do |

**Do not pre-fill the `itinerary` field.** The page auto-creates the empty
per-day containers from `dates` when it opens. Building the same data in two
places will eventually disagree. Contract:
[data-schema.md](references/data-schema.md).

### A1½. Confirm, announce, then search — in subagents when you can

Between the questionnaire and the first search there is one mandatory beat.
Play back what you have — destination, dates (including any half-day shape),
party, home base — plus **which categories you're about to search and roughly
how many places each** (the quota table in the playbook). Get a yes. This is
the last cheap moment for corrections; after the search round it's expensive.

In the same message, set two expectations:

- **The search takes roughly 10–20 minutes.** Say so, and that they can walk
  away — the alternative is a user staring at a silent screen wondering if
  anything is happening.
- **If you can spawn subagents, search in them, not in the main
  conversation.** Dozens of searches' worth of intermediate results otherwise
  bloat the context that stages B–D still need. Build each subagent's prompt
  from **[references/subagent-briefing.md](references/subagent-briefing.md)**
  — copy the template, fill the placeholders; don't improvise the prompt (a
  subagent inherits nothing from this conversation, including every rule
  you've read). Parallel agents never write the same file: each writes its
  own `partial-<group>.json`, and you merge into `places.json` afterwards,
  then run A3 yourself (A3 spawns one further subagent, for images — see A3). No subagent capability (plain chat, Codex)? Search in
  the main conversation as before — the time warning matters even more then.

### A2. Search and produce `places.json`

Read **[references/research-playbook.md](references/research-playbook.md)** for
the full rules: category quotas, search strategy, anti-hallucination, image
sourcing, micro-spot handling.

Key points:

- Total **35–50**, allocated by category quotas; if a small city can't fill
  them, **say so honestly — never pad**
- Hours, closure days, booking status, tickets, renovation status **must be
  obtained in the first pass** — otherwise the user filters for an hour and then
  discovers the place is shut that day
- Coordinates use the `{"lon":…, "lat":…}` object form, never an array
- Image URLs: let `enrich.py`'s chain run first; leftovers and verification
  belong to the A3 image subagent. Wikimedia thumbnail URLs specifically are
  **never hand-assembled** (see the playbook's image section)
- **Create the lodging entry now** — the moment the questionnaire yields a
  hotel name or address, it goes into `places.json` as `kind: "lodging"`
  (contract: data-schema.md, "Lodging"), so the hotel is on the map from the
  very first build. Only a rough area so far? Note it in `brief.md` and add
  the entry when the booking lands. This is the step that keeps getting
  forgotten — the user reads the map around their hotel
- Set **`trip.theme_hue`** — one integer that colours the page's title band.
  Derive it from the destination's dominant material or landscape — never
  from a mood word, a flag, or a cuisine. All 360 hues are available. Full
  rules and examples:
  [data-schema.md](references/data-schema.md#picking-theme_hue)

### A3. Fill coordinates & images · validate · build

**Don't fill coordinates and images yourself — run the scripts.** These are
deterministic API calls; the scripts are more accurate than you, and they already
handle Nominatim's 1 req/s rate limit, bbox validation, and the fact that
Wikimedia thumbnails must go through the API.

```bash
<PY> <SKILL_ROOT>/scripts/enrich.py   trips/<trip>/places.json --coords --images
<PY> <SKILL_ROOT>/scripts/enrich.py   trips/<trip>/places.json --transit
<PY> <SKILL_ROOT>/scripts/validate.py trips/<trip>/places.json --check-links
<PY> <SKILL_ROOT>/scripts/build.py    trips/<trip> --serve
```

`--transit` pulls the local metro / light-rail lines and stations from OSM into
`transit.geojson`. Line colors come from OSM's `colour` tag, i.e. the official
line colors. **Run it separately** — don't combine with `--coords --images`:
Overpass allocates execution slots per IP, and back-to-back requests get
throttled. If it fails, skip it — the transit layer is a bonus, never a blocker.

Whatever `enrich.py` can't fill, it reports explicitly (usually not found, or the
hit falls outside the bbox). **It prefers leaving a blank over writing a
plausible-looking wrong coordinate.** Only then does manual work start, and it
splits two ways:

- **Coordinates — fix them yourself, in the main conversation.** Misses are
  usually few, and the judgment calls (is an out-of-bbox hit a same-name
  mismatch, or a place the user really means to visit?) need trip context
  only you have. Rules: playbook, "Getting coordinates".
- **Images — spawn one image subagent, always**, the moment
  `--coords --images` finishes. It finds images for the misses and visually
  verifies every image the chain filled — the slowest part of A3 — in the
  background while you fix coordinates and run `--transit`. Build its prompt
  from [references/image-agent-briefing.md](references/image-agent-briefing.md)
  — copy the template, fill the placeholders; don't improvise. Prefer a
  vision-capable model. It writes only `images-patch.json`; review it and
  merge into `places.json` before validating (merge rules in the briefing).
  No subagent capability? Do the image work yourself, same playbook rules.

**Delivery requires zero P0.** Read each P1 and decide to fix or ignore.

`--serve` starts a local server and opens the browser. **Prefer it**: under
`file://` the official OSM basemap returns an image reading "Access blocked"
(HTTP status still 200 — only eyes catch it).

**If your environment has an embedded browser / preview pane, use it**: run
`--serve --no-open` (so the system browser doesn't also pop up) and open the
printed URL in the pane. The user keeps everything in one window, and you can
screenshot the page yourself for the pre-delivery check instead of asking them
to look.

---

## Stages B + C · The user filters and schedules (you're not involved)

Tell the user it's two steps, both done on the same page:

**Filter first**

- In the shortlist, mark each place **want / maybe / skip** — picking "skip"
  allows noting a reason
- Switch to the map anytime to see the spread; markers recolor the moment a
  choice changes, **no need to come back to you**

**Then schedule** (map view, middle pane)

- The day-plan pane is pre-built from the trip dates; nothing to create
- Put a place into a day: **drag it from the shortlist**, or select the day and
  **click the place's dot**
- Reorder within a day: drag, or use the ↑ ↓ on the entry
- The map links each day's points in visit order with a dashed line in that
  day's color — **detours are visible at a glance**
- A place may appear on multiple days (two consecutive Expo days) or twice in
  one day (daytime and night views)
- Flight lands in the evening? Click `+` in the day-plan header to add "Day 0"

**Don't tell the user to hit save.** Under a `--serve` server, changes auto-write
back to `places.json` after a few idle seconds; status shows at the bottom of the
page. Only `file://` needs the "Save choices & schedule" button (browsers won't
let a page write files without a user gesture); browsers without direct write
fall back to "Download JSON" or "Copy code".

In the code, the `+ ? -` lines are choices and the `D1 D2 …` lines are the
schedule (**in-line order = that day's route order**, `(parentheses)` are notes).
When the user pastes a code back, update `choice` and `itinerary` in
`places.json` from it, then rebuild.

Then **stop and wait**. Don't filter or schedule on the user's behalf — what to
cut and which day to go are trade-offs, not computations; they belong to the
user.

When the user says they're done: re-read `places.json`, confirm the `choice`
distribution and `itinerary`, then move to D. If the distribution contradicts
the declared interest weights (a Low category heavily wanted, a High one
heavily skipped), mention it once in conversation — but **never write
`preferences.md` from stage-B data**. Choices measure attraction, not
experience; only the post-trip retro earns write access.

---

## Stage D · Design the route

Read **[references/route-design.md](references/route-design.md)** for the full
rules.

**When `places.json` has an `itinerary`, write to it — do not regroup.** That is
the user's own day assignment and ordering; overriding it throws away the
trade-offs they just made. If you disagree, say so in the guide body and let them
change it. Only when `itinerary` is missing or entirely empty do you propose one
using the rules below. And hard rule 4 applies at every stage, not just here:
any itinerary edit — add, remove, reorder, re-day — is proposed with the
concrete before/after and applied only once the user agrees.

Key points:

- Cluster by `area`; **at most 1–2 areas per day**
- Exclude conflicts with `closed_days`; put `night: true` places in the evening;
  draw rain alternatives from `indoor: true`
- Transport numbers are looked up, never estimated — and the lookups can go
  to a subagent while you write (route-design.md, "Delegate the lookups");
  you keep the segment planning and write the table yourself
- Write to `trips/<trip>/route.md` in Markdown
- List items starting with `09:30 ` render as a timeline automatically — **no
  special syntax**
- **Don't** hand-write the cost summary or the place-by-place table in
  `route.md` — the page generates them from the data, guaranteed correct
- **`---` is a page break.** The guide is laid out on A4 sheets by default and
  always prints that way. Put a `---` between sections that shouldn't share a
  sheet, and aim each section at one sheet — roughly 1,300–1,500 CJK
  characters. Page count is not fixed; type size is the same on every sheet

Rebuild when done:

```bash
<PY> <SKILL_ROOT>/scripts/build.py trips/<trip> --serve
```

To share the guide alone (without the filtering UI):

```bash
<PY> <SKILL_ROOT>/scripts/build.py trips/<trip> --standalone   # outputs guide.html
```

The guide view also exports itself as Markdown (`guide.md`): `route.md`'s body
verbatim — build.py embeds the source alongside the rendered HTML for exactly
this — followed by the schedule and the checklist rebuilt from the user's
current choices. That is the form to hand back to an AI; the built page is
~600KB, most of it template.

---

## File layout

```
<trips_root>/2026-09-osaka/          # root: see "Where trip files live"
├── brief.md          # trip parameters (answers to the opening questionnaire)
├── places.json       # ★ the single source of truth; every view renders from it
├── transit.geojson   # metro lines & stations (from enrich.py --transit)
├── route.md          # guide body (you write this)
└── trip.html         # build artifact — never hand-edit
```

`places.json` is the single truth. User choices update its `choice` fields in
place — no side files — so the shortlist and the map can never disagree.

`trip.html` is a **snapshot at build time**: it's self-contained (share it with
travel companions; they double-click and it works, no server, no repo), but they
see the data as of that build — including every "skip" reason. The user's later
in-browser changes live in their own localStorage, **not in the file**; nobody
else can see them. So rebuild after every `places.json` write — the `--serve`
server already does this automatically on save.

---

## Language rules

**UI language of the trip page**: follows `trip.output_language`. `zh*` gets the
built-in Chinese interface, everything else gets the built-in English one. For
any other language, translate the template's `I18N.en` table into a top-level
`ui` object in `places.json` when creating the trip — contract and example in
[data-schema.md](references/data-schema.md), section "ui". Weekday/date names
localize automatically via `Intl`; no work needed there.

**Body text (`pitch` / `detail` / `route.md`)**:

- Body text uses place names in **the user's language**.
- Where the local language differs, write "user-language name (local-language
  name)" on **first** occurrence in the body; after that, the user-language name
  alone.
- The local-language name must be **findable on the map**; the user-language
  name must be natural, readable, and consistent throughout.
- With no established translation, transliterate or translate freely — but
  **never mix multiple renderings** of the same place in one document.

---

## Pre-delivery self-check

Once `validate.py` is at zero P0, **spawn the verify subagent** — prompt from
[references/verify-agent-briefing.md](references/verify-agent-briefing.md).
It re-opens sources with fresh eyes (you checking data you wrote repeats
your own misreadings) and handles the web-facing checklist items in the
background while you do the one thing it can't: open the built page and look
at the render. Adjudicate its findings — it's briefed to over-report — fix
what's real, then finish the checklist. No subagent capability? Run every
check yourself, as before.

Run through **[references/checklist.md](references/checklist.md)**, especially:

- [ ] `validate.py` reports zero P0
- [ ] Spot-check 3–5 places by **manually opening the links in `sources`** to
  confirm the facts
- [ ] Actually opened the page in a browser (not just read the code)
- [ ] The guide's ✅❌ table matches the user's `choice` values (auto-generated,
  but confirm it rendered)
- [ ] Explicitly told the user which information may go stale and which numbers
  are estimates

One more beat at first-trip delivery: if `preferences.md` is still mostly
`<placeholders>`, offer — don't push — "two minutes now to fill the interest
weights, and the next trip starts sharper." This is the moment they best know
what they'd adjust; there is no other designated point where the initial fill
happens.

---

## Known limitations (state them proactively; don't be vague)

The single authoritative list — every limitation worth stating at delivery,
with how to phrase it — is [checklist.md](references/checklist.md), section
"Must be stated at delivery"; it is read before every delivery anyway, and
keeping one copy stops the lists from drifting apart. The one limitation
that also shapes earlier work is documented where that work happens:
`file://` degradation, in "Stages B + C" above.

---

## Updating this skill

When the user asks whether or how to update this skill, read
[references/updating.md](references/updating.md) **before answering** — the
order of operations there matters (reassure about user data first, detect
local edits, then merge the directory as one unit).

---

## Resource guide

| File | When to read |
|---|---|
| [references/data-schema.md](references/data-schema.md) | Before writing `places.json` — required |
| [references/research-playbook.md](references/research-playbook.md) | Before stage-A searching — required |
| [references/subagent-briefing.md](references/subagent-briefing.md) | When spawning stage-A search subagents |
| [references/image-agent-briefing.md](references/image-agent-briefing.md) | When spawning the A3 image subagent |
| [references/verify-agent-briefing.md](references/verify-agent-briefing.md) | When spawning the pre-delivery verify subagent |
| [references/route-design.md](references/route-design.md) | Before stage-D routing — required |
| [references/checklist.md](references/checklist.md) | Before delivery |
| [references/updating.md](references/updating.md) | When the user asks to update this skill |
| `scripts/enrich.py` | Fill coordinates & images, after the `places.json` body is written |
| `scripts/validate.py` | After every `places.json` change |
| `scripts/build.py` | Generate/update the page |
