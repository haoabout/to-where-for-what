---
name: lite-search
description: Lightweight place recommendations delivered directly in conversation — search, verify, list; no files, no full planning pipeline. Trigger on intent, in whatever language the user writes (中文/English/日本語/ไทย/…). Two scenarios: ① the user asks what a city is worth visiting («曼谷有什么好玩的» "what should I see in Bangkok" «大阪のおすすめは？»); ② the user is somewhere right now and wants nearby ideas («我现在在恰图恰附近» "what's around here this afternoon" «近くで何か面白いものある？»). Use this when they only want suggestions and haven't mentioned an itinerary page, planning, or a multi-day schedule; use travel-planner when they ask to plan a trip, build an itinerary, or make a travel guide. Reply in the user's language.
---

# Lite Search — casual place recommendations

Search → verify → **list directly in the conversation**. No files, no scripts, no questionnaire.

Division of labor with travel-planner: **this skill answers "what's worth going to";
that one produces "how to schedule the visits".** When the user hasn't mentioned an
itinerary page, planning, or a guide, default to this skill — upgrading afterwards is
smooth (see the last section), while dragging someone who asked a casual question
into the full opening questionnaire is a much worse failure.

---

## Two modes (infer from the phrasing — never ask the user to pick one)

### City level — "what's worth seeing in X"

- Default to **6–10 items**, grouped by theme (landmarks / museums / streets &
  markets / nature…). Groups need not be balanced — give more of whatever the
  city is actually strong at.
- If the context reveals an angle (traveling with kids, loves art museums, only
  has a weekend), use it. Otherwise ask **at most one question**, or just answer
  for mainstream taste and state that assumption up front.
- If a month or season was mentioned, factor in seasonal events (foliage,
  festivals, current exhibitions).

### Neighborhood level — "I'm near X right now"

- Default to **3–5 items**, ranked by **feasibility right now**, not by fame.
- **Time is the first constraint**: if it's 15:00 and the museum's last entry is
  16:30, say "doable, but you'll only have two hours"; in the evening recommend
  night markets, illuminations, places still open. If you don't know the user's
  local time, work it out from the timezone first.
- Walkable or short-ride places first, with rough distance or minutes on foot.

**The numbers are defaults, not quotas.** Fewer but solid beats padding: if you're
not sure something is worth the trip, leave it out. When the user says "give me a
few more", keep going — the conversation iterates, which is exactly the advantage
of not producing a file.

---

## Verification discipline (lightweight ≠ unverified)

Anti-hallucination rules are shared with travel-planner — see
[../travel-planner/references/research-playbook.md](../travel-planner/references/research-playbook.md):

- **At least one real source per recommendation** (official site or an
  authoritative page), linked in the entry.
- **Opening status must be checked before you state it**: city level verifies
  "currently open / currently exhibiting"; neighborhood level verifies "open
  today, right now". If you can't confirm, say "couldn't verify — check before
  you go". Never invent hours.
- Permanently closed or long-term-renovation spots are the most common failure
  in this kind of list — old articles in search results don't count; official
  information wins.
- Events and special exhibitions must have their dates checked: recommending an
  expired show sends someone on a wasted trip.

## Output shape

List directly in the chat, one line of key facts per item plus a sentence or two
on why it's worth it:

- **Name (local-language name)** — why it's worth going, in one line · rough
  time needed · opening status (neighborhood level: open now? closes when? +
  walking distance) · source link
- Use theme sub-headers for groups; end with a one-line verdict (e.g. "if the
  afternoon only fits one, pick A").
- **No files.** Only produce one if the user explicitly asks to save the list —
  which is usually the upgrade signal anyway.

---

## Upgrading to a full itinerary

When the user follows up with "help me schedule these" or "make it a trip page",
offer **two tiers** and let them choose:

1. **Mini itinerary**: use just the recommended spots — run the travel-planner
   flow but skip the large-scale search, complete the data fields, lay out a 1–2
   day route. Fits short stays with clear targets.
2. **Full planning**: supplement the search up to travel-planner's category
   quotas (35–50 places) and run the standard pipeline.

Either way: **the lightweight verification done here does not count as contract
verification.** This skill checked "is it open now"; `places.json` needs closure
days for the actual travel dates, tickets, booking rules (see travel-planner's
data-schema.md). Recommended spots **don't need re-searching, but every field
must be re-verified against the full contract** — never copy lite results into
the dataset as-is.

Also: if `trips/` already contains an itinerary for this city (how to find it:
travel-planner's "before you start" section), casually offer to add some of the
recommendations to the trip page; add only what the user confirms (with full
research, into places.json). No existing trip — don't bring it up.
