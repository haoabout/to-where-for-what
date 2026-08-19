# Pre-delivery checklist

Graded P0 / P1 / P2. **If any P0 fails, do not deliver.**

Every item comes from a mistake actually made.

---

## 🔴 P0 · No delivery until these pass

### 0-1. `validate.py` reports zero P0

```bash
<PY> <SKILL_ROOT>/scripts/validate.py trips/<trip>/places.json --check-links
```

(`<PY>` is the Python command probed once per conversation — see SKILL.md,
"Which interpreter runs the scripts". Never hardcode `python3`.)

Exit code must be 0. P0s are the problems that break the page or mislead the
user.

### 0-2. Spot-check source links by hand

Pick 3–5 places at random and **actually open the URLs in `sources`** to
confirm:

- The link opens (you didn't invent it)
- The page really is about this place
- Hours and tickets match what you wrote

The validator can only confirm a URL is reachable — **it cannot confirm the
content is true**. Only a human pass does that.

### 0-3. Actually opened the page in a browser

Not reading the code — **actually opening it**. This step has caught:

- Markdown paragraphs split line by line, shredding the body text
- `[hidden]` overridden by CSS, so the standalone page still showed a tab
  pointing at a deleted view
- Every thumbnail empty

**Reading DOM attributes and seeing rendered output are different things.**
`el.hidden === true` doesn't mean it isn't displayed — check
`getComputedStyle(el).display`.

While the page is open, also confirm the guide's ✅❌ table matches the user's
`choice` values — it's generated from the data, but "generated" still has to
have rendered.

### 0-4. Every `status` was confirmed

Not one filled in as `open` because it "looked like it should be". This is the
only mechanism against "arrived to find it under renovation".

**The official homepage must have been fetched.** Long-term renovations and
temporary closures only appear in the homepage news list, while the
visitor-info page keeps stating normal hours. Observed: the Museum of Oriental
Ceramics' info page said "9:30–17:00" while the homepage announced a long-term
closure from 2026-08-03. Reading only the former schedules a shut museum.

### 0-5. No closure-day / trip-date conflicts

The validator blocks "closures cover the whole trip", but **partial conflicts
are yours to schedule around**: a place closed Mondays on a trip containing a
Monday must land on another day.

**A public holiday in the window changes the rules themselves** — schedule
against the holiday-adjusted closure, not the weekday one. "Closed Mondays,
following day when Monday is a holiday" moves the closure onto Tuesday, and
year-end / New Year style periods shut venues for a stretch that no
`closed_days` weekday list expresses.

### 0-6. Coordinates inside the destination

The validator uses `bbox`. But also eyeball the map view — **an obviously
unreasonable spread** (one point alone out at sea) usually means a same-name
mismatch.

---

## 🟡 P1 · Handle these; skip only with a real reason

### 1-1. Category quotas met, or the shortfall honestly explained

Below-minimum categories require saying "the city genuinely has no more" —
never silently under-deliver. **Never fabricate places to pad.**

### 1-2. No mislabeled images

Batch image fetching mislabels easily, so every kept candidate gets looked at.
The image subagent normally does this. **Doing it in the main conversation
instead: judge from the saved files, not the URLs** — each audit candidate
whose bytes are on disk carries a `file` path relative to the trip directory,
under `image-review/`. **Read them in batches of 10–15 per turn**; one Read per
turn is what makes this pass feel expensive.

### 1-3. Image URLs came from the API, not hand-assembled

Wikimedia no longer generates thumbnails at arbitrary widths; a hand-built
`800px-` returns 400. See [research-playbook.md](research-playbook.md).

### 1-4. Every micro-spot has a `parent_id`

Otherwise they compete with major places for slots and drown the shortlist.

### 1-5. Data freshness

When `verified_at` is more than 30 days old the page shows a staleness warning.
When continuing on old data, **re-verify opening hours first**, then route.

### 1-6. The route clusters sanely by `area`

Three or more non-adjacent areas in one day is almost always a bad route. Redo
it.

### 1-7. Each day's final place has `last_entry`

Don't let the user rush over full of hope after last entry has passed.

### 1-8. Tier distribution isn't inflated

Roughly `S` ≤ 12% and `S + A` ≤ ⅓ of the list. Over that, everything looks
important and the tier stops helping anyone filter. The fix is re-grading
against the detour ladder in [research-playbook.md](research-playbook.md) —
never nudging a number to clear this line.

---

### 1-9. The festival / public-holiday check actually ran

Not "no `event` places, so presumably nothing was on". Either name the
festivals that fall in the window with their dates, or state plainly that
none do — and either way, the public-holiday conclusion is in `trip.note`.
An empty `event` category that nobody checked and one that was checked and
came up empty look identical in the data; only this item separates them.

---

## 🔵 P2 · Nice to have

### 2-1. `photo_note` specific to position and time

"Beautiful scenery" carries nothing. "Best angle across the lawn from
Nishinomaru Garden, front-lit in the morning" does.

### 2-2. Copy gives grounds for judgment, not adjectives

Touristy, overrated, expectations to temper — **say it straight**. The user
needs information to trade off with, not a brochure.

### 2-3. The guide leaves slack

Rain swaps, what to cut when short on time, where the `maybe`s slot in.

---

## Must be stated at delivery

Without these, the user forms wrong expectations:

- [ ] **Which information can go stale** — hours and prices change; reconfirm
  before departure
- [ ] **Ticket amounts are estimates** — special exhibitions, add-on
  experiences, and night surcharges usually cost extra
- [ ] **If the model has no vision capability**: say that images passed text
  checks only, not visual review — a wrong-looking photo spotted while
  filtering is worth reporting; swapping is cheap
- [ ] **What is provisional at v1, and what the two passes changed by the end**
  — at the v1 handover: the photos are picked but not yet eyeballed, and a
  separate pass is re-confirming hours and closing days against the sources. At
  final delivery: what those two passes actually changed — which photos were
  swapped, which facts moved — or plainly that neither changed anything. A
  silent second delivery reads as "nothing happened", which is the one thing it
  never means
- [ ] **How the images were reviewed** (final delivery) — the places whose
  photo a source vouched for (`review: "glance"` in `image-audit.json`) got an
  identity spot-check, not a per-image deep review; only the rest were audited
  one by one. Give the split as a count, so a wrong-looking photo reads as
  something to report rather than something already ruled out
- [ ] **Which festivals fall in the window, and what the public holidays do**
  — or, explicitly, that none do. Without the explicit "none", the user can't
  tell a quiet fortnight from an unchecked one
- [ ] **Weather beyond 16 days is a historical average, not a forecast**
- [ ] **After the server stops**, double-click opening still reads fine, but no
  direct file writes and no OSM raster basemap
- [ ] **Transit-line quality varies by city** — lines and official colors come
  from OSM's `colour` tag; where a city lacks them the map falls back to
  auto-assigned colors and says so in the legend
- [ ] **The page's own transport numbers are route planning, not a timetable**
  — the per-leg walk/drive times the "generate transport" button produces come
  from an OSM routing engine: real queries, so real numbers, but they answer
  "how long does this take", never "when does the next one leave". The guide's
  transit table is the timetable-backed one; sitting in the same page they look
  alike, and only saying so keeps them apart. Mention too that the button calls
  a free public service, so it can be down or slow — legs it can't route fall
  back to a straight line and lose nothing else
- [ ] How many places remain **undecided** — want another look?
- [ ] **First trip only**: if `preferences.md` is still mostly placeholders,
  offer — don't push — "two minutes now to fill the interest weights, and the
  next trip starts sharper". This is the moment the user best knows what
  they'd adjust; there is no other designated point for the initial fill

---

## Quick failure lookup

| Symptom | Most likely |
|---|---|
| Map entirely blank | Basemap fell back; check the degradation notice at the page bottom |
| Map shows gray tiles reading "Access blocked" | Opened via `file://` with the OSM basemap. Use `--serve` |
| Guide tab won't open | `route.md` missing or empty |
| Page content not updating | After editing `places.json` / `route.md`, rerun `build.py` |
| Cost total clearly too low | `ticket` contains unparseable text; see the "not counted" line |
| A place missing from the shortlist | Probably `scale: "spot"`, folded under its parent |
