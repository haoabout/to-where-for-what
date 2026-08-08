# Stage A · Research playbook

Goal: a `places.json` with 35–50 places, every one carrying **opening
information verified in the first pass**.

The core quality bar: **every choice the user makes off this list must be a
valid one.** If they pick "want to go" and it turns out the place is closed that
day, under renovation, or requires booking a month ahead, the whole filtering
round was wasted.

---

## Category quotas

Total lands in **35–50**, allocated per the table. This guarantees "every
category has options" rather than "30 museums".

| Category id | Label | Min | Max |
|---|---|:--:|:--:|
| `landmark` | Classic landmarks | 3 | 6 |
| `museum` | Museums · galleries · art spaces | 3 | 8 |
| `hidden` | Hidden gems · off-beat corners | 5 | 10 |
| `media` | Film & anime locations | 2 | 6 |
| `architecture` | Architecture · districts · night views | 3 | 7 |
| `shrine` | Temples · shrines · churches | 2 | 6 |
| `nature` | Nature · parks · observation decks | 3 | 6 |
| `market` | Markets · shopping streets · distinctive retail | 2 | 5 |
| `food` | Dining & cafés with scene value | 2 | 5 |
| `event` | Limited-run events · exhibitions · seasonal | 0 | 6 |

Write the `label` values in the user's language. Quotas may be tuned to the
destination's character, but **never silently** — if you adjust, say so at
delivery.

### What about small cities

When a quota can't be met, in order:

1. **Say so honestly**: "this city only has 2 art museums; both are included."
   **Never fabricate places to pad.**
2. Expand to the **1-hour-drive circle**; tag those points `day-trip` and state
   the travel time in `pitch`.
3. Still short? Lower the total target and say plainly at delivery: "this
   destination has only 28 places worth going."

### `event` (limited-run) is special

Its quota starts at 0 because it's **only meaningful once travel dates are
known**. Current exhibitions must be looked up online, never recalled from
memory. Record each exhibition's start/end dates and confirm they cover the
user's trip days.

---

## Information that must be in the first pass

Without these fields, the user's filtering is wasted:

| Field | Why first-pass |
|---|---|
| `hours` / `closed_days` / `closed` | "Filtered for an hour, then found it closed" is the worst experience |
| `booking` / `booking_url` | A booking-required place decided on spontaneously = a place you can't get into |
| `ticket` | Affects trade-offs; also feeds the cost summary |
| `status` | The cure for "arrived to find it under renovation" |
| `coord` | Needed by the map and route clustering |
| `sources` | The main anti-hallucination gate |

Left for stage D: exact walking routes inside venues, gallery-level detail,
same-day weather adaptation, specific camera angles.

---

## Search strategy

### Where a place's information comes from

Priority, high to low:

1. **The official site** — the only authority on hours, tickets, closure days,
   booking
2. **The official tourism bureau** (e.g. osaka-info.jp, gotokyo.org) — when the
   site is down or doesn't exist
3. **Wikipedia** — history, architecture, background, but **never trust its
   opening hours** (updates lag)
4. Everything else — for discovering places only, never for verifying facts

### Fetch at least two pages per place: the homepage + the visitor-info page

**A lesson paid for twice in testing.**

| Page | Provides | Missing it means |
|---|---|---|
| **Official homepage** | **Notices**: long-term renovation, temporary closure, between-exhibition gaps, special-exhibition dates | Scheduling a venue that's under renovation as if open |
| Visitor info / access page | Regular hours, closure days, tickets, booking | No canonical information; you'd be guessing |

Real case: the Museum of Oriental Ceramics, Osaka, has a `/guide/info/` page
reading "9:30–17:00, closed Mondays" — perfectly normal — while the homepage
news list carries

> 2026.05.19　2026（令和８）年８月３日（月）から、改修工事のため休館いたします

**The museum closes long-term from August.** Fetch only the visitor-info page
and you'd recommend a closed museum as operating.

So: **after the visitor-info page, always fetch the homepage too**, and search
the text for words like `休館` `改修` `工事` `リニューアル` `closed`
`renovation` (use the local language's equivalents). When you find a notice,
check whether its dates overlap the trip.

### Search snippets are not a source

**Only an actually fetched page counts.** Observed: for Tekijuku's admission, a
search snippet said ¥260; the official page says「一般　400円」. Snippets can
come from stale caches or third-party reposts.

When the page can't be fetched (404, SSL failure, JS-rendered), write `null` and
note it — **never fill the gap with a snippet**.

### Unverifiable ≠ replace, and definitely ≠ delete

**This is the easiest step to get wrong.**

Observed counterexample: a ferris wheel — operator subpage 404, dedicated domain
unreachable, the tourism-bureau page returned HTTP 200 whose content was a 404
error page, and second-hand prices ranged ¥700–¥1300. The handling at the time
was to **swap it for a different, easier-to-verify attraction** — wrong. The
user never learned the option existed, and "I couldn't verify it" is not "it
isn't worth going". **That's making the user's decision for them, then hiding
that a decision was made.**

The correct handling: **keep the place**, then

1. Fill the fields you could confirm; put `null` in the ones you couldn't
2. Add a `verify` field (structure in [data-schema.md](data-schema.md)):

```jsonc
"verify": {
  "state": "blocked",
  "note": "Operator subpage 404 (tried http and https); dedicated domain unreachable; tourism-bureau page returns 200 with a 404 body. Second-hand prices disagree (¥700–¥1300), not trusted.",
  "check": ["opening hours", "ticket price", "any temporary closure"]
}
```

3. Put the official URLs **you attempted** in `sources` — the user needs them to
   check for themselves

The page gives such entries a hatched border, a prominent badge, and a
"needs your confirmation" filter button. Once the user checks and reports back,
the AI fills in the data and sets `state` back to `verified`.

**Only one situation justifies exclusion**: cross-verification confirms the
place is **permanently closed or doesn't exist**. That's
`status: permanently_closed` — state it honestly rather than silently
disappearing it.

### A domain that looks official ≠ the official site

Observed: `konjyakukan.com` looks exactly like the domain of the Osaka Museum of
Housing and Living — it's a placeholder template site whose body literally reads
「ここにメインのコンテンツを記述します。」("write the main content here"). The
real site is at `osaka-angenet.jp`.

**Always glance at whether the page body is actually about this place** — a
plausible domain proves nothing.

### Exhibition runs are high-value information

For museums and galleries, beyond the regular opening info, check **what's on
during the trip**:

- Does the special exhibition's run cover the trip days?
- Is it in a **between-exhibitions gap** (previous show closed, next not open —
  only the permanent collection, or the whole venue shut)?
- Is the special exhibition **timed-entry / lottery**, and has the lottery
  already closed?

Observed case: Nakanoshima Museum of Art ran a Vermeer "Girl with a Pearl
Earring" special exhibition 2026-08-21 – 09-27, but general sales had switched
to a lottery that closed on 7/21 — unknowable without checking. Put this kind
of information in `pitch` or `detail`, and price `ticket` at the
special-exhibition rate.

### How to find hidden gems

Searching "top attractions in X" only returns the same ten everyone knows.
Angles that work:

- Search **architects**, **construction eras**, **architectural styles** — digs
  up masses of overlooked buildings
- Search in the **local language** — far richer than English or your own
- Search terms like **"locals' favorite" "穴場" "地元民" "known only to locals"**
- Walk the **surroundings** of known places (official sites often list "nearby")
- Check official registries: **important cultural properties / registered
  tangible heritage / historic building lists**
- Hunt these types: **industrial heritage, old libraries, old banks, old
  markets, covered arcades, observation decks**

### Micro-spots (`scale: "spot"`)

A tree, a camera angle, a signboard — worth including, handled properly:

- `scale` is `"spot"`, `parent_id` points at **the major place in the same
  area** (required; the validator enforces it)
- The shortlist folds it under its parent so it doesn't compete for a slot
- The `pitch` **says outright that it's a photo stop**: "it's one camera
  position; five minutes and done; only worth it in passing"
- `duration_min` 5–15

Never promote a micro-spot as a headliner — and never skip one for being small;
along-the-way bonuses have real value.

---

## Anti-hallucination

### `sources` is a hard gate

Every place needs at least one real `http(s)` URL. The validator blocks empty or
malformed values, but **it can't stop you from inventing a plausible-looking
URL**.

Rule: **only write URLs you actually visited.** If the fetch failed, find
another source — or don't include the place.

### Never guess `status`

Without online confirmation, `open` is forbidden. It's the only mechanism
preventing "arrived to find it under renovation".

### Images: let the script's chain run first, then fill gaps by hand

`enrich.py --images` tries three sources in order and stops at the first hit:

1. **Wikipedia lead image** — most representative, rarely mislabeled
2. **Wikidata P18** — catches items with no Wikipedia article (small
   galleries, markets); only accepted when the entity's coordinate falls
   inside the trip bbox, so same-name entities elsewhere can't sneak in
3. **Openverse keyword search** — aggregated CC photos (Flickr etc.), no API
   key; highest mislabel risk, hence last

When the whole chain comes up empty — typical for small venues — **fill
`images` manually with a direct link from an official page**: the venue's own
site or official social account (og:image, a press-kit photo). Two conditions:
the URL actually loads (fetch it, don't assume), and the photo shows *this*
place. This is a personal-use tool, so the licensing posture is pragmatic —
but keep `credit` honest about where the image came from. Truly nothing
anywhere? Leave it empty; images are optional, wrong images are not.

### Wikimedia thumbnail URLs specifically: API only, never hand-assembled

**Tested lesson**: Wikimedia no longer generates thumbnails at arbitrary widths
on demand. Hand-building an `800px-` prefix gets a 400.

| Width | 220 | 320 | 480 | 640 | 800 | 960 | 1024 | 1280 |
|---|---|---|---|---|---|---|---|---|
| Result | 400 | 400 | 400 | 400 | 400 | **200** | 400 | **200** |

The right way — the Commons API's `iiurlwidth`, which snaps to a width that
actually exists:

```
https://commons.wikimedia.org/w/api.php?action=query&titles=File:<filename>
  &prop=imageinfo&iiprop=url|extmetadata&iiurlwidth=800&format=json&formatversion=2
```

Use the returned `thumburl` directly. `extmetadata` carries `Artist` and
`LicenseShortName` — put them in `credit`.

**Also eyeball every image.** Category-based fetching and keyword search
(Openverse) mislabel easily — the first file in `Category:Osaka Castle` may be
something entirely unrelated. After a batch fetch, tile them into one contact
sheet and scan it; far faster than opening them one by one.

### Things the validator catches — but you should catch earlier

Before running `validate.py --check-links`, think through:

- Do the coordinates fall inside the destination? (Hitting a same-named place in
  another city is a classic error)
- Could lat/lon be swapped? (The object form prevents the swap, but the values
  themselves can still be wrong)
- Are any two entries actually the same place?

---

## Getting coordinates

Use Nominatim (OSM's official geocoder), **respect the 1 req/s policy**, and
send a descriptive User-Agent:

```
https://nominatim.openstreetmap.org/search?q=<local-language name>&format=json&limit=1&accept-language=<local language>
```

The **local-language name** has the best hit rate. When it misses, try something
more specific (「戎橋」 finds better than「グリコサイン」).

Check the returned `display_name` against the destination's administrative area
— that's where "wrong city" errors surface first.

---

## Grading: `tier` and `photo_index`

Both are judgment calls, which is exactly why they need anchors. Without them
the same city researched twice comes back with two different S lists — each
internally consistent, neither reproducible.

### `tier` — how much of the trip is this worth?

Grade on one scale: **how much detour the user would accept for it.** That's a
question you can simulate and get a single answer to, unlike "is this
excellent".

| Tier | Worth… |
|---|---|
| `S` | Its own half-day, and there's no substitute elsewhere — missing it is a reason to come back to this city |
| `A` | A 20–30 minute detour, or a dedicated half-day slot |
| `B` | Going into when already in that area — but not a detour |
| `C` | A glance in passing, 5–15 min; skipping it costs nothing |

The subject of "worth" is **this user**, not a generic tourist. A person who
genuinely loves modern architecture really would detour 30 minutes for one
building; that isn't grade inflation, it's the fact.

This is the same trade-off stage D makes when routing
([route-design.md](route-design.md)) — one scale, used twice.

#### Preferences move a tier at most one step

Set the base tier for "a traveler who likes this category", then adjust from
`preferences.md`. **One step total, and adjustments don't stack:**

| Trigger in `preferences.md` | Effect |
|---|---|
| Category or named subject under **High** interest | +1 |
| Under **Low** interest | −1 |
| Under **Not interested — don't recommend** | Leave it out entirely |
| Photography marked very important **and** `photo_index` ≥ 4 | +1 |
| Breaks a hard constraint — over the ticket threshold, on the "must avoid" list, needs booking further ahead than they accept | Cap at `B` |

The one-step ceiling is the point of the rule: matching the user's taste can
lift a strong place to `S`, but it can never make a mediocre one `S`.

**No preferences file, or one still full of `<placeholders>`** (first-time
user): use the base tier and stop. Don't invent a taste profile.

#### What `tier` is not about

Opening hours, closure days, booking lead time, weather, whether it's even open
on the trip dates — that's **availability**, and it's already carried by
`closed_days`, `status`, and the page's filters. A superb place that's shut both
days stays `S`; `pitch` says it's shut. Fold availability into the tier and the
scale stops meaning anything.

#### Distribution check

In a 40-place list, expect roughly `S` ≤ 5 and `S + A` ≤ 13 (≈12% and ≈⅓). Over
that, the ruler has gone soft — re-grade, don't rationalize. Under it is fine
and needs no explanation.

The reason for a tier belongs in `pitch`, which already has to give grounds
rather than adjectives — there's no separate field for it.

### `photo_index` — 1 to 5

| Score | Meaning |
|---|---|
| 5 | The composition is already there — stand in the right place and it works |
| 4 | Reliably good, but you pick the angle or wait for the light |
| 3 | A decent shot exists if you go looking for it |
| 2 | Photographable, nothing more |
| 1 | Nothing to shoot; you come for other reasons |

**This one describes the place, not the user** — no preference adjustment. The
user's interest in photography enters through the tier `+1` rule above, and
double-counting it here would apply the same input twice.

The number surfaces in the detail dialog, in that `+1` rule, and as the
tiebreak that orders places within a tier — **not** on the shortlist card. An
inflated 5 quietly reorders the shortlist and can lift a tier; it isn't
decoration.

---

## Writing the copy

`pitch` (one line) and `detail` (two or three paragraphs) decide whether the
user can make good trade-offs.

### The division of labor

| | `pitch` | `detail` |
|---|---|---|
| Answers | Do I want this at all? | I want it — now what do I need to know? |
| Holds | The one judgment that decides want / skip, plus any dealbreaker | Background, history, what to see inside, caveats, comparisons |
| Length | **Under ~3 card lines** — about 80 CJK characters or 160 Latin ones | Two or three paragraphs |

The card clamps `pitch` to three lines. The detail dialog then repeats it in
full as a lede above `detail`, so nothing is ever unreachable — but a hook that
never fits its own card has stopped being a hook and is turning into a second
`detail`. `validate.py` raises a P2 when it overflows.

The commonest way this goes wrong: packing the pitch with facts that belong in
`detail` (founding year, floor count, full opening caveats) instead of the one
sentence that settles the decision. Background goes down; the verdict stays up.

**Be honest.** If a place is heavily touristified, say so:

> Honesty required here: over the past decade this market has been thoroughly
> remade for tourists — many stalls now sell grilled-seafood street food at
> prices well above an ordinary market. It still works as a place to look and
> shoot; as a place to eat economically, it doesn't.

**Give grounds for judgment, not adjectives.** "Absolutely worth a visit"
carries no information; "the deck's view isn't outstanding for this city — the
real draw is the street grid below the tower" does.

`photo_note` must be specific to **position and time of day**: "best angle is
across the lawn from Nishinomaru Garden, front-lit in the morning; the keep's
face is backlit at noon".

---

## Pre-output self-check

- [ ] Every category meets its minimum, or the shortfall is honestly explained
- [ ] Every place has `sources` with URLs actually visited
- [ ] Every `status` was confirmed; none filled in as `open` on assumption
- [ ] `closed_days` agrees with the `closed` text
- [ ] Every micro-spot has a `parent_id`
- [ ] Every `tier` is explainable from the detour ladder, and the distribution
      isn't inflated (`S` ≤ ~12%, `S + A` ≤ ~⅓)
- [ ] Image URLs came from the API and were eyeballed against their places
- [ ] `validate.py --check-links` reports zero P0
