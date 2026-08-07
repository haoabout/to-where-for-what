# Museum deep-dive module

Invoke when the route includes a museum, gallery, or memorial hall. The goal is
for the user to **know what to see and how to walk it before entering**, rather
than wandering one lap and leaving.

Write into the place's `museum` field in `places.json`; the page expands it in
the detail dialog and the guide.

---

## Data structure

```jsonc
"museum": {
  "layout": "5 floors; permanent collection on 2–3F, special exhibitions on 1F and B1",
  "route": [
    { "stop": "1F lobby", "why": "Start with the building itself — the atrium void is the architectural core", "min": 10 },
    { "stop": "B1 special exhibition", "why": "The most crowded part; see it first to beat the peak", "min": 50 },
    { "stop": "2F permanent · Saeki Yūzō", "why": "The museum's founding collection; unskippable", "min": 40 }
  ],
  "highlights": [
    { "name": "Saeki Yūzō, The Postman", "name_local": "郵便配達夫",
      "era": "1928", "where": "east side, 2F permanent gallery",
      "why": "Painted months before the artist's death; the core of the collection" }
  ],
  "tips": [
    "Permanent and special exhibitions are ticketed separately; for Saeki alone the permanent ticket suffices",
    "Photography allowed; no flash, no tripods"
  ],
  "glossary": [
    { "user": "permanent exhibition", "local": "常設展", "en": "Permanent Collection" },
    { "user": "special exhibition", "local": "特別展", "en": "Special Exhibition" }
  ]
}
```

All fields optional — write what you found. **Not found = not written. Never
invent.**

The `glossary` `user` key holds the term in the user's language (when the user's
language is English, `user` and `en` will coincide — that's fine).

---

## How to write each field

### `layout` — floor plan

One or two sentences mapping floors to contents. The user builds a spatial model
before they're handed a floor guide.

### `route` — walking order

**The most valuable part.** Not the galleries listed by number, but an order
with reasons:

- See the crowded part first or last?
- Where is the building itself worth lingering?
- What can be walked through quickly?
- Minutes per leg — the total must reconcile with the place's `duration_min`

Reasons must be concrete. "See the special exhibition first" is useless; "the
special exhibition is the crowded part, and the first hour after opening is the
only lull" is useful.

### `highlights` — key works

For each: **era** (explicitly requested in the user's preferences),
**location**, **why it matters**.

`name_local` carries the local-language original — the label on the wall uses
that spelling; it's what makes the work findable.

Keep it to 3–8 works. Listing 30 is listing none.

### `tips` — practicalities

Ticket combinations, photography rules, lockers, whether the audio guide covers
the user's language, whether the café is worth it.

### `glossary` — term cross-reference

Only terms **seen on site whose misreading would hurt the visit**: permanent /
special / planned exhibition, on deposit, under restoration, and the like.
Don't build a dictionary.

---

## How to research

Priority:

1. **The official floor map and gallery pages** — the only reliable source for
   layout and walking order
2. **The official collection database** — era, artist, and whether a key work
   is currently displayed
3. **Wikipedia** — background and history; display status defers to the
   official site
4. Exhibition reviews, museology papers — help judge which works are truly core

**One thing that must be confirmed: whether the key works are currently on
display.** Rotation, loans, and restoration are routine; naming a work that's
out on loan sends the user on a wasted trip. If unverifiable, add a `tips`
entry: "works rotate; check the official site before departure".

---

## Presenting it in the guide body

Expand under the corresponding timeline node — don't split off a separate
section:

```markdown
- 15:00 · Nakanoshima Museum of Art. Suggested path: 5F first for the atrium
  view (10 min), down to the 4F permanent collection for Saeki Yūzō (40 min),
  special exhibition as needed. **The Postman (1928) hangs on the east side of
  4F** — the museum's founding work. Permanent and special tickets are
  separate; for Saeki alone, the permanent ticket suffices.
```

Write prose. Don't transliterate the JSON structure into bullet points.

---

## Boundaries

- Small memorial halls and one-room museums **don't need** this module; a clear
  `detail` suffices.
- Deep-dive at most 2–3 museums per route. Digging into all of them means no
  focus — and an unreadable guide.
- If the user has said they don't enjoy museums, don't expand this even when
  the route contains one.
