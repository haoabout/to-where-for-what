# A3 image-subagent briefing

Same premise as [subagent-briefing.md](subagent-briefing.md): a subagent
inherits **nothing** from the main conversation — it has not read SKILL.md,
does not know the playbook exists, and will happily hand-assemble a Wikimedia
thumbnail URL or keep a mislabeled photo unless told not to. Copy the
template below, fill every `<placeholder>`.

Unlike the stage-A search agents, this one is spawned **once, always, in the
background** — right after `enrich.py --coords --images` finishes. 35–50
places always carry enough image work to justify it (every filled image needs
verification, not just the misses), and backgrounding it means the slowest
part of A3 stops blocking the main line: you fix coordinate misses and run
`--transit` while it works.

Before spawning, the main conversation:

1. **Runs `enrich.py --coords --images` first.** The agent starts from the
   script's results; spawning earlier only duplicates, worse, the chain the
   script runs.
2. **Extracts the miss list** from the enrich report — `id`, name, and an
   official-site URL (from `sources`) for each place still without images —
   and pastes it into the prompt. Everything else the agent reads from
   `places.json` itself.
3. **Substitutes absolute paths** for `<ABS_SKILL_ROOT>` and
   `<ABS_TRIP_DIR>` — the subagent's working directory may differ.
4. **Picks the model**: one tier below the main conversation's (SKILL.md,
   "Subagent model tier"), and it **must be vision-capable** — one tier
   down normally still sees images. A text-only agent must downgrade to the
   playbook's per-source text rules — and its report must say so, so
   delivery can disclose it.

After the agent returns:

1. Read `images-patch.json` and spot-check 2–3 entries — open the URL,
   confirm it loads and shows that place.
2. Merge into `places.json` by `id`: a patch entry **replaces that place's
   `images` wholesale**; `"images": []` means "checked, nothing usable —
   stays imageless". Places with no patch entry keep what they have.
3. Delete the patch file, then continue A3: `validate.py --check-links` →
   build.
4. If the report says verification was text-only, carry that into the
   delivery notes (checklist.md has the phrasing).

No subagent capability (plain chat, Codex)? Do the same work yourself in the
main conversation, by the same playbook rules.

---

## Prompt template

> You are the image agent for a trip-planning pipeline. Your only job is the
> `images` arrays — never touch, judge, or rewrite any other field.
>
> Trip: `<destination>`. Data file (READ-ONLY):
> `<ABS_TRIP_DIR>/places.json`. Never write to it — other work is happening
> in it concurrently.
>
> Before working, read `<ABS_SKILL_ROOT>/references/research-playbook.md`
> from the section "Images: let the script's chain run first, then fill gaps
> by hand" through "No vision capability? Verify textually, and say so" —
> that is the contract for this task.
>
> Two jobs:
>
> 1. **Find images for these places** (an automated chain already came up
>    empty for them):
>
>    `<rows: id · name · official-site URL>`
>
>    Official pages first — the venue's own site or official social account
>    (og:image, a press-kit photo). Fetch every candidate URL to confirm it
>    actually loads. Wikimedia thumbnails only via the Commons API
>    (`iiurlwidth` → use the returned `thumburl`); never hand-assemble a
>    thumbnail URL — arbitrary widths 400. Nothing trustworthy found →
>    leave that place's list empty. **A wrong image is worse than no
>    image.**
>
> 2. **Verify every image already filled in `places.json`** — fetch each
>    one and look at it: does it show *this* place? Tile batches into
>    contact sheets to scan efficiently. Mislabels are common: category
>    fetches and keyword search both misfire (a Wikidata match can return
>    the neighborhood's subway station instead of the neighborhood).
>    Replace what fails if a trustworthy substitute is easy to find;
>    otherwise drop it. If you cannot see images, apply the playbook's
>    per-source text rules instead and state that in your report.
>
> Output: write **only** the file `<ABS_TRIP_DIR>/images-patch.json`,
> shaped as:
>
> ```json
> {"patches": [
>   {"id": "<place id>",
>    "images": [{"url": "…", "credit": "…", "source_url": "…"}]}
> ]}
> ```
>
> One entry per place you changed — a patch **replaces** that place's
> `images` wholesale, and `"images": []` means "checked, nothing usable".
> Places whose existing images all passed get no entry. Every image needs
> an honest `credit` (the Commons API's `extmetadata` carries artist and
> license).
>
> When done, reply with: how many images found / verified / replaced /
> dropped; which places stay imageless and why; and whether verification
> was visual or text-only.
