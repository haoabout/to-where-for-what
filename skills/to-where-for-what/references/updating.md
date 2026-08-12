# Updating this skill

When the user asks whether or how to update this skill, work in this order —
the order matters, because the first thing on the user's mind is usually
"will I lose my data".

1. **Reassure first**: `preferences.md` and the trips directory live outside
   the skill and are untouched by any update path.
2. **Detect local modifications** of the installed skill files. With git
   metadata: `git status`. Without: read `version:` and `source:` (the source
   repo's URL) from SKILL.md's frontmatter, fetch that release from the source
   repo, and diff — comparing against *latest* instead would conflate the
   user's edits with upstream evolution.
3. **Unmodified** → overwrite with the new version.
   **Modified** → three-way merge per file (installed version's original ×
   the user's copy × the new version), and merge the skill directory **as one
   unit** — `build.py` and the template are coupled; mixing versions breaks.
4. Read `CHANGELOG.md` and tell the user the behavior changes before
   applying, then re-run `validate.py` over existing trips afterwards.

Rationale and the power-user recommendation (git install, local commits): the
"Updating" section of the source repo's README —
https://github.com/haoabout/to-where-for-what#updating — the README does not
ship with a skill-only install, so follow the link rather than looking for a
local copy.
