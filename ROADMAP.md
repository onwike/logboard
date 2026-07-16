# logboard roadmap

## Versioning policy

`vMAJOR.MINOR.PATCH`, zero-padded (`v1.00.00`, `v1.01.00`, `v1.01.02`).

- **Patch** — fixes and hardening of already-released behavior; no new public capability.
- **Minor** — a new, backward-compatible capability or public surface.
- **Major** — breaks a core invariant or repositions the tool.

A release's quality level is the certification tier it actually passed; a tag never
claims a tier that was not earned. Untiered tags carry their gate evidence instead.

## v1.01.03 — chart axis labels + table pagination (2026-07-16)

**Shipped:** every chart now carries x and y axis labels — the trend and tagging-debt
time-series get day/week (x) and entries (y) titles; the horizontal lane, project, tag,
and tool/area charts get a category + "entries →" + total axis caption. The entries
table is paginated inside a scrolling frame (sticky header) with a rows-per-page toggle
(25 / 50 / 100 / All, default 50), prev/next controls, and a page indicator; `#id` deep
links jump to the page containing the entry and expand it.

**Quality level:** untiered (frontend-only refinement). Gates: backend unchanged
(`test_logboard.py` 31/31, `serve.py --check` 31/0); browser-verified in light and dark —
axis labels present on all charts, pager navigation / size toggle / deep-link jump all
exercised, console clean.

**Carried forward:** none.

## v1.01.02 — live README captures + Bronze certification (2026-07-16)

**Shipped:** README refreshed with light/dark captures of the live dashboard, all
register text redacted before publishing (`demo-light.png`, `demo-dark.png`). Bronze
certification fix wave: anti-DNS-rebinding `Host`-header gate on every route
(+ `allowed_hosts` config), SIGPIPE-safe leak scanners (pre-commit / pre-push / CI all
consume full input), range-scanning pre-push, server-side CI leak-guard workflow,
duplicate-basename guard at load and validate time, and doc corrections. Two new tests
(Host rejection, >100 KB leak) bring the suite to 31.

**Quality level: Bronze / PASS** — certified over 4 review rounds; two fix waves
resolved 3 significant issues (anti-DNS-rebinding gate, SIGPIPE-safe leak scanners,
live-instance redeploy) plus 6 minor, residual an advisory only. Gates:
`test_logboard.py` 31/31; `serve.py --check` 31/0; CI leak-guard green.

**Carried forward:** none. Advisory: optional em-dash trim in prose; path-keying (vs
basename) as a future cleaner fix for the project-collision class.

## v1.01.01 — test suite + write-guard hardening (2026-07-16)

**Shipped:** 28 stdlib unittest tests over synthetic fixtures (parser incl. legacy
quirks and bare-semicolon counts, canon, config validation, `edit_tags` invariants,
HTTP layer with origin/CORS gating, CLI exit codes); fix for marker-blind entry
counting in the write guard (CE36), caught by the suite's first run.

**Quality level:** untiered. Gates at tag time: `test_logboard.py` 28/28 OK;
`serve.py --check` 31 ok / 0 failed on live registers; repo hygiene clean.

**Carried forward:** none.

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

- **Part 2 (unversioned until planned)** — cloud-hosted frontend pointing at the local
  data server; CORS/PNA + `allowed_hosts` enablers already shipped.
