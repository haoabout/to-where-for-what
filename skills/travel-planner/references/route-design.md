# Stage D · Route design and guide writing

Input: `places.json` (with the user's `choice` filled in) + `preferences.md`
Output: `trips/<trip>/route.md`

---

## Three things first

### 1. Tally the filtering result

```
want N · maybe M · skip K · undecided J
```

- **When `itinerary` is already arranged, it wins** — the user may well have
  scheduled several "maybe"s into real days and left a "want" out. That's their
  trade-off.
- **Only when `itinerary` is empty do you propose one**: schedule only `yes`;
  treat `maybe` as alternates, mentioned in the body as "add if time allows",
  never on the main line.
- Treat undecided as unselected, but mention at delivery: "J places are still
  undecided — want another look?"
- If `yes` clearly can't fill the days, **tell the user first**; don't force it.

### 2. Cluster by `area`

This is what route quality hinges on. **At most 1–2 areas per day** —
criss-crossing the city is the classic bad route.

Group the `yes` places by `area`, then merge adjacent areas into day units. The
home bases (`trip.bases`) set each day's start and end points.

### 3. Check the hard constraints

| Constraint | Source | Handling |
|---|---|---|
| Closure days | `closed_days` vs trip dates | The place must go on a day it's open. **This often locks the dates of a whole area** |
| Booking required | `booking: "required"` | Flag prominently in the body, give `booking_url`, say how far ahead to book |
| Night value | `night: true` | Schedule at the end of its day |
| Last entry | `last_entry` | **Must** be stated for each day's final place — don't let anyone rush over for nothing |
| Renovation / closed | `status ≠ open` | Shouldn't be in the route; if the user chose it anyway, explain in the body |

Closure-day conflicts are usually what determines the route's skeleton — solve
them first, then arrange everything else.

---

## Guide structure

Write `route.md` in this order:

```markdown
# <Destination> in N days

## Route logic
## Day 1 · M/D (Weekday) · <theme of the day>
## Day 2 · …
## Transport
## Light & photography
## Caveats
```

**Don't** hand-write a "cost summary" or an "all-places table" — the page
generates both from `places.json`, always in sync with the data. Hand-written
copies duplicate them and eventually contradict them.

Both blocks follow `itinerary`, not `choice`:

- **Costs** are grouped by day and only count scheduled places (a place on two
  days is one ticket). A place marked "want" but scheduled nowhere costs
  nothing and must not be counted.
- **The table** lists the schedule day by day on top and the unscheduled below;
  places marked "want" but scheduled nowhere are called out as warnings.

### Route logic (required at the top)

One short passage on **why the days are split this way**, so the user can judge
the reasoning. Cover:

- Which areas each day covers and why they're grouped so
- Which hard constraints fixed the order (closures, night views, bookings)
- **Estimated daily walking distance with an intensity verdict**, checked
  against the user's `pace` setting

Example:

> The two days split into a north-island line and a south-city line that never
> cross. The three Nakanoshima points are 5–10 minutes' walk apart and belong
> in one day. Two hard constraints fixed the order: the Nakanoshima Library
> closes Sundays, so it must be 9/12 (Saturday); Hōzenji Yokochō and Ebisubashi
> want to be seen at night when the lanterns are lit, so they close out day
> two. Estimated 9–11 km of walking per day — moderate, within the
> "12 km/day acceptable" setting.

### Daily timeline entries

Use a list, **starting with a time** — it renders as a timeline automatically:

```markdown
- 09:30 · Enter Osaka Castle Park from the east; follow the moat to Gokurakubashi. Entering the keep right at opening dodges the tour groups.
- 12:30 · Tanimachi line, transfer to Keihan, to Yodoyabashi. Lunch around Kitahama.
- 14:00 · Nakanoshima Library. **30 minutes is enough** — the central-hall dome is the point.
```

Time format `HH:MM` or `HH:MM–HH:MM`, followed by `·` or a space. **No special
syntax needed.**

Every node includes: **how to get there** (down to the line name), **how long to
stay**, **what to watch out for at this stop**.

Not a bare log. "10:00 arrive A, 11:00 arrive B" has no value; write **why this
order**, **what to do first on arrival**, **when it's least crowded**.

### Transport

**Lines, transfer stations, transfer counts, durations, and fares must be
looked up item by item. No estimating.**

This is hard rule #3 applied to transport. Place data has `sources` and a
validator backstopping it; the transport table has nothing — once you start
estimating, estimated numbers and verified numbers look identical in the same
table and the user can't tell. It actually happened: four segments estimated on
intuition — two wrote a 2-minute hop as 15 minutes (5× off, skewing the whole
timeline), one fare ¥110 over, one ¥130 under, and "3 transfers", the fact that
actually shapes the experience, never appeared at all.

**Japan**: use Yahoo! Transit; the result page takes URL parameters directly, no
login:

```
https://transit.yahoo.co.jp/search/result?from=<origin>&to=<destination>&y=2026&m=09&d=13&hh=08&m1=3&m2=0&type=1&ticket=ic
```

`from`/`to` are URL-encoded station names; `ticket=ic` returns IC-card fares.
The page returns lines, transfer stations, transfer counts, duration, fare, and
stop counts. In other countries, find the local official or mainstream transit
planner.

Lay the table out like this:

| Segment | Lines & transfers | Transfers | Duration | IC fare |
|---|---|---|---|---|
| Umeda → Nanko ATC | Midōsuji line → [Hommachi] Chūō line → [Cosmosquare] New Tram | 2 | 33–35 min | ¥290 |

**The table footer must state the query source and date**, plus a reminder to
re-check before travel — timetables and fares change, and the trip is often
weeks away.

**No number without a lookup.** Segments that can only be estimated (walking
legs) get an explicit "**estimate**" in the cell — never let them blend in with
verified numbers.

**Use the station people will actually start from.** "From Nakanoshima to
Umeda" sounds like one fact, but from Yodoyabashi at the island's east end it's
a 2-minute direct ride on the Midōsuji line, while from Keihan Nakanoshima
station at the west end it's 23 minutes with a transfer — a tenfold difference.
Pin down where that day actually starts first.

**Look for better routings while you're at it.** Lookups regularly surface
options intuition misses: the line outside the hotel isn't necessarily optimal —
a small detour may save a transfer, halve the fare, or land inside a day-pass's
coverage. When you find one, put it in the body and say why.

Then give **pass advice**: the day pass's real price (weekday/weekend often
differ), which lines it covers and **which it doesn't**, then sum the day's
actual segment fares to show whether it pays off. Prices and coverage also come
from the official site, never from memory.

Cover arrival and departure transport too — airport/station to the home base.
If the lodging runs a free shuttle or similar, confirm the schedule and
conditions on the official site (typical limits: guests only, per-run capacity).

### Light & photography

Pick from the high-`photo_index` places, **ordered by best time slot**, and say
why that slot. This module is explicitly requested in the user's preferences.

### Caveats

Only what **genuinely needs care**: closure-day traps, pickpocket zones,
cash-only places, expectation management.
No filler like "stay safe" or "mind your belongings".

---

## Weather

The page **fetches Open-Meteo live in the browser** — fresh on every open; you
don't write weather into `route.md`.

But understand its behavior so you can explain it at delivery:

- Trip within **16 days** → a real forecast
- Beyond 16 days → falls back to the **same-period average of the past 8
  years**, labeled "not a forecast" in the UI

If the trip falls in a rainy season, add a **rain plan** paragraph under
"Caveats" — drawn from the `indoor: true` places.

---

## Alternates and slack

A good guide leaves room:

- **Rain swaps**: one `indoor: true` substitute per day
- **What to cut when time runs short**: name the skippable place — don't make
  the user guess
- **Where the `maybe`s fit**: "if X only took an hour, Y is on the way"

---

## After writing

```bash
python3 <SKILL_ROOT>/scripts/build.py trips/<trip> --serve
```

Then **actually open the page and look**:

- [ ] The timeline renders (time capsules appear)
- [ ] No table overflows
- [ ] Cost-summary numbers are sane (`ticket` is free text; unparseable ones are
  listed separately)
- [ ] The table's ✅❌ match the user's choices
- [ ] The weather card appears, in the right mode (forecast/average)

To share the guide alone (without the filtering UI):

```bash
python3 <SKILL_ROOT>/scripts/build.py trips/<trip> --standalone
```
