# Film & anime locations

Find the destination's film locations, anime pilgrimage sites, and TV shooting
spots. Written into the `media` field of `places.json`.

---

## Be upfront about what's achievable

**Achievable**: locations with clear public documentation — officially
announced, promoted by local governments as pilgrimage routes, or long
maintained and cross-verified by fan communities.

**Try, but expect walls**: Xiaohongshu, Bilibili, and Douyin often sit behind
anti-bot measures and login walls. **Attempt them first** — when a page does
open, it's the richest source for exactly the spots nothing else covers. When
blocked, fall back to second-hand write-ups via search engines instead of
retrying the wall, and accept that **spots that spread via short video but
never settled into written sources may be missed**.

Tell the user which spots that caveat touches — don't let them assume the list
is exhaustive.

---

## Data structure

```jsonc
"category": "media",
"media": {
  "title": "Your Name",
  "title_local": "君の名は。",
  "year": 2016,
  "type": "anime film",
  "scene": "The staircase where Taki and Mitsuha pass each other — the film's final shot",
  "fidelity": "high",
  "official": true
}
```

| Field | Notes |
|---|---|
| `title` / `title_local` | Work title. Always give the local-language title — on-site signs and merchandise use it |
| `year` | Release/broadcast year; helps the user judge how current it still is |
| `type` | anime film / TV anime / film / TV series / music video / variety show |
| `scene` | **Down to the exact scene.** This is the module's core value |
| `fidelity` | `high` the site matches the frame closely / `medium` takes angle-hunting / `low` loose reference only |
| `official` | Official or local-government endorsement (usually means signage and a pilgrimage map) |

`scene` must let people match the shot. "Where the leads meet" isn't enough;
"the staircase where Taki and Mitsuha pass each other — the film's final shot"
is.

---

## How to find them

By reliability:

1. **Official pilgrimage programs** — many Japanese local governments and the
   Anime Tourism Association certify sites formally, with maps and signage.
   Search `<title> 聖地巡礼 公式` (or the local language's equivalent of
   "official filming locations")
2. **Locations announced by the production** — the film's site, Blu-ray extras,
   director interviews
3. **Local tourism-association feature pages** — often a "filmed in X" trail
4. **Long-maintained fan databases** — the kind with exact addresses and
   side-by-side comparison shots; fairly reliable
5. General blog posts — leads only; cross-verify against 1–4

**Cross-verification is mandatory.** Filming locations are a misinformation
hotspot: many circulated "pilgrimage spots" are wrong, or belong to a different
work. Two independent agreeing sources minimum.

---

## Special cautions

### The site may have changed

Locations get rebuilt, demolished, or fenced off. `status` must reflect
reality:

```jsonc
"status": "permanently_closed",
"status_note": "The building containing the staircase was demolished in 2023; the site is now a construction lot"
```

The older the filming, the more the current state needs confirming.

### Many are private homes or private property

Plenty of locations are residential streets, private shops, or operating
schools. These must say so explicitly in `detail`:

> This is an ordinary residential area. Do not enter the grounds, keep noise
> down, and don't linger shooting in front of private homes.

Not boilerplate — pilgrimage friction with residents is common, and some sites
have banned photography because of it.

### Most are micro-spots

A staircase, an intersection, a platform — usually 5–15 minutes. Handle as
micro-spots:

- `scale: "spot"`, `parent_id` pointing at the area's major place
- `duration_min` 5–15
- The `pitch` says it straight: "it's that staircase; two photos and go —
  worth it only in passing"

Unless it's a dedicated museum, or the work's stage is a whole district.

### Expectation management

Low-`fidelity` spots must say so:

> The site differs a lot from the frame — the anime beautified it heavily.
> Fine with a "let's see if we can find it" attitude; a special trip will
> disappoint.

---

## Slotting them into the route

- A single spot **never justifies a detour** — insert only when passing by
- Several spots from one work clustered in one area can chain into a small
  side-line — then half a day is justified
- Name the work and scene in the guide body, so companions who haven't seen it
  know what this is:

```markdown
- 16:20 · Suga Shrine steps (the passing-each-other staircase from the end of
  *Your Name*, 5 min). Eight minutes' walk from Yotsuya station, on the way.
  Residential area — photograph quietly.
```

---

## Quota

The `media` category: minimum 2, maximum 6.

Niche destinations may have none — **say there are none; never pad**.
Writing in a vague "some show supposedly shot here" lead is worse than leaving
it empty.
