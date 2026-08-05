# vendor/

Third-party code, stored verbatim and unmodified, inlined into `trip.html` by
`build.py`.

## sortable.min.js

| | |
|---|---|
| Library | [SortableJS](https://github.com/SortableJS/Sortable) 1.15.7 |
| License | MIT |
| Dependencies | none |
| Size | 44.4 KB (~15 KB gzipped) |

**Why inlined rather than loaded from a CDN**: MapLibre has a three-tier
fallback chain and the map needs the network anyway; sorting doesn't — losing
drag-sort because unpkg is down would be a self-inflicted failure point. The
user may reopen this file months later.

**Why a library rather than hand-rolling it**: `fallbackTolerance`
(distinguishing a click from a drag), `scrollSensitivity` (auto-scroll at
container edges) and `pull:'clone'` (the original card stays behind when
dragged out of the pool) cover exactly the hardest parts to write yourself —
and the clone semantics map precisely onto "the pool column doesn't remove,
it only grays out".

**How to update**:

```bash
curl -sL -o sortable.min.js https://unpkg.com/sortablejs@<version>/Sortable.min.js
```

After updating, run the end-to-end checks under `dev/`, paying particular
attention to cross-container dragging and within-container reordering.
