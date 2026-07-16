#!/usr/bin/env python3
"""One-off retro-tagger: applies assignments.json (uid -> [tags]) to the
register files by inserting one '- **Tags:**' line per entry.

Reuses serve.edit_tags, so every write is canon-checked, lock-guarded,
atomic, re-parse-verified with automatic restore, and journaled to
tag-edits.log. Entries that already carry the assigned tags are no-ops.

BACK UP the register files before running. Usage:
  python3 retro-tag.py            dry run — reports what would change
  python3 retro-tag.py --apply    perform the writes
"""

import json
import os
import sys

from serve import BASE, edit_tags, find_register_file, load_config

ASSIGNMENTS = os.path.join(BASE, "assignments.json")


def main():
    apply_mode = "--apply" in sys.argv
    cfg = load_config()
    if not cfg:
        print("retro-tag: no roots.json — configure the server first")
        return 2
    if not os.path.isfile(ASSIGNMENTS):
        print("retro-tag: %s not found" % ASSIGNMENTS)
        return 2
    with open(ASSIGNMENTS, encoding="utf-8") as fh:
        assign = json.load(fh)

    resolvable = 0
    unresolvable = []
    for uid in assign:
        path, _lt = find_register_file(cfg, uid)
        if path and os.path.isfile(path):
            resolvable += 1
        else:
            unresolvable.append(uid)
    print("retro-tag: %d assignments, %d resolvable, %d unresolvable%s"
          % (len(assign), resolvable, len(unresolvable),
             " (%s)" % ", ".join(unresolvable) if unresolvable else ""))
    if unresolvable:
        return 1
    if not apply_mode:
        print("retro-tag: dry run only — rerun with --apply to write")
        return 0

    updated = 0
    unchanged = 0
    failures = []
    for uid in sorted(assign):
        ok, message, _tags = edit_tags(cfg, uid, assign[uid], [])
        if not ok:
            failures.append("%s: %s" % (uid, message))
        elif message == "no change":
            unchanged += 1
        else:
            updated += 1
    print("retro-tag: %d updated, %d already-tagged no-ops, %d failures"
          % (updated, unchanged, len(failures)))
    for f in failures:
        print("FAIL %s" % f)
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
