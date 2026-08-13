# A3 image-subagent briefing

Same premise as [subagent-briefing.md](subagent-briefing.md): a subagent
inherits **nothing** from the main conversation — it has not read SKILL.md,
does not know the playbook exists, and will happily hand-assemble a Wikimedia
thumbnail URL or keep a mislabeled photo unless told not to. Copy the
template below, fill every `<placeholder>`.

Unlike the stage-A search agents, this one is spawned **once, always, in the
background** — right after `enrich.py --coords --images` finishes. The script
has already collected up to 3 verified candidates per place into
`image-audit.json` (only exact-identity `high` hits were provisionally
written to `places.json`; every `medium`/`low` candidate waits), so the
agent's job is **judging**, not searching: look at the candidates, pick the
right one or reject them all, and only then search by hand. Backgrounding it
means the slowest part of A3 stops blocking the main line: you fix
coordinate misses and run `--transit` while it works.

Before spawning, the main conversation:

1. **Runs `enrich.py --coords --images` first.** The agent starts from
   `image-audit.json`; spawning earlier only duplicates, worse, the chain
   the script runs.
2. **Substitutes absolute paths** for `<ABS_SKILL_ROOT>` and
   `<ABS_TRIP_DIR>` — the subagent's working directory may differ.
3. **Picks the model**: one tier below the main conversation's (SKILL.md,
   "Subagent model tier"), and it **must be vision-capable** — one tier
   down normally still sees images. A text-only agent must downgrade to the
   playbook's per-source text rules — and its report must say so, so
   delivery can disclose it.

After the agent returns:

1. Read `images-patch.json` and spot-check 2–3 entries — open the URL,
   confirm it loads and shows that place.
2. Merge with
   `<PY> <ABS_SKILL_ROOT>/scripts/enrich.py <ABS_TRIP_DIR>/places.json
   --apply-image-review <ABS_TRIP_DIR>/images-patch.json` — it validates the
   patch, applies it atomically (a patch entry **replaces that place's
   `images` wholesale**; `"images": []` means "checked, nothing usable —
   stays imageless"), and writes the verdicts back into `image-audit.json`.
   A rejected patch changes nothing; fix the reported errors and rerun.
3. Delete the patch file, then continue A3: `validate.py --check-links` →
   build.
4. If the report says verification was text-only, carry that into the
   delivery notes (checklist.md has the phrasing).

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
> `image-audit.json` holds up to 3 verified candidates per place, each with
> `source`, `confidence` (high/medium/low/existing), `matched_title`, and a
> network check. Your job, per place:
>
> 1. **Look at the candidates** — fetch each candidate URL whose check
>    passed and look at it: does it show *this* place (for events: the
>    activity's key visual, never the venue's facade)? Tile batches into
>    contact sheets to scan efficiently — far faster than one by one.
>    `confidence` tells you the machine's evidence, not the truth: a `high`
>    the script already wrote can still be wrong, and a `low` geo hit can
>    still be right — your eyes decide.
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
> When done, reply with: how many places reviewed / images accepted /
> replaced / dropped; which places stay imageless and why; and whether
> verification was visual or text-only.
