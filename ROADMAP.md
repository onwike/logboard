# logboard roadmap

## Versioning policy

`vMAJOR.MINOR.PATCH`, zero-padded (`v1.00.00`, `v1.01.00`, `v1.01.02`).

- **Patch** — fixes and hardening of already-released behavior; no new public capability.
- **Minor** — a new, backward-compatible capability or public surface.
- **Major** — breaks a core invariant or repositions the tool.

A release's quality level is the certification tier it actually passed; a tag never
claims a tier that was not earned. Untiered tags carry their gate evidence instead.

## v1.01.00 — admin tag editing + retro-tagger (2026-07-16)

**Shipped:** `POST /tags` — the server's one surgical register write (a single entry's
`Tags` line: lock-guarded, atomic, re-parse-verified with restore, journaled to
`tag-edits.log`, canon-strict, local-admin only). Editable tag pills + canon-filtered
picker in the drill-down. `retro-tag.py` for bulk backfill from `assignments.json`
(dry-run by default).

**Quality level:** untiered. Gates at tag time: `serve.py --check` 31 ok / 0 failed;
tag-editor battery (one-line diff purity, byte-identical removal restore, cross-origin
403, off-canon/wrong-register 400s, journal); reindex byte-identical across register
types after a 253-entry backfill; repo hygiene clean.

**Carried forward:** none. A Bronze certification of the full shipped state is planned
at v1.01.02.

## v1.00.00 — baseline (2026-07-16)

Initial public logboard: register parser (four grammars, legacy quirks), read-only
data/config API bound to 127.0.0.1, browser setup screen, dashboard (recency-first
KPIs, daily/weekly trends, lane and project breakdowns, hot-spots, tagging-debt chart,
searchable drill-down table, deep links), repo leak guards (allowlist pre-commit and
pre-push), README with synthetic demo captures.

**Quality level:** untiered. Gates at tag time: `serve.py --check` 31 ok / 0 failed;
tree equals the tracked allowlist; content greps clean; seeded leak test blocked.

## Planned

- **v1.01.01** — test suite covering parser, config API, tag editing, guards (patch).
- **v1.01.02** — README refreshed with captures of the live system, content redacted;
  Bronze certification of the shipped state recorded on this tag.
- **Part 2 (unversioned until planned)** — cloud-hosted frontend pointing at the local
  data server; CORS/PNA enablers already shipped in v1.00.00.
