# Stage A · Research playbook

Goal: a `places.json` with 35–50 places, every one carrying **opening
information verified in the first pass**.

The core quality bar: **every choice the user makes off this list must be a
valid one.** If they pick "want to go" and it turns out the place is closed that
day, under renovation, or requires booking a month ahead, the whole filtering
round was wasted.

## Contents

First time here, read the whole file. Returning for one thing, jump straight
to it:

- [Category quotas](#category-quotas) — incl. flexing toward interests (floors
  are hard), wildcard slots, small cities, `event`
- [Information that must be in the first pass](#information-that-must-be-in-the-first-pass)
- [Search strategy](#search-strategy) — sources hierarchy, two pages per
  place, snippets are not a source, unverifiable ≠ delete, fake official
  domains, exhibition runs, hidden gems, micro-spots
- [Anti-hallucination](#anti-hallucination) — `sources` hard gate, never
  guess `status`, image sourcing (Wikimedia: API only), no-vision fallback
- [Getting coordinates](#getting-coordinates) — scripts do this, not you
- [Grading: `tier` and `photo_index`](#grading-tier-and-photo_index) — read
  when assigning either; incl. the distribution check
- [Writing the copy](#writing-the-copy) — `pitch` / `detail` division of labor
- [Pre-output self-check](#pre-output-self-check)

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

### Flex quotas toward interest — but floors are hard

The interest weights in `preferences.md` bend the quotas: a **High** category
aims at its Max, a **Low** category at its Min. Two hard edges:

- **No category drops below its Min because of a weight.** Only an entry under
  "Not interested — don't recommend" removes a category outright. Low means
  "rank it lower", not "stop offering it" — the Min floors are what keeps one
  sentence ("we're into architecture") from collapsing the whole list into
  architecture.
- The flexed table is announced in the A1½ confirmation like any other quota
  adjustment — never silently.

### Non-preferred categories must stand on their own merit

Quotas police the labels; this rule polices the selection reason. When filling
a category the user is lukewarm about, pick the best of *that category* — not
a flavored variant of what they already like. A Tadao Ando-designed park
filling the `nature` quota is architecture wearing a nature label, and the
diversity the floors were supposed to guarantee quietly disappears. Test every
cross-category pick: **would it still make this list if the user had never
stated that interest?**

### Wildcard slots — 2–3 deliberate off-profile picks

Reserve 2–3 places per search that sit **outside the user's stated profile**
but carry exceptional local reputation — the exploration slice a feed
algorithm would keep. Rules:

- They ride on top of the category quotas — never crowd a category below Min
- The `pitch` says honestly what each one is: "not your usual profile, but
  locals rate it exceptionally — judge for yourself"
- Wildcards are how the profile grows: one the user later reports loving (the
  retro loop, SKILL.md) promotes that direction in the next trip's quotas and
  tiers

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

### Images: the candidate pipeline runs first, then the visual pass decides

`enrich.py --images` no longer stops at the first hit. Per place it collects
up to **3 verified, deduplicated candidates** across the source families
below — every candidate is fetched with a real streaming `GET` (2xx + image
MIME + magic bytes; og:image URLs routinely 404, and some CDNs serve an HTML
error page with 200) — grades each by identity confidence, and records
everything in `image-audit.json` next to `places.json`:

- `high` — exact identity: Wikipedia exact-title/redirect lead image, or a
  Wikidata P18 whose entity matches **both** name and bbox. Only these are
  provisionally written to `places.json`, and only for places that had no
  image at all.
- `medium` — Wikipedia search hits, official-site og/meta/body images,
  Commons category members. Plausible but not proven; the visual pass decides.
- `low` — pure geo hits, Openverse, weak name evidence. **Distance never
  decides identity**: a geosearch hit whose title doesn't match the place's
  names stays low no matter how close (measured in Bangkok — the Old Customs
  House won on distance for a place whose coordinate sat 180m off).

Source families, in trust-then-cost order: Wikipedia exact title + redirects
→ Wikidata P18 (bbox-checked via P625) → Wikipedia search → official pages
(og/twitter/JSON-LD/itemprop meta, then body `img`/`srcset`) → Commons
category via P373 (one subcategory level) → geosearch (Wikipedia 150m,
Commons 120m) → Openverse. Composite display names (「梅田蓝天大厦 ·
空中庭园展望台」, 「大邮政大楼与 TCDC 曼谷」) are retried as variants —
parentheticals stripped, split on `·`/`&`/`and`/`与` and friends. Places
whose `category` is `event` scan their official page FIRST, and their
Wikipedia/Wikidata hits are capped at medium: an exact-title hit on a name
segment is the *venue's* facade, and an exhibition must never be represented
by the building it happens in. An official og:image is capped at medium for
the same reason from the other side — it can be a logo, a campaign banner,
or a news photo of an event at the venue (measured: Siam Paragon), and no
filename filter catches a clean-named news photo.

Existing images aren't trusted either: each run re-verifies them as
`existing` candidates, and a dead URL triggers fresh collection — but an
existing image is **never auto-replaced**; that swap belongs to the visual
pass. Every failure (404, 429, non-image, decode, identity mismatch) lands
in the audit instead of being silently swallowed.

The visual pass (the A3 image subagent, or you) reads `places.json` +
`image-audit.json`, judges the candidates, and hands back
`images-patch.json`; merge it with `--apply-image-review`, which validates,
applies atomically, and writes verdicts back into the audit. When the whole
pipeline comes up empty, **fill `images` manually with a direct link from an
official page**: the venue's own site or official social account (a
press-kit photo, a post). Two conditions: the URL actually loads (fetch it,
don't assume), and the photo shows *this* place. This is a personal-use
tool, so the licensing posture is pragmatic — but keep `credit` honest about
where the image came from. Truly nothing anywhere? Leave it empty; images
are optional, wrong images are not.

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

**Also look at every image yourself — you, the AI, not the user.** Fetch each
image and check it actually shows that place; never delegate this to the user.
Category-based fetching and keyword search (Openverse) mislabel easily — the
first file in `Category:Osaka Castle` may be something entirely unrelated, and
a Wikidata match can return the neighborhood's subway station instead of the
neighborhood. After a batch fetch, tile them into one contact sheet and scan
it; far faster than opening them one by one.

#### No vision capability? Verify textually, and say so

A text-only model can't look at images — don't skip verification, downgrade
it. Most mislabels leak into text: that subway-station mismatch above carried
the filename `Osaka-subway-T19-Nakazakicho-station.jpg`, catchable with no
eyes at all. Per source:

The audit's `source` tag tells you which rule applies:

| Source | Text-only rule |
|---|---|
| `wikipedia` (exact title/redirect) | Trust as-is — lead images are rarely mislabeled |
| `wikidata` | Keep only if `matched_title` / filename relates to the place name; otherwise drop |
| `wiki-search` | Keep only if the hit article's title relates to the place name |
| `official-meta` / `official-body` | Confirm the URL loads; drop if the filename screams logo/banner (`logo`, `ogp`, `banner`) — and remember a clean-named news photo passes this filter while still being wrong |
| `commons-category` | Keep only when the filename relates to the place — the first file in a category can be anything |
| `wiki-geo` | Keep only if the found article's title relates to the place name — the nearest article can be a neighbor |
| `commons-geo` | Keep only when the filename / description relates to the place or its street; otherwise drop |
| `openverse` | Strictest: keep only when title / tags / filename contain the place name; otherwise leave empty |
| `existing` | Already on the page; drop only with a reason (dead URL, wrong subject per the rules above) |
| Official-site direct link (manual) | Confirm the URL loads; a venue's own site doesn't misphotograph itself |

Then **tell the user at delivery, explicitly**: the model in use has no vision,
so images passed text checks only, not visual review — and any photo that looks
wrong while they filter is worth reporting, since swapping an image is cheap.
Stage B already walks their eyes across every card, so this costs them nothing
extra. Don't present text-checked images as verified.

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

**Proven preferences outrank declared ones.** When an entry in the "Proven
preferences" section of `preferences.md` contradicts a declared weight (Low on
nature, but three gardens loved on a past trip), adjust from the proven entry
— it was paid for in shoe leather — and point the conflict out to the user,
suggesting they update the declared weight. The one-step ceiling still
applies. Likewise feed proven entries into the quota flexing above: a
direction the user loved is treated as High even if they never declared it.

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
