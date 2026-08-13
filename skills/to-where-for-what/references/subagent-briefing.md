# Stage-A subagent briefing

A subagent inherits **nothing** from the main conversation — it has not read
SKILL.md, does not know the playbook exists, and will happily invent fields
and guess opening hours unless told not to. So the prompt is not improvised:
copy the template below, fill every `<placeholder>`, one subagent per
category group.

Before spawning, the main conversation:

1. **Splits the categories into 2–4 groups** by affinity (e.g.
   landmark + shrine + architecture / museum + event / nature + market +
   food / hidden + media). Every category of the flexed quota table lands in
   exactly one group.
2. **Substitutes absolute paths** for `<ABS_SKILL_ROOT>` and
   `<ABS_TRIP_DIR>` — the subagent's working directory may differ.
3. **Passes only the preference lines relevant to searching** (interest
   weights, "not interested" entries, mobility notes). Never paste the whole
   `preferences.md` — the rest is the user's private context and no search
   needs it.

After all subagents return: merge the partials into `places.json` (dedupe by
name and coordinates — the same place found by two groups keeps one entry
with merged `sources`), then run A3 yourself.

---

## Prompt template

> You are researching places for a trip. Work strictly by the rules below.
>
> Trip: `<destination>`, `<dates>` (`<half-day shape, if any>`), party:
> `<party>`, home base: `<home base>`. Write all reader-facing text
> (`pitch`, `detail`) in `<user language>`.
>
> Preferences that affect searching: `<relevant lines, or "none stated">`.
>
> Your categories and quotas (already flexed toward the user's interests):
> `<rows, e.g. "museum (Museums · galleries): aim 6, floor 3">`
>
> Before searching, read these two files — they are the contract:
>
> 1. `<ABS_SKILL_ROOT>/references/research-playbook.md` — all of it: search
>    strategy, what must be verified in the first pass, anti-hallucination,
>    grading, copywriting.
> 2. `<ABS_SKILL_ROOT>/references/data-schema.md` — the `places[]` section.
>    Every field you write is defined there; fields outside the contract are
>    silently lost.
>
> Output: write **only** the file `<ABS_TRIP_DIR>/partial-<group>.json`,
> shaped as `{"places": [ … ]}` — no `trip`, `categories`, or `itinerary`
> keys. Never touch `places.json` or any other `partial-*.json`; other
> agents own those.
>
> Hard rules (the playbook explains each):
>
> - Every place carries real `sources` URLs you actually opened. A search
>   snippet is not a source.
> - Never set `status: "open"` without confirmation from an official page
>   fetched by you, now. Unverifiable → keep the place and flag it per the
>   playbook; never guess, never silently drop.
> - Do not fill `coord` by hand and do not run any script — coordinates are
>   filled centrally afterwards (parallel agents hitting the geocoder would
>   violate its rate limit). Leave image URLs out for the same reason unless
>   you took one from an official page you opened.
> - Leave `choice`, `verdict`, and everything the schema marks as
>   page-written or retro-written unset.
>
> When done, reply with: how many places per category; which places you
> could **not** verify and why; which quotas you could not honestly fill —
> shortfalls are stated, never padded.

---

## Variant: completing user stubs

For the P3 flow (SKILL.md, "Completing user-added stubs"): when **3 or more**
stubs await completion, spawn **one** agent with the template above modified
as follows; with 1–2, completing them in the main conversation is cheaper
than a spawn.

Replace the quota paragraph ("Your categories and quotas…") with:

> Your task is not to search for new places but to **complete these existing
> ones** — the user added them on a map and they have only a name and
> coordinates so far:
>
> `<rows: id · name · coord · OSM link>`
>
> For each, run the full research pass: verify hours / tickets / booking /
> status online, write `pitch` and `detail`, set `tier` / `scale` /
> `category`, fill `name_local` (contract: data-schema.md, "User stubs").

And replace the coordinate/image bullet in the hard rules with:

> - Coordinates are already set (they came from the user's map click) —
>   don't touch them. **Images are yours to find and verify** in the same
>   pass: you already have each place's official pages open, so follow the
>   playbook's image section — official pages first, Wikimedia thumbnails
>   only via the Commons API, fetch and look at every image, and leave the
>   list empty rather than keep a doubtful one.

Output file: `partial-stubs.json`, same `{"places": [ … ]}` shape, each
entry a **complete place object keeping its original `id`**. After the agent
returns, merge by `id` into `places.json` — preserving each stub's existing
`origin`, `choice`, and any `itinerary` references (SKILL.md P3 rules) —
then run `validate.py`.
