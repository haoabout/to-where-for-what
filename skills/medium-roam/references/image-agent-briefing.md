# A3 image-subagent briefing

Same premise as [subagent-briefing.md](subagent-briefing.md): a subagent
inherits **nothing** from the main conversation — it has not read SKILL.md,
does not know the playbook exists, and will happily hand-assemble a Wikimedia
thumbnail URL or keep a mislabeled photo unless told not to. Copy the
template below, fill every `<placeholder>`.

Unlike the stage-A search agents, this one is spawned **once, always, in the
background** — immediately after the v1 page is delivered to the user, at the
same moment as the verify agent, and both are announced in the same message.
`enrich.py --coords --images` ran earlier in A3, so by delivery time the
candidates are already sitting in `image-audit.json` (only exact-identity
`high` hits were provisionally written to `places.json`; every `medium`/`low`
candidate waits) and each surviving candidate's bytes are already on disk in
`image-review/`. The agent's job is **judging**, not searching and not
downloading: look at the saved candidates, pick the right one or reject them
all, and only then search by hand. Spawning it after v1 means the slowest
part of A3 no longer sits between the user and a usable page — it runs while
they filter in stage B, and its patch lands before the final build.

Judging stays a **single** agent on purpose: off the user's critical path,
4.8 minutes of background work is not worth the coordination cost of
splitting places across agents (patch merging, `image-review/` cleanup
races, per-spawn billing) — sharding by place range is a future option for
100+ place trips only.

The script also sorts every place into one of two review tiers and records it
as `review` on that place's audit entry. **The tier decides how much of the
agent's attention the place gets** — spending the same effort everywhere was
measured as most of A3's cost, and most of it bought nothing:

- `review: "glance"` — the identity families vouched for the one image the
  place carries (Wikipedia exact title, or a bbox-checked Wikidata P18 whose
  label matches the name). Exactly one candidate. These are wrong ~10% of the
  time, in three coarse ways one look catches instantly, so they get a glance
  and no hand searching.
- `review: "full"` — nothing vouched for it: no corroborated hit, or an
  event (its identity is the activity, never the venue), or a name that
  resolves to several entities inside the bbox. Up to 2 candidates, all of
  them unproven — `medium` candidates were rejected 79% of the time — so
  these get the full contract, hand searching included.

Before spawning, the main conversation:

1. **Has already run `enrich.py --coords --images`.** The agent starts from
   `image-audit.json`; spawning before collection only duplicates, worse, the
   chain the script runs.
2. **Confirms `<ABS_TRIP_DIR>/image-review/` exists.** That directory holds
   the candidate bytes the agent reads instead of downloading. It is absent
   after a dry run, on a trip dir collected by an older version, or once a
   previous patch was merged (the merge deletes it) — in that case the agent
   falls back to fetching candidate URLs, which is slower, and its report
   must say so.
3. **Substitutes absolute paths** for `<ABS_SKILL_ROOT>` and
   `<ABS_TRIP_DIR>` — the subagent's working directory may differ.
4. **Picks the model**: default **Sonnet** where available, not the usual
   one-tier-below rule — the job is a yes/no visual judgment over
   pre-collected candidates, and measured on Bangkok (41 places, 70
   candidates) a top-tier model was no better, only pricier. Runtimes
   without Sonnet (Codex and friends) just use their available
   vision-capable model — the model matters far less than the loop.
   Escalate a tier only when the trip is dense with hard identity calls
   (look-alike branches, event key visuals). Whatever the tier, it **must
   be vision-capable**. A text-only agent must downgrade to the playbook's
   per-source text rules — and its report must say so, so delivery can
   disclose it.

After the agent returns:

1. Read `images-patch.json` and spot-check 2–3 entries — open the URL,
   confirm it loads and shows that place.
2. Merge with
   `<PY> <ABS_SKILL_ROOT>/scripts/enrich.py <ABS_TRIP_DIR>/places.json
   --apply-image-review <ABS_TRIP_DIR>/images-patch.json` — it validates the
   patch, applies it atomically (a patch entry **replaces that place's
   `images` wholesale**; `"images": []` means "checked, nothing usable —
   stays imageless"), and writes the verdicts back into `image-audit.json`.
   On success it also **deletes `image-review/`** — the saved bytes have done
   their job. A rejected patch changes nothing and leaves `image-review/`
   intact, so the agent can be handed the errors and retry from the same
   files.
3. Delete the patch file, then re-run `validate.py --check-links` → rebuild,
   and fold the result into the one message that tells the user what changed
   since v1.
4. Carry the report's tier split into the delivery notes — the `glance`
   places got an identity check, not a per-image deep review, and the user
   should hear that. Same for a report that says verification was text-only.
   checklist.md has the phrasing for both.

No subagent capability (plain chat, Codex)? Do the same work yourself in the
main conversation, by the same playbook rules.

---

## Prompt template

> You are the image agent for a trip-planning pipeline. Your only job is
> picking each place's `images` — never touch, judge, or rewrite any other
> field.
>
> Trip: `<destination>`. Data files (both READ-ONLY):
> `<ABS_TRIP_DIR>/places.json` and `<ABS_TRIP_DIR>/image-audit.json`.
> Never write to either — other work is happening in them concurrently.
>
> Before working, read `<ABS_SKILL_ROOT>/references/research-playbook.md`
> from the section "Images: the candidate pipeline runs first, then the
> visual pass decides" through "No vision capability? Verify textually, and
> say so" — that is the contract for this task.
>
> **The candidate images are already on disk. Judge them from there, and do
> not download anything.** A candidate in `image-audit.json` may carry a
> `file` field: a path relative to `<ABS_TRIP_DIR>` (always
> `image-review/<place id>_<n>.<ext>`) holding the exact bytes that
> candidate's URL served. Open it with the **Read** tool, using the path in
> the field verbatim. Never run `curl`, `wget`, or any other shell download,
> and **never re-fetch a URL that has a `file`** — the file *is* that URL's
> content.
>
> **Read the files in large parallel batches**: issue 10–15 Read calls in a
> single turn, then the next batch, until you have seen everything. Never one
> image per turn. This is the whole reason the job is fast — measured, this
> path judged 47 places in 4.8 minutes, against 31.4 minutes for the old
> download-then-look loop.
>
> A candidate without a `file` has no saved bytes: its check failed, its
> bytes duplicated another candidate's (its `reason` starts
> `duplicate-bytes:`, and the surviving copy's URL follows), the body was
> ≥2MB, or the second fetch failed. Fetching the original URL is allowed
> **only** for an individual `full`-tier candidate that is genuinely
> ambiguous on screen or whose `file` is missing — one at a time, as an
> exception, never as a bulk pass. If `<ABS_TRIP_DIR>/image-review/` does not
> exist at all, fall back to fetching candidate URLs and say so in your final
> report.
>
> `image-audit.json` holds each place's candidates — `source`, `confidence`
> (high/medium/low/existing), `matched_title`, a network check, an optional
> `file` — and a `review` field that is either `"glance"` or `"full"`.
> **Read `review` first: it decides how much work that place is owed.** Split
> the places into the two groups and work them separately; do not give a
> `glance` place the `full` treatment, and never the reverse.
>
> **`review: "glance"` places — one question, no searching.** A source
> already vouched for the identity of the single candidate, which is the
> image on the page. Read their files in big batches and ask only *is this
> the right place?* Three failure modes account for essentially all the
> errors, and all three are visible at a glance:
>
> - the photo shows a **neighbor** — the building next door, the station the
>   district is named after;
> - the photo shows the place's **holdings or contents** rather than the
>   place — a museum's star painting, a shop's product close-up;
> - the photo is an **interior** where the place is an exterior landmark, or
>   the reverse.
>
> Anything that looks like the place, stays. Anything that trips one of the
> three: **drop it and move on** — emit a patch with `"images": []` and a
> reason. You have **no obligation to hand-search a replacement** for these;
> spending the search budget here is exactly what this tier exists to avoid.
>
> **`review: "full"` places — the whole contract, per place:**
>
> 1. **Look at the candidates** — Read the saved file of every candidate
>    whose check passed, batching across places as above, and ask: does it
>    show *this* place (for events: the activity's key visual, never the
>    venue's facade)? `confidence` tells you the machine's evidence, not the
>    truth: a `high` the script already wrote can still be wrong, and a `low`
>    geo hit can still be right — your eyes decide.
> 2. **Pick at most one winner per place** (the best-identified, best-looking
>    candidate) or reject them all. Rejecting an `existing` image requires a
>    reason, and before leaving a place imageless you must **try at least
>    one source family the audit shows untried** for that place — official
>    pages first (og:image, a press-kit photo). Fetch every hand-found URL
>    to confirm it actually loads. Wikimedia thumbnails only via the Commons
>    API (`iiurlwidth` → use the returned `thumburl`); never hand-assemble a
>    thumbnail URL — arbitrary widths 400. Nothing trustworthy found →
>    leave that place's list empty. **A wrong image is worse than no
>    image.**
> 3. If you cannot see images, apply the playbook's per-source text rules
>    instead and state that in your report.
>
> Output: write **only** the file `<ABS_TRIP_DIR>/images-patch.json`,
> shaped as:
>
> ```json
> {"patches": [
>    {"id": "<place id>",
>     "images": [{"url": "…", "credit": "…", "source_url": "…"}]}
>  ],
>  "reviews": [
>    {"id": "<place id>",
>     "accepted": ["<winning url>"],
>     "rejected": [{"url": "…", "reason": "shows the neighboring pier"}],
>     "searched": ["official-body"],
>     "note": "optional context"}
>  ]}
> ```
>
> One `patches` entry per place whose `images` should change — it
> **replaces** that place's `images` wholesale, and `"images": []` means
> "checked, nothing usable". Places whose current images all passed get no
> patch entry. One `reviews` entry per place you examined — accepted URL,
> rejected URLs each with its reason, and which source families you searched
> by hand. Every image needs an honest `credit` (the Commons API's
> `extmetadata` carries artist and license).
>
> When done, reply with: how many places reviewed **in each tier** / images
> accepted / replaced / dropped; which places stay imageless and why; whether
> you judged from the saved files or had to fall back to fetching URLs, and
> how many candidates needed that fallback; and whether verification was
> visual or text-only.
