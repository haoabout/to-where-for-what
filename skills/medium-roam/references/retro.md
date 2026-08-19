# Post-trip retro

Read when the pre-A1 scan (SKILL.md, "Before a new trip") found a finished
trip with no retro: `dates.end` in the past, `trip.retro` unset. Take the most
recent such trip only — never backlog-interrogate.

Why this step exists: stage-B choices record what *attracted* the user; only
the trip itself shows what *delivered*. That gap — the hyped spot that
disappointed, the reluctant add that became the highlight — is the most
valuable preference signal there is, and this is the only step that collects
it. (A months-late answer is not a worse answer: what still surfaces from
memory after weeks is precisely the durable signal.)

## Ask lightly, once

Two open questions: which places turned out really worth it, and which they
regretted or found disappointing. Record what they volunteer; don't chase the
places they didn't mention. "Don't want to go over it" is a full answer —
write `trip.retro: "skipped"` and never raise that trip again.

## Record on two levels

1. **Raw, into that trip's `places.json`**: set `verdict` / `verdict_note` on
   the places mentioned (contract: [data-schema.md](data-schema.md),
   "Post-trip feedback"), then `trip.retro: "done"`.
2. **Distilled, into `preferences.md` "Proven preferences"** — but the
   generalization is the dangerous step: "disliked teamLab" could mean queues,
   crowds, or immersive shows in general, and picking the wrong axis skews
   every future trip. So **propose the exact wording, with its evidence, and
   append only after the user confirms** — never write it silently. Each
   entry cites the trip and date.

Proven entries outrank the declared interest weights when they conflict
([research-playbook.md](research-playbook.md), "Grading") — and a wildcard
pick the user reports loving is the strongest promotion signal a category can
get.
