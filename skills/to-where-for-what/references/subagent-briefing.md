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
