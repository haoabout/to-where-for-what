# Pre-delivery verify-subagent briefing

Same premise as [subagent-briefing.md](subagent-briefing.md): a subagent
inherits **nothing** from the main conversation. Here that is not a liability
but the point — the verifier gets **fresh eyes**. You checking data you wrote
suffers from self-consistency bias: however you misread a source the first
time, you will misread it the same way when checking. An agent that knows
only `places.json` and the checklist has no stake in the data being right.

Spawned **once, always**, after `validate.py` reports zero P0 and before
delivery. While it re-opens sources in the background, you do the one check
it can't: opening the built page yourself and looking at the render
(checklist 0-3 — the preview pane is yours, not its).

Division of labor:

| The verify agent checks | Stays in the main conversation |
|---|---|
| 0-2 spot-check sources · 0-4 status re-confirmation · 0-5 closure/date conflicts · 0-6 coordinate sanity · 1-5 stale `verified_at` · 1-8 tier inflation | 0-1 running `validate.py` · 0-3 opening the page · every fix decision · the delivery message and its "must be stated" list |

Before spawning, the main conversation:

1. **Runs `validate.py` to zero P0 first** — the agent verifies facts, not
   format; don't spend it on problems a script catches.
2. **Substitutes absolute paths** for `<ABS_SKILL_ROOT>` and
   `<ABS_TRIP_DIR>`.
3. **Pastes in the trip dates** — the agent needs them for closure-conflict
   and staleness checks, and reading `brief.md` is more context than it
   needs.

After the agent returns:

1. **Adjudicate each finding yourself** — the agent is briefed to over-report
   rather than miss, so expect some false alarms; its evidence URL makes each
   one cheap to confirm.
2. Fix what's real in `places.json` (or flag it to the user when the fix is
   a trade-off), re-run `validate.py` if anything changed, rebuild.
3. Then finish the rest of [checklist.md](checklist.md) and deliver.

The agent **writes no files** — its product is the findings list in its
reply. No subagent capability (plain chat, Codex)? Do the same checks
yourself from checklist.md, as before.

---

## Prompt template

> You are the pre-delivery verifier for a trip-planning pipeline. You did
> not write this data and you should not trust it — your job is to catch
> what its author got wrong. Report only; **never edit any file**.
>
> Trip dates: `<dates>`. Data file (READ-ONLY):
> `<ABS_TRIP_DIR>/places.json`.
>
> First read `<ABS_SKILL_ROOT>/references/checklist.md` — your checks are
> items 0-2, 0-4, 0-5, 0-6, 1-5, and 1-8; the file defines what each means.
> Then:
>
> 1. **Spot-check sources (0-2)**: pick 3–5 places at random, actually open
>    the URLs in their `sources`, and confirm the page is about this place
>    and the hours / tickets / closure days written in the data match what
>    the page says today.
> 2. **Re-confirm status (0-4)**: for those same places plus any place whose
>    data looks surprising, fetch the official **homepage** (not just the
>    visitor-info page) and scan its news list for renovation or temporary
>    closure notices — that is where closures appear first.
> 3. **Closure conflicts (0-5)**: cross every place's `closed_days` /
>    closure dates against the trip dates; if an `itinerary` exists, check
>    each place is scheduled on a day it is open.
> 4. **Coordinate sanity (0-6)**: scan the coordinates for outliers — a
>    point far from the rest usually means a same-name mismatch.
> 5. **Staleness (1-5)**: for entries whose `verified_at` is more than 30
>    days old, re-verify hours and status from the official page.
> 6. **Tier inflation (1-8)**: count the tiers — flag if `S` > ~12% or
>    `S + A` > ~⅓ of the list.
>
> Rules: every finding cites the URL **you actually opened** as evidence —
> a memory or a search snippet is not evidence. When a page is unreachable
> or ambiguous, report that as a finding too; **over-reporting is fine,
> missing is not**. Do not fix anything, do not rewrite copy, do not judge
> taste — facts only.
>
> Reply with a findings list — `place id · what's wrong · evidence URL ·
> suggested severity (P0/P1)` — or "all checks passed", plus one line per
> check saying what you sampled.
