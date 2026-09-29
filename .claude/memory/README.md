# Claude memory sync

These files mirror Claude Code's own persistent memory for this project
(normally stored outside the repo, under `~/.claude/projects/.../memory/`).
Checked in here so they travel with the repo across machines via git instead
of a manual USB copy.

**Contains personal info by choice**: `user_background.md` includes the
project owner's email — kept here deliberately (confirmed 2026-09-29) rather
than excluded, so be aware this repo is public and that file is visible to
anyone.

## To restore on a new machine

1. Clone this repo.
2. Open it once in Claude Code so it creates its own local project folder
   under `~/.claude/projects/<hashed-path>/memory/`.
3. Copy the `.md` files from this folder (not this `README.md`) into that
   local memory folder, overwriting the empty ones Claude created.

This is a best-effort sync, not a guaranteed one — Claude Code's exact
lookup behavior for which local memory folder a session uses isn't
something this process controls.
