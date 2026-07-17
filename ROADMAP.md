# logboard roadmap

## Versioning policy

`vMAJOR.MINOR.PATCH`, zero-padded (`v1.00.00`, `v1.01.00`, `v1.01.02`).

- **Patch** — fixes and hardening of already-released behavior; no new public capability.
- **Minor** — a new, backward-compatible capability or public surface.
- **Major** — breaks a core invariant or repositions the tool.

A release's quality level is the certification tier it actually passed; a tag never
claims a tier that was not earned. Untiered tags carry their gate evidence instead.

## v2.00.00 — Tagging help + application self-logging (2026-07-16)

**Major** — Tagging help introduces an optional local-LLM dependency and hands entry
text to a model, softening the founding "offline / zero-dependency" invariant to
"your data stays in tools you control." That invariant change is what makes this a
major bump.

**Shipped:**
- **Tagging help** — an LLM-assisted bulk-tagging wizard with a mandatory human
  confirmation gate. Describe the entries to tag + a scope (log types, projects,
  sessions); a **local** model (`claude -p` or Ollama, chosen in settings) returns
  matching IDs; the server intersects them with the real corpus (a hallucinated id
  can never reach a register) and shows them for review; you untick false positives
  and confirm, then the tag — and, if new, its canon line — is written through the
  existing guarded editor. The model receives `{id, summary, cause, fix}` only, never
  file paths.
- **Application self-logging** — logboard captures its own server exceptions and
  client-side JS errors into a gitignored `app-errors.md` (a fifth `app_error` log
  type) and surfaces them in a dedicated App-health panel, kept out of the
  four-register analytics.

**Quality level:** _to be recorded from the certification run before tagging._
Gates: `test_logboard.py` (45 tests incl. mocked-model suggest/apply, ID-intersection,
no-paths-to-model, self-log dedupe, server-exception→clean-500); `serve.py --check`;
browser-verified both features in light and dark (full wizard describe→confirm→apply
against fixtures, new-canon creation, App-health from real triggered errors).

**Why an LLM path (vs deterministic bulk-apply):** the dashboard already supports
lexical filtering (search, `#tag=`, the filterable table), and a "bulk-apply this tag
to the filtered rows" action would tag most keyword-shaped classes (`network`, `config`,
`csp`, …) with zero model exposure and full reproducibility. Tagging help exists for the
case that plain filtering can't reach: grouping entries that share a *concept* but no
token (e.g. clock-skew, off-by-one, and space-form-datetime bugs all under `datetime`).
The default Ollama provider keeps that semantic matching offline. A deterministic
filter-and-bulk-apply action, and persisting a Tagging-help run as a re-runnable rule so
recurring debt isn't re-solved each cycle, are the obvious next steps.

**Carried forward:** deterministic filter-and-bulk-apply + re-runnable tag rules (the
invariant-preserving path for keyword-shaped tags); JSONL self-log (a lighter, safer
write path than the current markdown-grammar reuse); cloud LLM providers with API keys
(behind a loud warning) — all deferred to future opt-in minors.

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
